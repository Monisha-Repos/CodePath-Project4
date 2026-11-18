"""
Thin wrapper around the Gemini API.

Everything that talks to the LLM goes through GeminiClient.generate(), so
switching models or providers only means changing this file.
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

# Override with the GEMINI_MODEL environment variable if needed.
DEFAULT_MODEL = "gemini-flash-lite-latest"


class LLMError(Exception):
    """Raised when the LLM can't be reached or returns nothing usable."""


class GeminiClient:
    """Calls Gemini with a single retry, and logs every call."""

    def __init__(self, model: str = None, retries: int = 1):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass  # .env support is optional; a shell variable works too

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError(
                "Missing GEMINI_API_KEY. Copy .env.example to .env and add your key."
            )

        from google import genai  # imported here so tests don't need the SDK

        self.client = genai.Client(api_key=api_key)
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.retries = retries

    def generate(self, prompt: str, json_output: bool = False) -> str:
        """Sends one prompt and returns the response text. Raises LLMError on failure."""
        config = {"temperature": 0.2}
        if json_output:
            config["response_mime_type"] = "application/json"

        last_error = None
        for attempt in range(1 + self.retries):
            start = time.perf_counter()
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                text = (response.text or "").strip()
                logger.info(
                    "LLM call ok (model=%s, attempt=%d, %.2fs, %d chars)",
                    self.model, attempt + 1, time.perf_counter() - start, len(text),
                )
                if not text:
                    raise LLMError("Empty response from model")
                return text
            except Exception as e:  # network errors, rate limits, empty output
                last_error = e
                logger.warning("LLM call failed (attempt %d): %s: %s", attempt + 1, type(e).__name__, e)
                if attempt < self.retries:
                    time.sleep(1.5)

        raise LLMError(f"LLM call failed: {type(last_error).__name__}: {last_error}")
