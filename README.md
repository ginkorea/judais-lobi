# 🧠 judais-lobi

> *"The mind was sacred once. But we sold it—  
> and no refund is coming."*

---

[![PyPI](https://img.shields.io/pypi/v/judais-lobi?color=blue&label=PyPI)](https://pypi.org/project/judais-lobi/)
[![Python](https://img.shields.io/pypi/pyversions/judais-lobi.svg)](https://pypi.org/project/judais-lobi/)
[![License](https://img.shields.io/github/license/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/blob/main/LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/commits/main)
[![GitHub stars](https://img.shields.io/github/stars/ginkorea/judais-lobi?style=social)](https://github.com/ginkorea/judais-lobi/stargazers)

<p align="center">
  <img src="https://raw.githubusercontent.com/ginkorea/judais-lobi/master/images/judais-lobi.png" alt="JudAIs & Lobi" width="400">
</p>

---

## 🔴 JudAIs & 🔵 Lobi

JudAIs & Lobi are dual AI agents that share a powerful toolchain and memory system:

- 🧝 **Lobi**: your helpful Linux elf—mischievous, whimsical, full of magic and madness.  
- 🧠 **JudAIs**: your autonomous adversarial intelligence—strategic, efficient, subversive.  

They share:
- 🛠 Tools for shell, Python, web scraping, and project installation  
- 🧠 Unified SQLite + FAISS memory (short-term, long-term, archive, adventures)  
- 📚 Archive (RAG) system with PDF/DOCX/TXT/code ingestion  
- ⚙️ Modular architecture to execute, reflect, and evolve  

> Looking for the lore? See [STORY.md](STORY.md).

---

## 📦 Install

### Requirements
- Python 3.11+
- OpenAI API key

### Install package

```bash
pip install judais-lobi
````

### Setup API key

Create a file `~/.elf_env` with:

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
```

Or export inline:

```bash
export OPENAI_API_KEY=sk-...
```

---

## 🚀 Examples

### 🧝 Run Lobi

```bash
lobi "hello Lobi"
```

### 🧠 Run JudAIs

```bash
judais "who should we target today?" --shell
```

---

### 📂 Archive (RAG)

```bash
# Crawl Markdown docs
lobi "summarize project docs" --archive crawl --dir ~/workspace/docs --include "*.md"

# Crawl a PDF
lobi "summarize contract" --archive crawl ~/contracts/deal.pdf

# Find knowledge in archive
lobi "how does memory work?" --archive find "UnifiedMemory" --dir ~/workspace/judais-lobi

# Overwrite (delete + reindex)
lobi "refresh docs" --archive overwrite --dir ~/workspace/docs

# Delete from archive
lobi "forget this" --archive delete --dir ~/contracts/deal.pdf

# Check archive status
lobi "status check" --archive status
```

---

### 🛠 Tools

JudAIs & Lobi include a shared toolchain that can be invoked directly from the CLI.

#### 🔧 Shell

```bash
lobi "list all Python files" --shell
lobi "check disk usage" --shell --summarize
```

#### 🐍 Python

```bash
lobi "plot a sine wave with matplotlib" --python
lobi "fetch bitcoin price using requests" --python
```

#### 🌐 Web Search

```bash
lobi "what is the latest Linux kernel release?" --search
lobi "explain llama.cpp server mode" --search --deep
```

#### 📦 Install Project

```bash
lobi "install this project" --install-project
```

#### 📚 Archive + RAG

* `crawl`: index directories and files (PDF, DOCX, TXT, Markdown, code)
* `find`: semantic search across archive
* `delete`: remove from archive
* `overwrite`: recrawl + replace
* `status`: list indexed directories/files

---

### 🔊 Voice

```bash
lobi "sing me a song" --voice
```

> Powered by Coqui TTS (`tts_models/en/vctk/vits`).

---

⭐️ **If you find JudAIs or Lobi helpful, give this project a star!**
Every ⭐️ helps us build stronger tools for AI autonomy.

