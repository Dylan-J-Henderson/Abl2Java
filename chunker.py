"""
chunker.py
──────────
Splits large ABL source files into logical chunks that fit within the model's
context window, and extracts shared global definitions that must be visible to
every chunk during conversion.

Public API
──────────
    extract_shared_context(lines) → str
    split_into_chunks(lines)      → list[AblChunk]
    halve_chunk(chunk)            → tuple[AblChunk, AblChunk]

"""

import re
from dataclasses import dataclass

from config import TARGET_CHUNK_LINES, MIN_CHUNK_LINES

# ── ABL block boundary patterns ───────────────────────────────────────────────
BLOCK_START_RE = re.compile(
    r"^\s*(?:"
    r"PROCEDURE\s+\S+\s*[:{]?"
    r"|FUNCTION\s+\S+"
    r"|METHOD\s+(?:PUBLIC|PRIVATE|PROTECTED|STATIC|\s)+\s+\S+"
    r"|CLASS\s+\S+"
    r"|CONSTRUCTOR\s+"
    r")",
    re.IGNORECASE,
)

BLOCK_END_RE = re.compile(
    r"^\s*END\s*(?:PROCEDURE|FUNCTION|METHOD|CLASS|CONSTRUCTOR)?\.?\s*$",
    re.IGNORECASE,
)

# Opening line of a DEFINE that should be included in shared context.
SHARED_DEF_RE = re.compile(
    r"^\s*DEFINE\s+"
    r"(?:VARIABLE|TEMP-TABLE|PARAMETER|DATASET|STREAM|QUERY|BUFFER"
    r"|DATASET-HANDLE|DATA-SOURCE)\b",
    re.IGNORECASE,
)

# Lines that belong to a multi-line DEFINE block (FIELD, INDEX, continuation).
SHARED_DEF_CONTINUATION_RE = re.compile(
    r"^\s+(?:FIELD|INDEX|AREA|BEFORE-TABLE|NAMESPACE-PREFIX|NAMESPACE-URI"
    r"|XML-NODE-NAME|SERIALIZE-NAME|LIKE)\b",
    re.IGNORECASE,
)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class AblChunk:
    """One logical slice of an ABL source file."""

    index:      int        # 0-based position in the chunk list
    start_line: int        # 1-based, inclusive
    end_line:   int        # 1-based, inclusive
    lines:      list[str]

    @property
    def source(self) -> str:
        """Reconstructed source text for this chunk."""
        return "".join(self.lines)

    def __repr__(self) -> str:
        return (
            f"AblChunk(index={self.index}, "
            f"lines={self.start_line}–{self.end_line}, "
            f"len={len(self.lines)})"
        )


# ── Public helpers ────────────────────────────────────────────────────────────

def extract_shared_context(lines: list[str]) -> str:
    """
    Collect every file-level DEFINE statement — including multi-line blocks
    such as DEFINE TEMP-TABLE with FIELD / INDEX sub-lines — so they can be
    injected as context into each chunk prompt.

    A multi-line DEFINE block is considered to continue as long as subsequent
    lines are indented continuation keywords (FIELD, INDEX, etc.) or blank
    lines within the block.  The block ends at the first line that starts a
    new top-level statement.

    Args:
        lines: All source lines of the ABL file (with line endings).

    Returns:
        A single string containing the relevant DEFINE lines, or "" if none.
    """
    result: list[str] = []
    in_define_block = False

    for line in lines:
        if SHARED_DEF_RE.match(line):
            in_define_block = True
            result.append(line)
        elif in_define_block:
            # Continuation: indented sub-keywords or blank lines stay in block
            if SHARED_DEF_CONTINUATION_RE.match(line) or line.strip() == "":
                result.append(line)
            else:
                # First non-continuation line ends the block
                in_define_block = False

    return "".join(result)


def split_into_chunks(lines: list[str]) -> list[AblChunk]:
    """
    Split ABL source into logical chunks on PROCEDURE / FUNCTION / METHOD
    block boundaries.

    Strategy
    ────────
    1. Walk lines tracking whether we're inside a named block.
    2. Flush accumulated lines into a chunk each time a block closes or a new
       top-level block opens (capturing any inter-block preamble as its own
       chunk).
    3. Merge adjacent chunks that are smaller than TARGET_CHUNK_LINES so we
       minimise round-trips to Ollama without exceeding the context window.

    If no block boundaries are detected (e.g. a pure-procedural .p with no
    PROCEDURE keyword) the whole file is returned as a single chunk.

    Args:
        lines: All source lines of the ABL file (with line endings).

    Returns:
        An ordered list of AblChunk objects covering the entire file.
    """
    raw_chunks: list[AblChunk] = []
    current: list[str] = []
    current_start = 1
    in_block = False
    depth = 0

    def flush(end_line: int) -> None:
        nonlocal current, current_start
        if current:
            raw_chunks.append(AblChunk(
                index=len(raw_chunks),
                start_line=current_start,
                end_line=end_line,
                lines=current[:],
            ))
        current = []
        current_start = end_line + 1

    for lineno, line in enumerate(lines, 1):
        if not in_block and BLOCK_START_RE.match(line):
            if current:
                flush(lineno - 1)
                current_start = lineno
            in_block = True
            depth = 1
            current.append(line)

        elif in_block and BLOCK_START_RE.match(line):
            # Nested block (rare in ABL, but legal inside METHOD bodies)
            depth += 1
            current.append(line)

        elif in_block and BLOCK_END_RE.match(line):
            current.append(line)
            depth -= 1
            if depth <= 0:
                flush(lineno)
                in_block = False
                depth = 0

        else:
            current.append(line)

    if current:
        flush(len(lines))

    if not raw_chunks:
        return [AblChunk(0, 1, len(lines), lines)]

    return _merge_small_chunks(raw_chunks)


def halve_chunk(chunk: AblChunk) -> tuple["AblChunk", "AblChunk"]:
    """
    Split a single chunk in half by line count, returning two new AblChunk
    objects.  Used by the converter when a chunk triggers a context-window
    overflow error.

    If the chunk is at or below MIN_CHUNK_LINES, the same chunk is returned
    twice (caller must detect this and abort to avoid an infinite loop).

    Args:
        chunk: The chunk that was too large for the model's context window.

    Returns:
        A pair (first_half, second_half) of AblChunk objects.
    """
    if len(chunk.lines) <= MIN_CHUNK_LINES:
        # Cannot split further — return duplicate so caller can detect it
        return chunk, chunk

    mid = len(chunk.lines) // 2
    first_lines  = chunk.lines[:mid]
    second_lines = chunk.lines[mid:]

    first = AblChunk(
        index=chunk.index,
        start_line=chunk.start_line,
        end_line=chunk.start_line + mid - 1,
        lines=first_lines,
    )
    second = AblChunk(
        index=chunk.index + 1,          # caller will re-index the full list
        start_line=chunk.start_line + mid,
        end_line=chunk.end_line,
        lines=second_lines,
    )
    return first, second


# ── Private helpers ───────────────────────────────────────────────────────────

def _merge_small_chunks(chunks: list[AblChunk]) -> list[AblChunk]:
    """
    Combine consecutive small chunks until their combined size would exceed
    TARGET_CHUNK_LINES, reducing the number of LLM calls for small procedures.

    The merged chunk's end_line is taken from the last constituent chunk's
    end_line (not recomputed from bucket_start + length) so that line numbers
    remain accurate for non-contiguous source regions.

    Args:
        chunks: Raw chunk list produced by the block-boundary scanner.

    Returns:
        A new chunk list with adjacent small chunks merged.
    """
    merged: list[AblChunk] = []
    bucket_lines: list[str] = []
    bucket_start: int = chunks[0].start_line
    bucket_end:   int = chunks[0].end_line   # tracks the real end_line

    for chunk in chunks:
        if bucket_lines and len(bucket_lines) + len(chunk.lines) > TARGET_CHUNK_LINES:
            merged.append(AblChunk(
                index=len(merged),
                start_line=bucket_start,
                end_line=bucket_end,
                lines=bucket_lines[:],
            ))
            bucket_lines  = []
            bucket_start  = chunk.start_line

        bucket_lines.extend(chunk.lines)
        bucket_end = chunk.end_line          # always advance to real end_line

    if bucket_lines:
        merged.append(AblChunk(
            index=len(merged),
            start_line=bucket_start,
            end_line=bucket_end,
            lines=bucket_lines,
        ))

    return merged