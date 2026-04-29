"""Gradio UI definition for NomadMeet — multi-user version."""

import gradio as gr

from .logic import (
    process_speech,
    process_audio,
    join_meeting,
    refresh,
    approve_decision,
    reject_decision,
    make_user_status,
    get_pending_decisions_md,
)
from .room import ROOM
from .samples import SAMPLE_SHORT, SAMPLE_LONG, SAMPLE_DECISION

THEME = gr.themes.Soft(
    primary_hue="orange",
    secondary_hue="blue",
    font=gr.themes.GoogleFont("Inter"),
)

CSS = """
.container { max-width: 1200px; margin: auto; }
#speech-bar { transition: all 0.3s ease; }
"""


def build_app() -> gr.Blocks:
    with gr.Blocks(title="NomadMeet") as app:
        # Per-session username state
        username_state = gr.State("")

        # Header
        gr.Markdown(
            """
            # 🌍 NomadMeet
            ### The meeting app that tells digital nomads to shut up.
            *Real-time speech monitoring • Auto-timeout • Friend approval*
            """
        )

        # ── Join bar ──
        with gr.Row():
            username_input = gr.Textbox(
                label="👤 Your Name",
                placeholder="Enter username...",
                scale=2,
            )
            join_btn = gr.Button("🚀 Join Meeting", variant="primary", scale=1)
            meeting_topic = gr.Textbox(
                value="Q3 planning & team logistics",
                label="📋 Meeting Topic",
                scale=2,
            )

        with gr.Row(equal_height=True):
            # ── Left: Meeting Panel ──
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    label="📞 Meeting Room",
                    height=450,
                )

                speech_bar = gr.Slider(
                    minimum=0, maximum=1, value=0,
                    label="🎤 Speech Meter (words used / limit)",
                    interactive=False,
                    elem_id="speech-bar",
                )

                with gr.Row():
                    speech_input = gr.Textbox(
                        label="⌨️ Type what you'd say",
                        placeholder="Join the meeting first...",
                        lines=3,
                        scale=4,
                    )
                    send_btn = gr.Button("📤 Send", variant="primary", scale=1)

                mic_input = gr.Audio(
                    sources=["microphone"],
                    type="filepath",
                    label="🎙️ Or use your microphone",
                )

                gr.Markdown("**⚡ Quick Demo:**")
                with gr.Row():
                    btn_short = gr.Button("💬 Short")
                    btn_long = gr.Button("🗣️ Ramble")
                    btn_decision = gr.Button("🤔 Decision")

            # ── Right: Status + Decision Approval ──
            with gr.Column(scale=2):
                status_display = gr.Markdown(
                    value="# ⏳ Enter a username to join",
                )

                gr.Markdown("---")
                gr.Markdown("### 📋 Pending Decisions")
                pending_display = gr.Markdown(value="No pending decisions.")

                with gr.Row():
                    decision_id_input = gr.Textbox(
                        label="Decision #",
                        placeholder="#",
                        scale=1,
                    )
                    decision_reason = gr.Textbox(
                        label="Your reason",
                        placeholder="Why?",
                        scale=2,
                    )
                with gr.Row():
                    approve_btn = gr.Button("✅ Approve", variant="primary")
                    reject_btn = gr.Button("❌ Reject", variant="stop")

                decision_result = gr.Markdown(value="")

        # ── Join handler ──
        def on_join(name):
            name = name.strip()
            if not name:
                return "", ROOM.get_transcript(), make_user_status(""), 0.0, get_pending_decisions_md()
            transcript, status, bar, pending = join_meeting(name)
            return name, transcript, status, bar, pending

        join_btn.click(
            fn=on_join,
            inputs=[username_input],
            outputs=[username_state, chatbot, status_display, speech_bar, pending_display],
        )
        username_input.submit(
            fn=on_join,
            inputs=[username_input],
            outputs=[username_state, chatbot, status_display, speech_bar, pending_display],
        )

        # ── Text speech handler ──
        text_args = dict(
            fn=process_speech,
            inputs=[speech_input, username_state, meeting_topic],
            outputs=[chatbot, status_display, speech_input, speech_bar, pending_display],
        )
        send_btn.click(**text_args)
        speech_input.submit(**text_args)

        btn_short.click(lambda: SAMPLE_SHORT, outputs=speech_input).then(**text_args)
        btn_long.click(lambda: SAMPLE_LONG, outputs=speech_input).then(**text_args)
        btn_decision.click(lambda: SAMPLE_DECISION, outputs=speech_input).then(**text_args)

        # ── Mic handler ──
        mic_input.stop_recording(
            fn=process_audio,
            inputs=[mic_input, username_state, meeting_topic],
            outputs=[chatbot, status_display, speech_bar, pending_display],
        )

        # ── Decision approval/rejection ──
        approve_btn.click(
            fn=approve_decision,
            inputs=[decision_id_input, decision_reason, username_state],
            outputs=[chatbot, decision_result, pending_display],
        )
        reject_btn.click(
            fn=reject_decision,
            inputs=[decision_id_input, decision_reason, username_state],
            outputs=[chatbot, decision_result, pending_display],
        )

        # ── Auto-refresh every 3s so all users see updates ──
        timer = gr.Timer(3)
        timer.tick(
            fn=refresh,
            inputs=[username_state],
            outputs=[chatbot, status_display, speech_bar, pending_display],
        )

    return app
