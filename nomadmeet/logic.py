"""Core meeting logic — speech processing, status, thresholds (multi-user)."""

import random
import time

from .config import WORD_LIMIT, TIMEOUT_DURATION, WARNING_THRESHOLD, WORDS_PER_SECOND
from .prompts import FEEDBACK_LINES
from .ai import analyze_speech, transcribe_audio
from .room import ROOM


def make_user_status(username: str) -> str:
    """Generate the status panel markdown for a specific user."""
    if not username:
        return "# ⏳ Enter a username to join"

    user = ROOM.get_user_state(username)
    if not user:
        return "# ⏳ Enter a username to join"

    muted_until = user.get("muted_until", 0)
    if muted_until > time.time():
        remaining = int(muted_until - time.time())
        return (
            f"# 🔇 MUTED — {username}\n\n"
            f"**{remaining}s remaining**\n\n"
            f"Total words: {user.get('total_words', 0)} | "
            f"Turns: {user.get('turn_count', 0)}"
        )

    warnings = user.get("warnings", 0)
    indicator = "🟡 WARNING" if warnings > 0 else "🟢 ACTIVE"

    online = ", ".join(ROOM.users.keys()) or "—"
    return (
        f"# {indicator} — {username}\n\n"
        f"Warnings: **{warnings}/2**\n\n"
        f"Total words: {user.get('total_words', 0)} | "
        f"Turns: {user.get('turn_count', 0)}\n\n"
        f"Word limit: {WORD_LIMIT}/turn\n\n"
        f"---\n**Online:** {online}"
    )


def make_bar(username: str) -> float:
    """Return a 0-1 progress value for the speech bar."""
    if not username:
        return 0.0
    user = ROOM.get_user_state(username)
    current = user.get("current_words", 0) if user else 0
    return min(current / WORD_LIMIT, 1.0)


def get_pending_decisions_md() -> str:
    """Render pending decisions as markdown for the approver panel."""
    unresolved = ROOM.get_unresolved_decisions()
    if not unresolved:
        return "No pending decisions."
    lines = []
    for d in unresolved:
        lines.append(f"**#{d.id}** by {d.proposer}: *{d.summary}*")
    return "\n\n".join(lines)


def refresh(username: str):
    """Called on a timer to refresh the transcript and status for a user."""
    return (
        ROOM.get_transcript(),
        make_user_status(username),
        make_bar(username),
        get_pending_decisions_md(),
    )


def join_meeting(username: str):
    """Register a user and return initial state."""
    if not username or not username.strip():
        return ROOM.get_transcript(), make_user_status(""), 0.0, get_pending_decisions_md()
    username = username.strip()
    ROOM.add_user(username)
    return (
        ROOM.get_transcript(),
        make_user_status(username),
        make_bar(username),
        get_pending_decisions_md(),
    )


def process_audio(audio, username: str, meeting_topic: str):
    """Handle microphone audio: transcribe then process."""
    if audio is None or not username:
        return ROOM.get_transcript(), make_user_status(username), make_bar(username), get_pending_decisions_md()

    text = transcribe_audio(audio)
    if not text or text.startswith("[Transcription failed"):
        ROOM.add_message("assistant", f"🎙️ {text}")
        return ROOM.get_transcript(), make_user_status(username), make_bar(username), get_pending_decisions_md()

    ROOM.add_message("assistant", f"🎙️ *{username} transcribed:* {text}")
    return process_speech_inner(text, username, meeting_topic)


def process_speech(text: str, username: str, meeting_topic: str):
    """Process a text speech turn."""
    if not text or not text.strip() or not username:
        return ROOM.get_transcript(), make_user_status(username), "", make_bar(username), get_pending_decisions_md()

    result = process_speech_inner(text.strip(), username.strip(), meeting_topic)
    # return with text-clear
    return result[0], result[1], "", result[2], result[3]


def process_speech_inner(text: str, username: str, meeting_topic: str):
    """Core speech processing — shared by text and audio paths."""
    user = ROOM.get_user_state(username)
    if not user:
        ROOM.add_user(username)
        user = ROOM.get_user_state(username)

    # ── Check if muted ──
    if user.get("muted_until", 0) > time.time():
        remaining = int(user["muted_until"] - time.time())
        ROOM.add_message(
            "assistant",
            f"🔇 **{username} IS MUTED** — {remaining}s remaining.",
        )
        return ROOM.get_transcript(), make_user_status(username), make_bar(username), get_pending_decisions_md()

    if user.get("muted_until", 0) <= time.time():
        user["muted_until"] = 0

    word_count = len(text.split())
    simulated_time = word_count / WORDS_PER_SECOND
    user["total_words"] = user.get("total_words", 0) + word_count
    user["turn_count"] = user.get("turn_count", 0) + 1
    user["current_words"] = word_count

    ROOM.add_message("user", text, username=username)

    # ── Check thresholds ──
    if word_count > WORD_LIMIT:
        user["warnings"] = user.get("warnings", 0) + 1

        if user["warnings"] >= 2:
            user["muted_until"] = time.time() + TIMEOUT_DURATION
            user["warnings"] = 0
            ROOM.add_message(
                "assistant",
                (
                    f"# 🔇 {username} TIMED OUT!\n\n"
                    f"**~{int(simulated_time)}s / {word_count} words.**\n\n"
                    f"Muted for **{TIMEOUT_DURATION} seconds**. ☕"
                ),
            )
            return ROOM.get_transcript(), make_user_status(username), make_bar(username), get_pending_decisions_md()
        else:
            feedback_line = random.choice(FEEDBACK_LINES)
            ROOM.add_message(
                "assistant",
                (
                    f"## ⚠️ Warning {user['warnings']}/2 for {username}\n\n"
                    f"**{word_count} words** (~{int(simulated_time)}s)\n\n"
                    f"{feedback_line}\n\n"
                    "*Next violation = 2 minute timeout*"
                ),
            )
    elif word_count > WARNING_THRESHOLD:
        ROOM.add_message(
            "assistant",
            f"🟡 *{username} getting wordy... {word_count} words. Limit is {WORD_LIMIT}.*",
        )

    # ── AI Analysis ──
    analysis = analyze_speech(text, meeting_topic)

    if analysis.get("feedback"):
        ROOM.add_message("assistant", f"🤖 **MeetBot** to {username}: {analysis['feedback']}")

    if analysis.get("topic_drift"):
        ROOM.add_message("assistant", f"🧭 **{username} drifted off-topic!** Stay on track.")

    # ── Decision Detection → Pending for human approval ──
    if analysis.get("decision_detected") and analysis.get("decision_summary"):
        decision = analysis["decision_summary"]
        d = ROOM.add_pending_decision(username, decision)
        ROOM.add_message(
            "assistant",
            f"📋 **Decision #{d.id} by {username}:** *{decision}*\n\n"
            f"⏳ Waiting for a friend to approve or reject...",
        )

    return ROOM.get_transcript(), make_user_status(username), make_bar(username), get_pending_decisions_md()


def approve_decision(decision_id_str: str, reason: str, username: str):
    """Approve a pending decision."""
    try:
        did = int(decision_id_str)
    except (ValueError, TypeError):
        return ROOM.get_transcript(), "⚠️ Enter a valid decision # number.", get_pending_decisions_md()

    result = ROOM.resolve_decision(did, approved=True, resolver=username, reason=reason or "Looks good to me!")
    if not result:
        return ROOM.get_transcript(), "⚠️ Decision not found or already resolved.", get_pending_decisions_md()
    return ROOM.get_transcript(), f"✅ Decision #{did} approved!", get_pending_decisions_md()


def reject_decision(decision_id_str: str, reason: str, username: str):
    """Reject a pending decision."""
    try:
        did = int(decision_id_str)
    except (ValueError, TypeError):
        return ROOM.get_transcript(), "⚠️ Enter a valid decision # number.", get_pending_decisions_md()

    result = ROOM.resolve_decision(did, approved=False, resolver=username, reason=reason or "Nah, bad idea.")
    if not result:
        return ROOM.get_transcript(), "⚠️ Decision not found or already resolved.", get_pending_decisions_md()
    return ROOM.get_transcript(), f"❌ Decision #{did} rejected!", get_pending_decisions_md()
