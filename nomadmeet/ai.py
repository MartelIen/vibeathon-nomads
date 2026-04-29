"""AI service calls — speech analysis, friend approval, and transcription."""

import json
from pathlib import Path

from .config import MODEL, client
from .prompts import MONITOR_SYSTEM, FRIEND_SYSTEM


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


def transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file using OpenAI Whisper API."""
    try:
        with open(audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
        return transcript.text
    except Exception as e:
        return f"[Transcription failed: {e}]"
