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
DEFAULT_MODEL = "gemini-3.5-flash-lite"

TIMEOUT_MS = 30_000

# HTTP status codes where retrying can't help.
NO_RETRY_CODES = {400, 401, 403, 404}


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

        # Timeout is in milliseconds, so a hung request can't freeze the app.
        self.client = genai.Client(api_key=api_key, http_options={"timeout": TIMEOUT_MS})
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
                # Bad key / bad request won't fix itself; only retry rate limits and server errors.
                if getattr(e, "code", None) in NO_RETRY_CODES:
                    break
                if attempt < self.retries:
                    time.sleep(1.5)

        raise LLMError(describe_error(last_error))


def describe_error(e: Exception) -> str:
    """Short, user-friendly description of an API failure."""
    code = getattr(e, "code", None)
    if code in (400, 401, 403) and "API key" in str(e):
        return "Gemini rejected the API key. Check GEMINI_API_KEY in your .env file."
    if code == 429:
        return "Gemini rate limit reached. Wait a minute and try again."
    if code == 503:
        return "Gemini is overloaded right now. Try again shortly."
    if code == 404:
        return "Gemini model not found. Check GEMINI_MODEL in your .env file."
    return f"Gemini call failed ({type(e).__name__}: {str(e)[:150]})"
