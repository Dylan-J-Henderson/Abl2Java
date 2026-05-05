"""
config.py
─────────
Central configuration for ABL2Java.
Edit the values here; no other file needs to change.
"""

import os
from pathlib import Path

# ── Ollama ────────────────────────────────────────────────────────────────────
MODEL      = os.getenv("MODEL",      "qwen2.5-coder:3b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
TIMEOUT    = int(os.getenv("TIMEOUT", "600"))

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", str(BASE_DIR / "samples")))
OUTPUT_DIR  = Path(os.getenv("OUTPUT_DIR",  str(BASE_DIR / "java_output")))

# ── File types ────────────────────────────────────────────────────────────────
# .p  = procedure file
# .cls = class file
# .w  = window / GUI file
# .i  = include file
# .t  = temp-table definition file
EXTENSIONS = {".p", ".cls", ".w", ".i", ".t"}

# ── Chunking ──────────────────────────────────────────────────────────────────
# Files with more lines than this are split into chunks before conversion.
CHUNK_THRESHOLD    = int(os.getenv("CHUNK_THRESHOLD",    "300"))
# Ideal maximum line-count per chunk sent to the model.
TARGET_CHUNK_LINES = int(os.getenv("TARGET_CHUNK_LINES", "150"))
# Floor: never split a chunk below this size (avoids degenerate 1-line chunks).
MIN_CHUNK_LINES    = int(os.getenv("MIN_CHUNK_LINES",    "20"))

# ── Retry / resilience ────────────────────────────────────────────────────────
# How many times to retry a failed Ollama call before giving up.
MAX_RETRIES        = int(os.getenv("MAX_RETRIES",   "3"))
# Seconds to wait between retry attempts (doubles on each retry).
RETRY_BACKOFF      = float(os.getenv("RETRY_BACKOFF", "2.0"))

# ── Context-window overflow ───────────────────────────────────────────────────
# When the model signals that the prompt is too long, the chunk is halved and
# retried.  This constant caps how many times we'll halve before giving up.
MAX_SPLIT_DEPTH    = int(os.getenv("MAX_SPLIT_DEPTH", "4"))