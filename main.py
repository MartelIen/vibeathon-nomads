"""
NomadMeet — The meeting app that tells digital nomads to shut up.
Real-time speech monitoring, auto-timeout, and AI friend approval for decisions.
"""

import json
import os
import random
import time

import gradio as gr
from openai import OpenAI

# ── Config ──────────────────────────────────────────────────────────────────
WORD_LIMIT = 150  # max words per turn
TIMEOUT_DURATION = 120  # seconds muted
WARNING_THRESHOLD = 100  # words before soft warning
WORDS_PER_SECOND = 2.5  # simulate speaking speed

client = OpenAI()  # uses OPENAI_API_KEY env var
MODEL = "gpt-4o-mini"

# ── System Prompts ──────────────────────────────────────────────────────────
MONITOR_SYSTEM = """You are MeetBot, a snarky meeting monitor for NomadMeet — a meeting app for digital nomads.
Analyze the user's speech turn and return ONLY valid JSON (no markdown, no code fences):
{
  "over_talking": true/false,
  "topic_drift": true/false,
  "decision_detected": true/false,
  "decision_summary": "short summary or null",
  "feedback": "one snarky sentence about their speaking"
}
The meeting topic is provided. Be concise. If they ramble, roast them lightly.
If they make a decision or proposal (e.g. "let's do X", "I think we should", "I propose"), set decision_detected=true."""

FRIEND_SYSTEM = """You are Alex, the user's digital nomad travel buddy. You're slightly hungover, sitting in a café in Lisbon, and very opinionated.
When asked to confirm a decision, you either APPROVE or REJECT it.
You reject about 30% of decisions for funny, relatable reasons.
Return ONLY valid JSON (no markdown, no code fences):
{
  "approved": true/false,
  "reason": "your 1-2 sentence hot take"
}
Be funny, human, and slightly chaotic. Reference nomad life (coworking spaces, visa runs, bad WiFi, etc)."""

FEEDBACK_LINES = [
    "🎤 Fascinating. Perhaps let someone else have a turn?",
    "📢 TL;DR would be great right about now.",
    "⏰ You've been talking longer than my last relationship.",
    "🗣️ Even your WiFi wants you to stop buffering.",
    "😴 I think the coworking space fell asleep.",
    "🌍 You've spoken long enough to cross a timezone.",
]


# ── AI Calls ────────────────────────────────────────────────────────────────
def analyze_speech(text: str, meeting_topic: str) -> dict:
    """Call GPT to analyze a speech turn."""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": MONITOR_SYSTEM},
                {
                    "role": "user",
                    "content": f"Meeting topic: {meeting_topic}\n\nSpeech turn:\n{text}",
                },
            ],
            temperature=0.7,
            max_tokens=200,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {
            "over_talking": False,
            "topic_drift": False,
            "decision_detected": False,
            "decision_summary": None,
            "feedback": f"(Analysis unavailable: {e})",
        }


def get_friend_approval(decision: str) -> dict:
    """Ask Alex the friend agent to approve/reject a decision."""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": FRIEND_SYSTEM},
                {
                    "role": "user",
                    "content": f'Should we do this? Decision: "{decision}"',
                },
            ],
            temperature=0.9,
            max_tokens=150,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {"approved": False, "reason": f"(Alex is offline: {e})"}


# ── Core Logic ──────────────────────────────────────────────────────────────
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
            # MUTE!
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
            {
                "role": "assistant",
                "content": f"🤖 **MeetBot:** {analysis['feedback']}",
            }
        )

    if analysis.get("topic_drift"):
        chat_history.append(
            {
                "role": "assistant",
                "content": "🧭 **Topic drift detected!** Stay on track, nomad.",
            }
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


# ── Sample texts for demo ──────────────────────────────────────────────────
SAMPLE_SHORT = "I think the new landing page looks great. Let's ship it."

SAMPLE_LONG = (
    "So basically what I was thinking is that we should probably consider maybe "
    "looking into the possibility of potentially exploring some alternative options "
    "for our coworking space situation because honestly the WiFi here in Bali has "
    "been absolutely terrible lately and I can't even join a Zoom call without "
    "dropping out at least three times and then there's the whole visa situation "
    "which is just a nightmare because I have to do a visa run every 30 days and "
    "it's getting really expensive flying to Singapore and back every month and "
    "I was also thinking about maybe we should look into getting a virtual mailbox "
    "service because I keep getting important documents sent to my parents house "
    "and they have to scan everything and send it to me and it's just not a "
    "sustainable solution long term especially when we're dealing with tax documents "
    "and legal stuff that really needs to be handled properly and on time and "
    "speaking of taxes has anyone figured out the whole tax residency thing because "
    "I've been talking to three different accountants and they all say different things."
)

SAMPLE_DECISION = (
    "I think we should move the entire team to Lisbon for Q3. "
    "The coworking spaces are better, the food is amazing, and "
    "the timezone works for both US and EU clients. Let's do it."
)


# ── UI ──────────────────────────────────────────────────────────────────────
THEME = gr.themes.Soft(
    primary_hue="orange",
    secondary_hue="blue",
    font=gr.themes.GoogleFont("Inter"),
)

CSS = """
.muted-overlay { background: #ff000022; border: 3px solid red; border-radius: 12px; }
.container { max-width: 1200px; margin: auto; }
#speech-bar { transition: all 0.3s ease; }
"""

with gr.Blocks(title="NomadMeet") as app:
    # State
    state = gr.State(
        {
            "total_words": 0,
            "turn_count": 0,
            "warnings": 0,
            "muted_until": 0,
            "current_words": 0,
        }
    )

    # Header
    gr.Markdown(
        """
        # 🌍 NomadMeet
        ### The meeting app that tells digital nomads to shut up.
        *Real-time speech monitoring • Auto-timeout • AI friend approval*
        """
    )

    with gr.Row():
        meeting_topic = gr.Textbox(
            value="Q3 planning & team logistics",
            label="📋 Meeting Topic",
            scale=3,
        )

    with gr.Row(equal_height=True):
        # ── Left: Meeting Panel ──
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                label="📞 Meeting Room",
                height=450,
            )

            speech_bar = gr.Slider(
                minimum=0,
                maximum=1,
                value=0,
                label="🎤 Speech Meter (words used / limit)",
                interactive=False,
                elem_id="speech-bar",
            )

            with gr.Row():
                speech_input = gr.Textbox(
                    label="🎤 Your microphone (type what you'd say)",
                    placeholder="Start talking...",
                    lines=3,
                    scale=4,
                )
                send_btn = gr.Button("📤 Send", variant="primary", scale=1)

            gr.Markdown("**⚡ Quick Demo Buttons:**")
            with gr.Row():
                btn_short = gr.Button("💬 Say something short")
                btn_long = gr.Button("🗣️ Ramble on and on")
                btn_decision = gr.Button("🤔 Propose a decision")

        # ── Right: Status + Friend Panel ──
        with gr.Column(scale=2):
            status_display = gr.Markdown(
                value="# 🟢 ACTIVE\n\nWarnings: **0/2**\n\nTotal words: 0\n\nTurns: 0\n\nWord limit: 150/turn",
            )

            gr.Markdown("---")

            friend_chat = gr.Chatbot(
                label="🧑‍🤝‍🧑 Alex (Your Friend Agent)",
                height=250,
                value=[
                    {
                        "role": "assistant",
                        "content": (
                            "☕ *Alex is online from a café in Lisbon*\n\n"
                            "Hey! I'll review any decisions you make. "
                            "No pressure, but I *will* judge you."
                        ),
                    }
                ],
            )

    # ── Event handlers ──
    submit_args = dict(
        fn=process_speech,
        inputs=[speech_input, meeting_topic, chatbot, friend_chat, state],
        outputs=[chatbot, friend_chat, state, status_display, speech_input, speech_bar],
    )

    send_btn.click(**submit_args)
    speech_input.submit(**submit_args)

    btn_short.click(lambda: SAMPLE_SHORT, outputs=speech_input).then(**submit_args)
    btn_long.click(lambda: SAMPLE_LONG, outputs=speech_input).then(**submit_args)
    btn_decision.click(lambda: SAMPLE_DECISION, outputs=speech_input).then(**submit_args)


if __name__ == "__main__":
    app.launch(theme=THEME, css=CSS)
