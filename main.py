#!/usr/bin/env python3
"""
main.py  ·  ABL2Java
────────────────────
Command-line entry point for the Progress 4GL → Java 17 converter.

Usage:
    python main.py [--force] [--recurse] [--verbose]

Flags:
    --force    Overwrite existing .java output files (default: skip them).
    --recurse  Scan sub-directories of SAMPLES_DIR, not just the top level.
    --verbose  Enable DEBUG-level logging to stdout.

All other configuration (model, paths, chunk size) lives in config.py.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from config import (
    MODEL,
    SAMPLES_DIR,
    OUTPUT_DIR,
    EXTENSIONS,
    CHUNK_THRESHOLD,
    TARGET_CHUNK_LINES,
    MAX_RETRIES,
    MAX_SPLIT_DEPTH,
)
from converter import convert_file


def main() -> None:
    args = _parse_args()
    _configure_logging(args.verbose)

    _print_banner()

    if not SAMPLES_DIR.exists():
        print(f"ERROR: samples directory not found: {SAMPLES_DIR}")
        sys.exit(1)

    files = _discover_files(SAMPLES_DIR, recurse=args.recurse)

    if not files:
        print("No Progress 4GL files found.")
        return

    print(f"Found {len(files)} file(s)\n")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    success, failed, skipped = 0, 0, 0

    for i, source_path in enumerate(files, 1):
        out_path = OUTPUT_DIR / (source_path.stem + ".java")

        if out_path.exists() and not args.force:
            print(f"[{i}/{len(files)}] {source_path.name} — skipped (already exists)")
            skipped += 1
            continue

        print(f"[{i}/{len(files)}] {source_path.name} …", end="", flush=True)
        t0 = time.time()

        java_code, error = convert_file(source_path)

        if error:
            print(f" FAILED\n    {error}")
            failed += 1
        else:
            out_path.write_text(java_code, encoding="utf-8")
            elapsed = time.time() - t0
            size_kb = len(java_code.encode()) / 1024
            print(
                f" done ({elapsed:.1f}s, {size_kb:.1f} KB)"
                f" → {out_path.relative_to(OUTPUT_DIR.parent)}"
            )
            success += 1

    parts = [f"{success} succeeded", f"{failed} failed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    print(f"\n  Done — {', '.join(parts)}\n")
    if failed:
        sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Progress 4GL (ABL) source files to Java 17."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing .java output files instead of skipping them.",
    )
    parser.add_argument(
        "--recurse", action="store_true",
        help="Scan sub-directories of SAMPLES_DIR recursively.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args()


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _discover_files(directory: Path, *, recurse: bool) -> list[Path]:
    """Return all ABL source files in *directory*, sorted by name."""
    if recurse:
        candidates = directory.rglob("*")
    else:
        candidates = directory.iterdir()

    return sorted(
        f for f in candidates
        if f.is_file() and f.suffix.lower() in EXTENSIONS
    )


def _print_banner() -> None:
    print(f"\n  Progress 4GL → Java Converter")
    print(f"  Model            : {MODEL}")
    print(f"  Input            : {SAMPLES_DIR}")
    print(f"  Output           : {OUTPUT_DIR}")
    print(f"  Chunk threshold  : {CHUNK_THRESHOLD} lines")
    print(f"  Target chunk     : {TARGET_CHUNK_LINES} lines")
    print(f"  Max retries      : {MAX_RETRIES}")
    print(f"  Max split depth  : {MAX_SPLIT_DEPTH}\n")


if __name__ == "__main__":
    main()