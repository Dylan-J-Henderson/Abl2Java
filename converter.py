"""
converter.py
────────────
Conversion strategies for ABL → Java translation.

Two strategies are provided:
  • convert_small_file  — single-shot prompt for files within the context budget.
  • convert_large_file  — chunked pipeline: split → convert each chunk → merge.

The public entry point is convert_file(), which picks the right strategy
automatically based on file line-count vs CHUNK_THRESHOLD.

"""

import json
import logging
import re
import time
import urllib.error
from pathlib import Path
from typing import Optional

from config import (
    CHUNK_THRESHOLD,
    MAX_SPLIT_DEPTH,
    OUTPUT_DIR,
)
from chunker import AblChunk, extract_shared_context, split_into_chunks, halve_chunk
from ollama_client import call_ollama, strip_fences, ContextWindowError
from prompts import SYSTEM_PROMPT, CHUNK_SYSTEM_PROMPT, MERGE_SYSTEM_PROMPT

log = logging.getLogger(__name__)

# Matches the opening line of a method / constructor / static block in Java
# output — used by both the coverage checker and the truncation heuristic.
_METHOD_OPEN_RE = re.compile(
    r'^\s*(?:(?:public|protected|private|static|final|abstract|synchronized)'
    r'[\s\w<>\[\],?]+)\s+\w+\s*\(',
    re.MULTILINE,
)

# Placeholder emitted by CHUNK_SYSTEM_PROMPT for preamble-only chunks.
_PREAMBLE_PLACEHOLDER = "/* no translatable procedures in this chunk */"


# ── Small-file strategy ───────────────────────────────────────────────────────

def convert_small_file(
    source_path: Path,
    source_code: str,
) -> tuple[str, Optional[str]]:
    """
    Single-shot conversion: send the entire file in one prompt.
    Suitable for files at or below CHUNK_THRESHOLD lines.

    Falls back automatically to the chunked pipeline on context overflow.

    Args:
        source_path: Path to the original ABL file (used for the filename hint).
        source_code: Full text of the ABL file.

    Returns:
        (java_code, None) on success, or ("", error_message) on failure.
    """
    user_prompt = (
        f"Convert this Progress 4GL file to Java 17.\n"
        f"File: {source_path.name}\n\n{source_code}"
    )
    try:
        java_code = call_ollama(SYSTEM_PROMPT, user_prompt)
        return strip_fences(java_code), None

    except ContextWindowError:
        log.warning(
            "%s — single-shot prompt exceeded context window; "
            "falling back to chunked pipeline.",
            source_path.name,
        )
        lines = source_code.splitlines(keepends=True)
        return convert_large_file(source_path, lines)

    except urllib.error.URLError as exc:
        return "", f"Cannot reach Ollama: {exc.reason}"
    except Exception as exc:
        return "", f"Error: {exc}"


# ── Large-file (chunked) strategy ─────────────────────────────────────────────

def convert_large_file(
    source_path: Path,
    lines: list[str],
) -> tuple[str, Optional[str]]:
    """
    Chunked conversion pipeline for files that exceed CHUNK_THRESHOLD lines.

    Steps
    ─────
    1. Extract shared global DEFINE statements (injected into every chunk
       prompt so the model always has the full data-model context).
    2. Split the file into logical chunks on block boundaries.
    3. Convert each chunk independently via Ollama.  If a chunk triggers a
       context-window overflow, halve it and retry (up to MAX_SPLIT_DEPTH
       times).
    4. Cache partial results to disk so a re-run can skip completed chunks.
    5. Merge all converted snippets into a single Java class via a second
       LLM call, then verify that no methods were silently dropped.

    Args:
        source_path: Path to the original ABL file.
        lines:       Source lines (with line endings) of the ABL file.

    Returns:
        (java_code, None) on success, or ("", error_message) on failure.
    """
    shared_ctx = extract_shared_context(lines)
    chunks     = split_into_chunks(lines)
    total      = len(chunks)

    log.info("%s — %d lines → %d chunk(s)", source_path.name, len(lines), total)
    print(f"\n    ↳ {len(lines)} lines → {total} chunk(s)", flush=True)

    cache_path = _cache_path_for(source_path)
    cache      = _load_cache(cache_path)

    converted_snippets: list[str] = []

    for chunk in chunks:
        cache_key = f"{chunk.start_line}-{chunk.end_line}"

        if cache_key in cache:
            log.debug("chunk %s — loaded from cache", cache_key)
            converted_snippets.append(cache[cache_key])
            continue

        snippet, error = _convert_chunk_with_split(
            source_path, lines, shared_ctx, chunk, depth=0
        )
        if error:
            return "", error

        header = (
            f"// ── Converted from lines "
            f"{chunk.start_line}–{chunk.end_line} ──\n"
        )
        full_snippet = header + snippet
        converted_snippets.append(full_snippet)
        cache[cache_key] = full_snippet
        _save_cache(cache_path, cache)

    result, error = _merge_snippets(
        source_path, shared_ctx, converted_snippets, total
    )
    if not error:
        cache_path.unlink(missing_ok=True)
    return result, error


# ── Chunk conversion with recursive halving ───────────────────────────────────

def _convert_chunk_with_split(
    source_path: Path,
    all_lines: list[str],
    shared_ctx: str,
    chunk: AblChunk,
    depth: int,
) -> tuple[str, Optional[str]]:
    """
    Convert one chunk.  On ContextWindowError, halve the chunk and convert
    each half separately, recursing up to MAX_SPLIT_DEPTH times.

    Args:
        source_path: Original file path (for prompt context).
        all_lines:   All source lines (for total line-count display).
        shared_ctx:  Global DEFINE block to inject into every prompt.
        chunk:       The chunk to convert.
        depth:       Current recursion depth (0 = first attempt).

    Returns:
        (java_snippet, None) on success, or ("", error_message) on failure.
    """
    label = (
        f"chunk lines {chunk.start_line}–{chunk.end_line}"
        + (f" [split depth {depth}]" if depth else "")
    )
    print(f"      {label} …", end="", flush=True)
    t0 = time.time()

    user_prompt = (
        f"File: {source_path.name}  |  "
        f"Source lines {chunk.start_line}–{chunk.end_line} of {len(all_lines)}\n\n"
        f"=== SHARED GLOBAL DEFINITIONS (for context only — do not redeclare) ===\n"
        f"{shared_ctx or '(none)'}\n\n"
        f"=== CHUNK TO CONVERT ===\n"
        f"{chunk.source}"
    )

    try:
        snippet = call_ollama(CHUNK_SYSTEM_PROMPT, user_prompt)
        snippet = strip_fences(snippet)   # also calls strip_explanation internally
        print(f" {time.time() - t0:.1f}s", flush=True)
        return snippet, None

    except ContextWindowError:
        print(f" context overflow!", flush=True)

        if depth >= MAX_SPLIT_DEPTH:
            return "", (
                f"Chunk {chunk.start_line}–{chunk.end_line} is still too large "
                f"after {MAX_SPLIT_DEPTH} splits ({len(chunk.lines)} lines). "
                f"Reduce TARGET_CHUNK_LINES or increase the model's context window."
            )

        first, second = halve_chunk(chunk)
        if first is second:
            return "", (
                f"Chunk {chunk.start_line}–{chunk.end_line} cannot be split further "
                f"({len(chunk.lines)} lines ≤ MIN_CHUNK_LINES). "
                f"The model's context window may be too small for this file."
            )

        log.info(
            "Context overflow — splitting chunk %d–%d into halves",
            chunk.start_line, chunk.end_line,
        )

        first_snippet, err = _convert_chunk_with_split(
            source_path, all_lines, shared_ctx, first, depth + 1
        )
        if err:
            return "", err

        second_snippet, err = _convert_chunk_with_split(
            source_path, all_lines, shared_ctx, second, depth + 1
        )
        if err:
            return "", err

        return first_snippet + "\n\n" + second_snippet, None

    except urllib.error.URLError as exc:
        return "", f"Cannot reach Ollama: {exc.reason}"
    except Exception as exc:
        return "", f"Chunk {chunk.start_line}–{chunk.end_line} error: {exc}"


# ── Merge ─────────────────────────────────────────────────────────────────────

def _merge_snippets(
    source_path: Path,
    shared_ctx: str,
    snippets: list[str],
    total: int,
) -> tuple[str, Optional[str]]:
    """
    Ask the LLM to combine independently-converted snippets into one
    complete, compilable Java class.

    After merging:
      1. _warn_if_truncated() logs a soft warning based on keyword frequency.
      2. _assert_method_coverage() does a harder check: if the merged output
         is missing a large proportion of the method signatures that appeared
         in the input snippets, the conversion is aborted with a clear error
         so the caller can inspect the .chunk_cache.json for the raw snippets
         and diagnose the issue.

    Args:
        source_path: Used to derive a class-name hint.
        shared_ctx:  Global DEFINE lines to become instance fields.
        snippets:    Converted Java method bodies, one per chunk.
        total:       Number of chunks (for console output only).

    Returns:
        (merged_java_code, None) on success, or ("", error_message) on failure.
    """
    print(f"      merging {total} snippet(s) …", end="", flush=True)
    t0 = time.time()

    class_name_hint = source_path.stem

    # Filter out placeholder-only snippets before sending to the merge model
    # so we don't waste tokens and confuse it.
    substantive = [
        s for s in snippets
        if _PREAMBLE_PLACEHOLDER not in s
    ]

    if not substantive:
        # Every chunk was preamble only — nothing to merge
        log.warning("%s — all chunks were preamble-only; nothing to merge.", source_path.name)
        return (
            f"// {source_path.name}: no translatable procedures found.\n",
            None,
        )

    snippets_joined = "\n\n".join(substantive)

    merge_prompt = (
        f"Class name hint: {class_name_hint}\n\n"
        f"=== SHARED FIELDS (declare these as private instance fields) ===\n"
        f"{shared_ctx or '(none)'}\n\n"
        f"=== CONVERTED METHOD SNIPPETS ===\n"
        f"{snippets_joined}"
    )

    try:
        merged = call_ollama(MERGE_SYSTEM_PROMPT, merge_prompt)
        merged = strip_fences(merged)   # strip_fences also calls strip_explanation
        elapsed = time.time() - t0
        print(f" {elapsed:.1f}s", flush=True)

        _warn_if_truncated(merged, substantive)

        coverage_error = _assert_method_coverage(merged, substantive, source_path)
        if coverage_error:
            return "", coverage_error

        return merged, None

    except ContextWindowError:
        return "", (
            "Merge prompt exceeded the model's context window. "
            "The file may have too many chunks to merge in one pass. "
            "Consider reducing TARGET_CHUNK_LINES to produce fewer, larger chunks, "
            "or upgrading to a model with a larger context window."
        )
    except urllib.error.URLError as exc:
        return "", f"Cannot reach Ollama (merge): {exc.reason}"
    except Exception as exc:
        return "", f"Merge error: {exc}"


def _assert_method_coverage(
    merged: str,
    snippets: list[str],
    source_path: Path,
    threshold: float = 0.70,
) -> Optional[str]:
    """
    Hard coverage check: count method-signature opening lines in the input
    snippets and in the merged output.  If the merged class contains fewer
    than *threshold* × input count, return an error string so the caller
    can surface it clearly.

    Uses the module-level _METHOD_OPEN_RE rather than a simple keyword count
    so that field declarations and import lines don't inflate the tally.

    Args:
        merged:      The merged Java class text.
        snippets:    The per-chunk converted snippets (preamble already removed).
        source_path: Used only for the error message.
        threshold:   Fraction of input methods that must appear in output
                     (default 0.70 — allows for legitimate de-duplication).

    Returns:
        None if coverage is acceptable, or an error string if not.
    """
    input_count  = sum(len(_METHOD_OPEN_RE.findall(s)) for s in snippets)
    output_count = len(_METHOD_OPEN_RE.findall(merged))

    if input_count == 0:
        return None  # nothing to check

    if output_count < input_count * threshold:
        cache_path = _cache_path_for(source_path)
        log.error(
            "Method coverage check FAILED for %s: %d method signatures in "
            "input snippets, only %d in merged output (threshold %.0f%%). "
            "Raw snippets are in %s",
            source_path.name, input_count, output_count,
            threshold * 100, cache_path,
        )
        return (
            f"Merge coverage check failed for {source_path.name}: "
            f"{input_count} method signature(s) detected across input snippets "
            f"but only {output_count} found in merged output "
            f"(threshold {threshold:.0%}). "
            f"Raw per-chunk snippets have been preserved in {cache_path}. "
            f"Options:\n"
            f"  • Re-run with --force to retry the merge step alone "
            f"(chunk cache will be reused).\n"
            f"  • Reduce TARGET_CHUNK_LINES to produce fewer, larger chunks "
            f"so the merge prompt is shorter.\n"
            f"  • Switch to a model with a larger context window."
        )

    return None


def _warn_if_truncated(merged: str, snippets: list[str]) -> None:
    """
    Soft heuristic: compare keyword frequency in input vs output.
    Logs a warning and prints to stdout but does not abort conversion.
    """
    sig_re = re.compile(
        r"\b(?:public|private|protected|void|static)\b", re.IGNORECASE
    )
    input_sigs  = sum(len(sig_re.findall(s)) for s in snippets)
    output_sigs = len(sig_re.findall(merged))

    if input_sigs > 0 and output_sigs < input_sigs * 0.6:
        log.warning(
            "Merged output may be truncated: expected ~%d keyword occurrences, "
            "found %d. Review the output carefully.",
            input_sigs, output_sigs,
        )
        print(
            f"\n      ⚠  Merge may be truncated "
            f"(~{output_sigs} vs ~{input_sigs} expected keyword hits). "
            f"Review output carefully.",
            flush=True,
        )


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path_for(source_path: Path) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / f".{source_path.stem}.chunk_cache.json"


def _load_cache(cache_path: Path) -> dict[str, str]:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache_path: Path, cache: dict[str, str]) -> None:
    try:
        cache_path.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Could not write chunk cache %s: %s", cache_path, exc)


# ── Public entry point ────────────────────────────────────────────────────────

def convert_file(source_path: Path) -> tuple[str, Optional[str]]:
    """
    Convert a single ABL source file to Java 17.

    Automatically selects the single-shot strategy for small files and the
    chunked pipeline for large ones.

    Args:
        source_path: Path to the ABL file to convert.

    Returns:
        (java_code, None) on success, or ("", error_message) on failure.
    """
    try:
        source_code = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "", f"Cannot read file: {exc}"

    lines = source_code.splitlines(keepends=True)

    if len(lines) <= CHUNK_THRESHOLD:
        return convert_small_file(source_path, source_code)
    else:
        return convert_large_file(source_path, lines)