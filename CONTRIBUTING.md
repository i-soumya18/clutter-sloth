# Contributing to Clutter Sloth

First of all, thank you for considering contributing to **Clutter Sloth**! 🦥

Clutter Sloth is built around an intentional philosophy: **be slow, careful, and reversible on purpose**. Unlike aggressive scripts that move or rename files instantly, Clutter Sloth prioritizes user safety, local privacy, and low resource overhead.

---

## Code of Conduct

This project adheres to the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## Development Setup

### 1. Prerequisites
- **Python 3.11** or newer.
- Git.
- (Optional for real inference) [Unsloth Desktop](https://unsloth.ai/) or any OpenAI-compatible local server (e.g., Ollama, vLLM, LM Studio) hosting an open-weight vision model (e.g., `Qwen2.5-VL`, `Qwen3.5`, `Gemma-3`). Note: Local GPU models are **not** needed to run or contribute to tests—the test suite runs with an integrated lightweight mock server.

### 2. Setting Up Local Environment

```bash
# Clone your fork
git clone https://github.com/<your-username>/clutter-sloth.git
cd clutter-sloth

# Create and activate virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install in editable mode with development dependencies
pip install -e .[dev]
```

### 3. Verify Installation
```bash
sloth --version
python tests/test_e2e.py
```

---

## Codebase Architecture

```
clutter-sloth/
├── sloth/
│   ├── __init__.py       # Package definition, version, Windows UTF-8 terminal I/O setup
│   ├── cli.py            # Command line entrypoints and interactive review UI
│   ├── config.py         # TOML configuration loader (~/.clutter-sloth/config.toml)
│   ├── db.py             # SQLite database layer (proposals, moves, corrections, trust)
│   ├── engine.py         # Core lifecycle: candidates, batching, trust ladder, apply, undo
│   ├── extract.py        # Text & thumbnail extraction (PIL, pypdf, pypdfium2)
│   ├── classify.py       # Prompt synthesis with few-shot dynamic corrections, LLM call
│   ├── llm.py            # Lightweight client for local OpenAI-compatible /v1 endpoints
│   ├── worker.py         # Background loop: watchdog observer, calm CPU gate, idle settle
│   └── digest.py         # Markdown summary of moves, corrections, and trust stats
└── tests/
    ├── mock_server.py    # Local HTTP server mocking OpenAI chat completions for testing
    └── test_e2e.py       # End-to-end test suite
```

---

## Core Tenets for Contributors

When writing code or submitting pull requests, ensure your changes adhere to these core design rules:

1. **Reversibility Is Non-Negotiable**: Every single move must be recorded in the `moves` table with its previous and new paths. The `undo` operation must restore the original file without ever overwriting newly created files.
2. **Safety First**:
   - Never touch subdirectories.
   - Never touch hidden files or unfinished downloads (`.crdownload`, `.part`, `.tmp`).
   - Name collisions must be handled cleanly via numeric increments (` (2)`).
3. **The Trust Ladder**:
   - New categories always start in preview-only mode.
   - Relocations for `never_auto` categories (e.g., identity cards, tax documents) must never be automated.
   - Any correction or undo must immediately reset the category's trust streak.
4. **Local-Only**:
   - No telemetry, analytics, or outbound web requests may be added. Communication is strictly restricted to local inference servers (`localhost`).

---

## Adding New Features

### Adding a New File Extractor
To support new formats (such as `.docx`, `.epub`, or audio tags), extend `sloth/extract.py`:
1. Register file extensions in the appropriate set (`TEXT_EXT`, `RULE_CATEGORY`, etc.).
2. Add a helper function to extract text or preview images cleanly.
3. Ensure all file handles are explicitly closed before returning (critical on Windows to avoid locking files).
4. Add corresponding assertions in `tests/test_e2e.py`.

---

## Testing

Always run the test suite before submitting a pull request:
```bash
python tests/test_e2e.py
```

All 12 checks should output `ok`.

---

## Pull Request Checklist

Before opening a pull request:
- [ ] Code follows existing style and formatting.
- [ ] New functionality includes corresponding tests in `tests/test_e2e.py`.
- [ ] All tests pass cleanly (`python tests/test_e2e.py`).
- [ ] Documentation (`README.md`, docstrings) is updated.
- [ ] Commit messages are clear and descriptive.
