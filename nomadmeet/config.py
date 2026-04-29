"""Configuration constants for NomadMeet."""

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

WORD_LIMIT = 150  # max words per turn
TIMEOUT_DURATION = 120  # seconds muted
WARNING_THRESHOLD = 100  # words before soft warning
WORDS_PER_SECOND = 2.5  # simulate speaking speed

MODEL = "gpt-4o-mini"

client = OpenAI()  # loads OPENAI_API_KEY from .env via dotenv
