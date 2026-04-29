"""Core meeting logic — speech processing, status, thresholds."""

import random
import time

from .config import WORD_LIMIT, TIMEOUT_DURATION, WARNING_THRESHOLD, WORDS_PER_SECOND
from .prompts import FEEDBACK_LINES
from .ai import analyze_speech, get_friend_approval, transcribe_audio


def make_status(state: dict) -> str:
    """Generate the status panel markdown."""
    muted_until = state.get("muted_until", 0)
    if muted_until > time.time():
        remaining = int(muted_until - time.time())
        return (
            f"# 🔇 MUTED\n\n"
            f"**{remaining}s remaining**\n\n"
            f"Total words: {state.get('total_words', 0)}\n\n"
            f"Turns: {state.get('turn_count', 0)}"
        )

    warnings = state.get("warnings", 0)
    indicator = "🟡 WARNING" if warnings > 0 else "🟢 ACTIVE"

    return (
        f"# {indicator}\n\n"
        f"Warnings: **{warnings}/2**\n\n"
        f"Total words: {state.get('total_words', 0)}\n\n"
        f"Turns: {state.get('turn_count', 0)}\n\n"
        f"Word limit: {WORD_LIMIT}/turn"
    )


def make_bar(state: dict) -> float:
    """Return a 0-1 progress value for the speech bar."""
    current = state.get("current_words", 0)
    return min(current / WORD_LIMIT, 1.0)


def initial_state() -> dict:
    return {
        "total_words": 0,
        "turn_count": 0,
        "warnings": 0,
        "muted_until": 0,
        "current_words": 0,
    }


def process_audio(
    audio,
    meeting_topic: str,
    chat_history: list,
    friend_history: list,
    state: dict,
):
    """Handle microphone audio input: transcribe then process."""
    if audio is None:
        yield chat_history, friend_history, state, make_status(state), make_bar(state)
        return

    # audio is a tuple (sample_rate, numpy_array) or a filepath string from Gradio
    if isinstance(audio, str):
        audio_path = audio
    else:
        # Gradio Audio with type="filepath" gives a string
        audio_path = audio

    text = transcribe_audio(audio_path)
    if not text or text.startswith("[Transcription failed"):
        chat_history.append({"role": "assistant", "content": f"🎙️ {text}"})
        yield chat_history, friend_history, state, make_status(state), make_bar(state)
        return

    # Show transcription
    chat_history.append({"role": "assistant", "content": f"🎙️ *Transcribed:* {text}"})
    yield chat_history, friend_history, state, make_status(state), make_bar(state)

    # Delegate to the text processing pipeline
    for result in process_speech(text, meeting_topic, chat_history, friend_history, state):
        yield result[0], result[1], result[2], result[3], result[5]  # skip text-clear output


def process_speech(
    text: str,
    meeting_topic: str,
    chat_history: list,
    friend_history: list,
    state: dict,
):
    """Process a speech turn: track words, check limits, call AI, handle decisions."""
    if not text or not text.strip():
        yield chat_history, friend_history, state, make_status(state), "", make_bar(state)
        return

    # ── Check if muted ──
    if state.get("muted_until", 0) > time.time():
        remaining = int(state["muted_until"] - time.time())
        chat_history.append(
            {
                "role": "assistant",
                "content": f"🔇 **YOU ARE MUTED** — {remaining}s remaining. Use this time to reflect on your life choices.",
            }
        )
        yield chat_history, friend_history, state, make_status(state), "", make_bar(state)
        return

    # Clear mute if expired
    if state.get("muted_until", 0) <= time.time():
        state["muted_until"] = 0

    word_count = len(text.split())
    simulated_time = word_count / WORDS_PER_SECOND
    state["total_words"] = state.get("total_words", 0) + word_count
    state["turn_count"] = state.get("turn_count", 0) + 1
    state["current_words"] = word_count

    # Add user message to transcript
    chat_history.append({"role": "user", "content": text})

    # ── Check thresholds ──
    if word_count > WORD_LIMIT:
        state["warnings"] = state.get("warnings", 0) + 1

        if state["warnings"] >= 2:
            state["muted_until"] = time.time() + TIMEOUT_DURATION
            state["warnings"] = 0
            chat_history.append(
                {
                    "role": "assistant",
                    "content": (
                        "# 🔇 TIMEOUT!\n\n"
                        f"**You talked for ~{int(simulated_time)}s with {word_count} words.**\n\n"
                        f"You are muted for **{TIMEOUT_DURATION} seconds**.\n\n"
                        "Go touch grass. Get a coffee. Contemplate brevity."
                    ),
                }
            )
            yield chat_history, friend_history, state, make_status(state), "", make_bar(state)
            return
        else:
            feedback_line = random.choice(FEEDBACK_LINES)
            chat_history.append(
                {
                    "role": "assistant",
                    "content": (
                        f"## ⚠️ Warning {state['warnings']}/2\n\n"
                        f"**{word_count} words** (~{int(simulated_time)}s of talking)\n\n"
                        f"{feedback_line}\n\n"
                        "*Next violation = 2 minute timeout*"
                    ),
                }
            )
    elif word_count > WARNING_THRESHOLD:
        chat_history.append(
            {
                "role": "assistant",
                "content": f"🟡 *Getting wordy... {word_count} words. Limit is {WORD_LIMIT}.*",
            }
        )

    yield chat_history, friend_history, state, make_status(state), "", make_bar(state)

    # ── AI Analysis ──
    analysis = analyze_speech(text, meeting_topic)

    if analysis.get("feedback"):
        chat_history.append(
            {"role": "assistant", "content": f"🤖 **MeetBot:** {analysis['feedback']}"}
        )

    if analysis.get("topic_drift"):
        chat_history.append(
            {"role": "assistant", "content": "🧭 **Topic drift detected!** Stay on track, nomad."}
        )

    yield chat_history, friend_history, state, make_status(state), "", make_bar(state)

    # ── Decision Detection → Friend Approval ──
    if analysis.get("decision_detected") and analysis.get("decision_summary"):
        decision = analysis["decision_summary"]

        friend_history.append(
            {
                "role": "assistant",
                "content": f"📋 **Decision detected:** *{decision}*\n\n⏳ Asking Alex for confirmation...",
            }
        )
        yield chat_history, friend_history, state, make_status(state), "", make_bar(state)

        approval = get_friend_approval(decision)

        if approval["approved"]:
            emoji, verdict = "✅", "APPROVED"
        else:
            emoji, verdict = "❌", "REJECTED"

        friend_history.append(
            {
                "role": "assistant",
                "content": f"## {emoji} {verdict}\n\n**Alex says:** {approval['reason']}",
            }
        )

        chat_history.append(
            {
                "role": "assistant",
                "content": (
                    f"{'✅' if approval['approved'] else '❌'} **Decision {verdict} by Alex:** "
                    f"*{decision}*\n\n> {approval['reason']}"
                ),
            }
        )

    yield chat_history, friend_history, state, make_status(state), "", make_bar(state)
