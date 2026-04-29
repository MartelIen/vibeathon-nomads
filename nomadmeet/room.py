"""Shared server-side meeting room state for multi-user sessions."""

import threading
import time
from dataclasses import dataclass, field

_lock = threading.Lock()


@dataclass
class PendingDecision:
    id: int
    proposer: str
    summary: str
    timestamp: float
    kind: str = "decision"  # "decision" or "timeout"
    target: str | None = None  # who to mute (for timeout requests)
    word_count: int = 0
    resolved: bool = False
    approved: bool | None = None
    resolver: str | None = None
    reason: str | None = None


class MeetingRoom:
    """Thread-safe shared meeting room."""

    def __init__(self):
        self.transcript: list[dict] = []
        self.users: dict[str, dict] = {}
        self.pending_decisions: list[PendingDecision] = []
        self.typing_users: dict[str, str] = {}  # username -> "typing" | "recording"
        self.topic: str = "Q3 planning & team logistics"
        self._decision_counter = 0

    def add_user(self, username: str) -> dict:
        with _lock:
            if username not in self.users:
                self.users[username] = {
                    "total_words": 0,
                    "turn_count": 0,
                    "warnings": 0,
                    "muted_until": 0,
                    "current_words": 0,
                }
                self.transcript.append({
                    "role": "assistant",
                    "content": f"👋 **{username}** joined the meeting.",
                })
            return self.users[username]

    def get_user_state(self, username: str) -> dict:
        with _lock:
            return self.users.get(username, {})

    def add_message(self, role: str, content: str, username: str | None = None):
        with _lock:
            if username and role == "user":
                self.transcript.append({"role": "user", "content": f"**{username}:** {content}"})
            else:
                self.transcript.append({"role": role, "content": content})

    def get_transcript(self) -> list[dict]:
        with _lock:
            return list(self.transcript)

    def set_typing(self, username: str, mode: str | None):
        """Set typing indicator. mode = 'typing', 'recording', or None to clear."""
        with _lock:
            if mode:
                self.typing_users[username] = mode
            else:
                self.typing_users.pop(username, None)

    def get_typing_users(self) -> dict[str, str]:
        with _lock:
            return dict(self.typing_users)

    def add_pending_decision(self, proposer: str, summary: str) -> PendingDecision:
        with _lock:
            self._decision_counter += 1
            d = PendingDecision(
                id=self._decision_counter,
                proposer=proposer,
                summary=summary,
                timestamp=time.time(),
                kind="decision",
            )
            self.pending_decisions.append(d)
            return d

    def add_timeout_request(self, proposer: str, target: str, word_count: int) -> PendingDecision:
        """Request to timeout a user — must be approved by another participant."""
        with _lock:
            self._decision_counter += 1
            d = PendingDecision(
                id=self._decision_counter,
                proposer="MeetBot",
                summary=f"Mute {target} for 2 minutes (over-talking: {word_count} words)",
                timestamp=time.time(),
                kind="timeout",
                target=target,
                word_count=word_count,
            )
            self.pending_decisions.append(d)
            return d

    def resolve_decision(self, decision_id: int, approved: bool, resolver: str, reason: str):
        with _lock:
            for d in self.pending_decisions:
                if d.id == decision_id and not d.resolved:
                    d.resolved = True
                    d.approved = approved
                    d.resolver = resolver
                    d.reason = reason

                    if d.kind == "timeout":
                        if approved and d.target and d.target in self.users:
                            from .config import TIMEOUT_DURATION
                            self.users[d.target]["muted_until"] = time.time() + TIMEOUT_DURATION
                            self.users[d.target]["warnings"] = 0
                            emoji = "🔇"
                            self.transcript.append({
                                "role": "assistant",
                                "content": (
                                    f"🔇 **{d.target} MUTED by {resolver}!** "
                                    f"{TIMEOUT_DURATION}s timeout. ☕\n\n> {reason}"
                                ),
                            })
                        else:
                            self.transcript.append({
                                "role": "assistant",
                                "content": (
                                    f"🛡️ **Timeout for {d.target} REJECTED by {resolver}.**\n\n> {reason}"
                                ),
                            })
                    else:
                        emoji = "✅" if approved else "❌"
                        verdict = "APPROVED" if approved else "REJECTED"
                        self.transcript.append({
                            "role": "assistant",
                            "content": (
                                f"{emoji} **Decision {verdict} by {resolver}:** "
                                f"*{d.summary}*\n\n> {reason}"
                            ),
                        })
                    return d
            return None

    def get_unresolved_decisions(self) -> list[PendingDecision]:
        with _lock:
            return [d for d in self.pending_decisions if not d.resolved]


# ── Global singleton ──
ROOM = MeetingRoom()
