"""Gradio UI definition for NomadMeet."""

import gradio as gr

from .config import WORD_LIMIT
from .logic import process_speech, process_audio, make_status, make_bar, initial_state
from .samples import SAMPLE_SHORT, SAMPLE_LONG, SAMPLE_DECISION

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


def build_app() -> gr.Blocks:
    with gr.Blocks(title="NomadMeet") as app:
        state = gr.State(initial_state())

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
                    minimum=0, maximum=1, value=0,
                    label="🎤 Speech Meter (words used / limit)",
                    interactive=False,
                    elem_id="speech-bar",
                )

                # Text input
                with gr.Row():
                    speech_input = gr.Textbox(
                        label="⌨️ Type what you'd say",
                        placeholder="Start talking...",
                        lines=3,
                        scale=4,
                    )
                    send_btn = gr.Button("📤 Send", variant="primary", scale=1)

                # Microphone input
                mic_input = gr.Audio(
                    sources=["microphone"],
                    type="filepath",
                    label="🎙️ Or use your microphone",
                )

                gr.Markdown("**⚡ Quick Demo Buttons:**")
                with gr.Row():
                    btn_short = gr.Button("💬 Say something short")
                    btn_long = gr.Button("🗣️ Ramble on and on")
                    btn_decision = gr.Button("🤔 Propose a decision")

            # ── Right: Status + Friend Panel ──
            with gr.Column(scale=2):
                status_display = gr.Markdown(
                    value=make_status(initial_state()),
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

        # ── Event handlers: text input ──
        text_args = dict(
            fn=process_speech,
            inputs=[speech_input, meeting_topic, chatbot, friend_chat, state],
            outputs=[chatbot, friend_chat, state, status_display, speech_input, speech_bar],
        )
        send_btn.click(**text_args)
        speech_input.submit(**text_args)

        btn_short.click(lambda: SAMPLE_SHORT, outputs=speech_input).then(**text_args)
        btn_long.click(lambda: SAMPLE_LONG, outputs=speech_input).then(**text_args)
        btn_decision.click(lambda: SAMPLE_DECISION, outputs=speech_input).then(**text_args)

        # ── Event handler: microphone input ──
        mic_args = dict(
            fn=process_audio,
            inputs=[mic_input, meeting_topic, chatbot, friend_chat, state],
            outputs=[chatbot, friend_chat, state, status_display, speech_bar],
        )
        mic_input.stop_recording(**mic_args)

    return app
