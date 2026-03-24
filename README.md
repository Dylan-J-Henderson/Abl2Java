# ABL2Java

> Refactor and migrate Progress OpenEdge ABL code to modern Java 17

ABL2Java is a command-line tool that automates the conversion of legacy Progress OpenEdge ABL (4GL) source files into idiomatic Java 17, using a locally running LLM via [Ollama](https://ollama.com).

---

## Features

- Converts `.p`, `.cls`, `.w`, and `.i` ABL source files to Java 17
- Preserves procedure and function names where possible
- Replaces Progress-specific constructs with modern Java equivalents
- Adds Javadoc comments to all public methods
- Flags untranslatable constructs with `// TODO` comments
- Batch processes entire directories of ABL files

---

## Prerequisites

Before using ABL2Java, ensure the following are installed:

- **Python 3.9+**
- **Ollama** — [Download here](https://ollama.com/download)

Once Ollama is installed, pull the required model:

```bash
ollama pull qwen2.5-coder:3b
```

Then make sure Ollama is running:

```bash
ollama serve
```

---

## Installation

```bash
# Clone the repository
git clone https://github.com/your-username/abl2java.git
cd abl2java
```

No additional dependencies required — the script uses only the Python standard library.

---

## Configuration

Configuration is hardcoded at the top of `abl2javaconverter.py`:

| Variable | Default | Description |
|---|---|---|
| `MODEL` | `qwen2.5-coder:3b` | Model to use for conversion |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama API endpoint |
| `TIMEOUT` | `300` | Request timeout in seconds |
| `SAMPLES_DIR` | `./samples` | Directory containing ABL source files |
| `OUTPUT_DIR` | `./java_output` | Directory for generated Java files |

To change any of these, edit the values at the top of the file directly.

---

## Usage

1. Place your ABL source files in the `samples/` directory
2. Run the converter:

```bash
python abl2javaconverter.py
```

3. Converted Java files will appear in `java_output/`

### Example output

```
  Progress 4GL → Java Converter
  Model  : qwen2.5-coder:3b
  Input  : ./samples
  Output : ./java_output

Found 3 file(s)

[1/3] customer.p ... done (12.4s) → customer.java
[2/3] order.cls  ... done (18.7s) → order.java
[3/3] utils.i    ... done (9.1s)  → utils.java

  Done — 3 succeeded, 0 failed
```

---

## ABL to Java Conversion Reference

| Progress ABL | Java equivalent |
|---|---|
| `DEFINE VARIABLE` | Typed local variables / fields |
| `FOR EACH` / `FIND` | JPA/JDBC (with TODO comment) |
| `DEFINE TEMP-TABLE` | Inner record class or DTO |
| `MESSAGE` / `DISPLAY` | `System.out` / logger calls |
| `RUN <program>` | Method call with TODO comment |
| `INPUT`/`OUTPUT` params | Method parameters / return types |

---

## Project Structure

```
abl2java/
├── README.md
├── .gitignore
├── abl2javaconverter.py
└── samples/              # place your .p, .cls, .w, .i files here
```

`java_output/` is created automatically when the converter runs.

---

## Contributing

Contributions are welcome! Please follow this workflow:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to your branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## Limitations

- Conversion quality depends on the model used — larger models generally produce better results
- Complex database interactions (`FOR EACH`, `FIND`) are flagged with `// TODO` comments and require manual review
- Very large ABL files may hit the model's context window; these will include range comments indicating sections that need manual refactoring

---
