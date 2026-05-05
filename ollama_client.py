"""
ollama_client.py
────────────────
Thin wrapper around the Ollama /api/chat endpoint.
All network I/O lives here; nothing else in the project should import urllib.

"""

import json
import re
import time
import urllib.request
import urllib.error
from typing import Optional

from config import MODEL, OLLAMA_URL, TIMEOUT, MAX_RETRIES, RETRY_BACKOFF


# ── Custom exceptions ─────────────────────────────────────────────────────────

class ContextWindowError(Exception):
    """
    Raised when Ollama reports that the prompt exceeds the model's context
    window.  The converter uses this signal to halve the chunk and retry.
    """


_CONTEXT_OVERFLOW_MARKERS = (
    "context window",
    "context length",
    "prompt is too long",
    "exceeds maximum",
    "token limit",
    "too many tokens",
)


def _is_context_overflow(message: str) -> bool:
    low = message.lower()
    return any(marker in low for marker in _CONTEXT_OVERFLOW_MARKERS)


# ── Post-processing helpers ───────────────────────────────────────────────────

# Matches the start of a markdown explanation section that sometimes leaks
# after the closing brace of a Java class.  Patterns caught:
#   ### Explanation:
#   ## Summary
#   - **Something**: …
#   * **Something**: …
_TRAILING_PROSE_RE = re.compile(
    r'\n(?:#{1,4}\s+\w|\s*[-*]\s+\*\*|\s*\d+\.\s+\*\*)',
    re.MULTILINE,
)


def strip_explanation(text: str) -> str:
    """
    Remove markdown explanation / summary sections that models sometimes
    append after the Java code despite being instructed not to.

    Strategy: find the last top-level closing brace (end of Java class),
    then check whether everything after it looks like a markdown prose
    section.  If so, truncate at the closing brace.

    Args:
        text: Model output, possibly with trailing explanation prose.

    Returns:
        Cleaned text ending at (or near) the final closing brace.
    """
    # Locate the rightmost stand-alone closing brace on its own line,
    # which marks the end of the top-level Java class.
    last_brace_match = None
    for m in re.finditer(r'^}', text, re.MULTILINE):
        last_brace_match = m

    if last_brace_match is None:
        return text  # no brace found — leave as-is

    end_of_class = last_brace_match.end()
    trailing = text[end_of_class:]

    if trailing.strip() and _TRAILING_PROSE_RE.search(trailing):
        return text[:end_of_class]

    return text


def strip_fences(text: str) -> str:
    """
    Remove ALL wrapping markdown code fences (``` or ```java, etc.) that
    the model sometimes adds despite being told not to, then strip any
    trailing explanation prose.

    Loops on fences until no more remain, handling models that occasionally
    double-wrap their output.

    Args:
        text: Raw model output.

    Returns:
        Cleaned text with all fences and trailing prose removed.
    """
    while True:
        lines = text.strip().splitlines()
        if not lines:
            return text.strip()
        changed = False
        if lines[0].startswith("```"):
            lines = lines[1:]
            changed = True
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
            changed = True
        text = "\n".join(lines)
        if not changed:
            break

    return strip_explanation(text)


# ── Public API ────────────────────────────────────────────────────────────────

def call_ollama(system: str, user: str) -> str:
    """
    Send a prompt to the locally running Ollama model and return the
    response text.

    Retries up to MAX_RETRIES times on transient network errors, with
    exponential back-off starting at RETRY_BACKOFF seconds.

    Args:
        system: The system prompt that sets model behaviour.
        user:   The user-turn prompt containing the content to process.

    Returns:
        The raw response string from the model.

    Raises:
        ContextWindowError:    If Ollama reports the prompt is too long.
        urllib.error.URLError: If Ollama cannot be reached after all retries.
        RuntimeError:          If the response body cannot be decoded.
    """
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        OLLAMA_URL, data=data, headers={"Content-Type": "application/json"}
    )

    last_exc: Optional[Exception] = None
    wait = RETRY_BACKOFF

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode()

            parsed = json.loads(body)

            if "message" in parsed:
                return parsed["message"]["content"]

            if "error" in parsed:
                err_text = parsed["error"]
                if _is_context_overflow(err_text):
                    raise ContextWindowError(err_text)
                raise RuntimeError(f"Ollama error: {err_text}")

            raise RuntimeError(f"Unexpected Ollama response shape: {body[:200]}")

        except ContextWindowError:
            raise   # never retry context-overflow — the caller must re-chunk

        except urllib.error.HTTPError as exc:
            # Some Ollama builds return 400/413 with a JSON body for overflow
            try:
                body = exc.read().decode()
                if _is_context_overflow(body):
                    raise ContextWindowError(body)
            except ContextWindowError:
                raise
            except Exception:
                pass
            last_exc = exc
            if attempt < MAX_RETRIES:
                print(f"\n      [retry {attempt}/{MAX_RETRIES - 1}] "
                      f"HTTP {exc.code} — waiting {wait:.0f}s …", flush=True)
                time.sleep(wait)
                wait *= 2
            else:
                raise

        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                print(f"\n      [retry {attempt}/{MAX_RETRIES - 1}] "
                      f"network error — waiting {wait:.0f}s …", flush=True)
                time.sleep(wait)
                wait *= 2
            else:
                raise

        except RuntimeError:
            raise

    raise last_exc  # type: ignore[misc]