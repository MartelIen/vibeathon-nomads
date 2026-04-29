"""FastAPI backend with WebSocket for real-time multi-user meeting."""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .room import ROOM
from .config import WORD_LIMIT, TIMEOUT_DURATION, WARNING_THRESHOLD, WORDS_PER_SECOND
from .prompts import FEEDBACK_LINES
from .ai import analyze_speech, transcribe_audio
import random
import tempfile

app = FastAPI(title="NomadMeet")

STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── WebSocket connection manager ───────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, WebSocket] = {}  # username -> ws

    async def connect(self, username: str, ws: WebSocket):
        await ws.accept()
        self.connections[username] = ws

    def disconnect(self, username: str):
        self.connections.pop(username, None)

    async def broadcast(self, message: dict):
        dead = []
        for uname, ws in self.connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(uname)
        for d in dead:
            self.connections.pop(d, None)

    async def send_to(self, username: str, message: dict):
        ws = self.connections.get(username)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.connections.pop(username, None)


manager = ConnectionManager()


def get_full_state(username: str) -> dict:
    """Build the full state payload for a user."""
    user = ROOM.get_user_state(username) or {}
    muted_until = user.get("muted_until", 0)
    muted_remaining = max(0, int(muted_until - time.time())) if muted_until > time.time() else 0

    return {
        "type": "state",
        "transcript": ROOM.get_transcript(),
        "users": list(ROOM.users.keys()),
        "user_state": {
            "username": username,
            "total_words": user.get("total_words", 0),
            "turn_count": user.get("turn_count", 0),
            "warnings": user.get("warnings", 0),
            "muted_remaining": muted_remaining,
            "current_words": user.get("current_words", 0),
            "word_limit": WORD_LIMIT,
        },
        "pending_decisions": [
            {
                "id": d.id,
                "proposer": d.proposer,
                "summary": d.summary,
            }
            for d in ROOM.get_unresolved_decisions()
        ],
    }


def process_speech_sync(text: str, username: str) -> list[dict]:
    """Process speech and return new messages to broadcast."""
    user = ROOM.get_user_state(username)
    if not user:
        ROOM.add_user(username)
        user = ROOM.get_user_state(username)

    # Check muted
    if user.get("muted_until", 0) > time.time():
        remaining = int(user["muted_until"] - time.time())
        ROOM.add_message("assistant", f"🔇 **{username} IS MUTED** — {remaining}s remaining.")
        return []

    if user.get("muted_until", 0) <= time.time():
        user["muted_until"] = 0

    word_count = len(text.split())
    simulated_time = word_count / WORDS_PER_SECOND
    user["total_words"] = user.get("total_words", 0) + word_count
    user["turn_count"] = user.get("turn_count", 0) + 1
    user["current_words"] = word_count

    ROOM.add_message("user", text, username=username)

    # Thresholds
    if word_count > WORD_LIMIT:
        user["warnings"] = user.get("warnings", 0) + 1
        if user["warnings"] >= 2:
            user["muted_until"] = time.time() + TIMEOUT_DURATION
            user["warnings"] = 0
            ROOM.add_message("assistant", f"🔇 **{username} TIMED OUT!** ~{int(simulated_time)}s / {word_count} words. Muted for {TIMEOUT_DURATION}s. ☕")
        else:
            line = random.choice(FEEDBACK_LINES)
            ROOM.add_message("assistant", f"⚠️ **Warning {user['warnings']}/2 for {username}** — {word_count} words (~{int(simulated_time)}s). {line} *Next violation = timeout!*")
    elif word_count > WARNING_THRESHOLD:
        ROOM.add_message("assistant", f"🟡 {username} getting wordy... {word_count}/{WORD_LIMIT} words.")

    # AI analysis (runs synchronously, but that's fine for demo)
    analysis = analyze_speech(text, ROOM.topic)

    if analysis.get("feedback"):
        ROOM.add_message("assistant", f"🤖 **MeetBot** → {username}: {analysis['feedback']}")

    if analysis.get("topic_drift"):
        ROOM.add_message("assistant", f"🧭 **{username} drifted off-topic!** Stay on track, nomad.")

    if analysis.get("decision_detected") and analysis.get("decision_summary"):
        decision = analysis["decision_summary"]
        d = ROOM.add_pending_decision(username, decision)
        ROOM.add_message("assistant", f"📋 **Decision #{d.id} by {username}:** {decision} — ⏳ Waiting for a friend to approve or reject...")

    return []


# ── Routes ─────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.websocket("/ws/{username}")
async def websocket_endpoint(ws: WebSocket, username: str):
    await manager.connect(username, ws)
    ROOM.add_user(username)

    # Send initial state
    await manager.broadcast(get_full_state(username))

    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "speech":
                text = data.get("text", "").strip()
                if text:
                    process_speech_sync(text, username)
                # Broadcast updated state to all
                for uname in list(manager.connections.keys()):
                    await manager.send_to(uname, get_full_state(uname))

            elif action == "approve":
                did = data.get("decision_id")
                reason = data.get("reason", "Looks good to me!")
                try:
                    ROOM.resolve_decision(int(did), approved=True, resolver=username, reason=reason)
                except Exception:
                    pass
                for uname in list(manager.connections.keys()):
                    await manager.send_to(uname, get_full_state(uname))

            elif action == "reject":
                did = data.get("decision_id")
                reason = data.get("reason", "Nah, bad idea.")
                try:
                    ROOM.resolve_decision(int(did), approved=False, resolver=username, reason=reason)
                except Exception:
                    pass
                for uname in list(manager.connections.keys()):
                    await manager.send_to(uname, get_full_state(uname))

            elif action == "ping":
                # Periodic refresh
                await manager.send_to(username, get_full_state(username))

    except WebSocketDisconnect:
        manager.disconnect(username)
        ROOM.add_message("assistant", f"👋 **{username}** left the meeting.")
        for uname in list(manager.connections.keys()):
            await manager.send_to(uname, get_full_state(uname))


@app.post("/api/audio/{username}")
async def upload_audio(username: str, file: UploadFile = File(...)):
    """Handle audio file upload for transcription."""
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    text = transcribe_audio(tmp_path)
    if text and not text.startswith("[Transcription failed"):
        ROOM.add_message("assistant", f"🎙️ *{username} (voice):*")
        process_speech_sync(text, username)
        # Broadcast
        for uname in list(manager.connections.keys()):
            await manager.send_to(uname, get_full_state(uname))
        return {"text": text}
    return {"error": text}
