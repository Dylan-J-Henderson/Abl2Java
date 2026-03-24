#!/usr/bin/env python3
"""
Progress 4GL → Java Converter
Converts all Progress ABL files in ./samples to Java using Ollama qwen2.5-coder:3b.
"""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
MODEL      = "qwen2.5-coder:3b"
OLLAMA_URL = "http://localhost:11434/api/generate"
SAMPLES_DIR = Path(__file__).parent / "samples"
OUTPUT_DIR  = Path(__file__).parent / "java_output"
EXTENSIONS  = {".p", ".cls", ".w", ".i", ".t"}
TIMEOUT     = 300

# ── Prompts ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert software engineer specialising in migrating legacy Progress OpenEdge ABL (4GL) code to modern Java 17.

Your task:
1. Convert the supplied Progress 4GL source file to idiomatic, production-quality Java 17.
2. Follow modern Java best practices: proper class structure, access modifiers, generics, streams, Optional, etc.
3. Replace Progress-specific constructs:
   - DEFINE VARIABLE  → typed local variables / fields
   - FOR EACH / FIND  → JPA/JDBC or comment noting DB access pattern
   - DEFINE TEMP-TABLE → inner record class or DTO
   - MESSAGE / DISPLAY → System.out / logger calls
   - RUN <program>    → method call with TODO comment
   - INPUT/OUTPUT PARAMS → method parameters / return types
4. All method names, procedure names, and function names should remain the same in cases where Progress 4gl code has only been transpiled and not refactored.
5. In cases where Progress 4gl code is too large to refactor, add a comment to specify the lines in a range from the source Progress 4gl code that need to be refactored.
6. Add a short Javadoc comment on every public method.
7. If a construct cannot be directly translated, leave a // TODO: [reason] comment.
8. Output ONLY the raw Java source code — no markdown fences, no explanation text."""


def call_ollama(system: str, user: str) -> str:
    payload = {
        "model":  MODEL,
        "prompt": f"<system>\n{system}\n</system>\n\n{user}",
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode()).get("response", "")


def strip_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def convert_file(source_path: Path):
    """Returns (java_code, error). One of them will be None."""
    source_code = source_path.read_text(encoding="utf-8", errors="replace")
    user_prompt = f"Convert this Progress 4GL file to Java 17.\nFile: {source_path.name}\n\n{source_code}"
    try:
        java_code = call_ollama(SYSTEM_PROMPT, user_prompt)
        return strip_fences(java_code), None
    except urllib.error.URLError as e:
        return "", f"Cannot reach Ollama: {e.reason}"
    except Exception as e:
        return "", f"Error: {e}"


def main():
    print(f"\n  Progress 4GL → Java Converter")
    print(f"  Model  : {MODEL}")
    print(f"  Input  : {SAMPLES_DIR}")
    print(f"  Output : {OUTPUT_DIR}\n")

    if not SAMPLES_DIR.exists():
        print(f"ERROR: samples directory not found: {SAMPLES_DIR}")
        return

    files = sorted(f for f in SAMPLES_DIR.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONS)

    if not files:
        print("No Progress 4GL files found in ./samples")
        return

    print(f"Found {len(files)} file(s)\n")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    success, failed = 0, 0

    for i, source_path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {source_path.name} ...", end="", flush=True)
        t0 = time.time()

        java_code, error = convert_file(source_path)

        if error:
            print(f" FAILED\n    {error}")
            failed += 1
        else:
            out_path = OUTPUT_DIR / (source_path.stem + ".java")
            out_path.write_text(java_code, encoding="utf-8")
            print(f" done ({time.time() - t0:.1f}s) → {out_path.name}")
            success += 1

    print(f"\n  Done — {success} succeeded, {failed} failed\n")


if __name__ == "__main__":
    main()
