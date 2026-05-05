# ABL2Java

**Automated Progress OpenEdge ABL (4GL) → Java 17 migration tool.**

ABL2Java converts legacy Progress ABL source files into idiomatic Java 17 using a locally running LLM via [Ollama](https://ollama.com). It handles arbitrarily large codebases by splitting files into logical chunks, converting each independently, and merging the results into a single compilable class.

---

## Features

- Converts `.p`, `.cls`, `.w`, `.i`, and `.t` ABL source files to Java 17
- **Automatic large-file handling** — files exceeding the line threshold are split on `PROCEDURE` / `FUNCTION` / `METHOD` boundaries, converted chunk-by-chunk, then merged
- Shared global `DEFINE` statements are injected into every chunk prompt so the model always has full type context
- Preserves procedure and function names where possible
- Replaces Progress-specific constructs with modern Java equivalents
- Adds Javadoc comments to all public methods
- Flags untranslatable constructs with `// TODO` comments
- Batch-processes entire directories of ABL files
- Zero external Python dependencies — uses the standard library only

---

## Project Structure

```
abl2java/
├── main.py           # CLI entry point — file discovery, progress output
├── config.py         # All tuneable constants (model, paths, thresholds)
├── prompts.py        # LLM system prompts for each conversion stage
├── ollama_client.py  # HTTP transport layer for Ollama API calls
├── chunker.py        # ABL source parser — block detection & chunk splitting
└── converter.py      # Conversion strategies (small-file and chunked pipeline)
```

Each file has a single responsibility. Swapping the LLM backend, tuning prompts, or adjusting chunking behaviour each require editing exactly one file.

---

## Prerequisites

- **Python 3.11+**
- **[Ollama](https://ollama.com)** running locally

Pull the required model and start Ollama:

```bash
ollama pull qwen2.5-coder:3b
ollama serve
```

> Larger models (e.g. `qwen2.5-coder:7b`, `codellama:13b`) produce better output at the cost of speed. Change the model in `config.py`.

---

## Installation

```bash
git clone https://github.com/your-username/abl2java.git
cd abl2java
```

No `pip install` required — the project uses only the Python standard library.

---

## Usage

1. Place your ABL source files in the `samples/` directory.
2. Run the converter:

```bash
python main.py
```

3. Converted Java files appear in `java_output/`.

### Example output

```
  Progress 4GL → Java Converter
  Model          : qwen2.5-coder:3b
  Input          : ./samples
  Output         : ./java_output
  Chunk threshold: 300 lines
  Target chunk   : 150 lines

Found 3 file(s)

[1/3] customer.p ... done (14.2s, 3.1 KB) → customer.java
[2/3] order.cls ...
    ↳ 820 lines → 6 chunk(s)
      chunk 1/6 (lines 1–142) ... 11.3s
      chunk 2/6 (lines 143–290) ... 13.7s
      chunk 3/6 (lines 291–435) ... 12.1s
      chunk 4/6 (lines 436–580) ... 14.8s
      chunk 5/6 (lines 581–715) ... 11.9s
      chunk 6/6 (lines 716–820) ... 9.4s
      merging 6 snippet(s) ... 18.2s
 done (101.4s, 18.6 KB) → order.java
[3/3] utils.i ... done (9.1s, 1.4 KB) → utils.java

  Done — 3 succeeded, 0 failed
```

---

## Configuration

All settings live in `config.py`:

| Variable            | Default                              | Description                                              |
|---------------------|--------------------------------------|----------------------------------------------------------|
| `MODEL`             | `qwen2.5-coder:3b`                   | Ollama model to use                                      |
| `OLLAMA_URL`        | `http://localhost:11434/api/generate`| Ollama API endpoint                                      |
| `TIMEOUT`           | `300`                                | Per-request timeout in seconds                           |
| `SAMPLES_DIR`       | `./samples`                          | Directory containing ABL source files                    |
| `OUTPUT_DIR`        | `./java_output`                      | Directory for generated Java files                       |
| `EXTENSIONS`        | `{.p, .cls, .w, .i, .t}`            | File extensions treated as ABL source                    |
| `CHUNK_THRESHOLD`   | `300`                                | Files longer than this (lines) are split before conversion |
| `TARGET_CHUNK_LINES`| `150`                                | Target size when merging small adjacent blocks into chunks |

---

## ABL → Java Conversion Reference

| Progress ABL construct | Java equivalent |
|------------------------|-----------------|
| `DEFINE VARIABLE`      | Typed local variable or instance field |
| `FOR EACH / FIND`      | JPA / JDBC query with `// TODO` comment |
| `DEFINE TEMP-TABLE`    | Inner `record` class or DTO |
| `MESSAGE / DISPLAY`    | `System.out.println` / logger call |
| `RUN <program>`        | Method call with `// TODO` comment |
| `INPUT / OUTPUT` params | Method parameters / return types |

---

## Large Codebase Pipeline

For files exceeding `CHUNK_THRESHOLD` lines, ABL2Java uses a three-stage pipeline:

```
ABL file
   │
   ├─ 1. extract_shared_context()   ← global DEFINE statements saved aside
   │
   ├─ 2. split_into_chunks()        ← split on PROCEDURE / FUNCTION / METHOD boundaries
   │        │                          merge tiny adjacent blocks up to TARGET_CHUNK_LINES
   │        ▼
   │   [chunk 1] [chunk 2] ... [chunk N]
   │        │
   ├─ 3. convert each chunk         ← shared context injected into every prompt
   │        │                          model outputs method bodies only (no class wrapper)
   │        ▼
   │   [snippet 1] [snippet 2] ... [snippet N]
   │
   └─ 4. merge via LLM              ← single merge prompt assembles one compilable class,
                                       deduplicates imports and helper methods
```

---

## Limitations

- Conversion quality depends on the model. Larger models produce better results.
- Complex database interactions (`FOR EACH`, `FIND`) are flagged with `// TODO` and require manual review.
- The merge step can itself approach the context window limit for very large files (20+ chunks). In such cases consider raising `CHUNK_THRESHOLD` to reduce the number of chunks, or post-process the snippets manually.
- Generated code compiles structurally but will require integration work for any real database or UI layer.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to your branch: `git push origin feature/your-feature`
5. Open a Pull Request

---