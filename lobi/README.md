# 🧝‍♂️ Lobi: The Helpful Linux Elf

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg)](https://www.python.org/)
[![Memory](https://img.shields.io/badge/Memory-Short--term%20%26%20Long--term-yellow.svg)](#-memory-files)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)](#)
[![PyPI version](https://badge.fury.io/py/lobi-cli.svg)](https://badge.fury.io/py/lobi-cli)

![Lobi the Helpful Linux Elf](https://github.com/ginkorea/lobi/raw/master/images/lobi.png)

---

Lobi lives in your keyboard and helps you solve riddles, write code, poke the websies, and whisper secrets of the circuits.  
Built to be mischievous, quirky, loyal — and now a fully memory-driven coding agent!

---

## ✨ Features

- **Friendly CLI Assistant:** chat, ask questions, brainstorm ideas
- **Code Writer:** write and run Python scripts (`--python`) or Bash commands (`--shell`)
- **Agentic Memory System:**
  - **Short-term memory:** persistent `.lobi_history.json`
  - **Long-term vector memory:** FAISS-powered `.lobi_longterm.json`
  - **Recall past successes or failures** using `--recall` and `--recall-type`
- **Self-Reflective Learning:**
  - Structured memory injection into new prompts
  - Improves upon past failed or successful code automatically
- **Error Handling & Repair:**
  - Automatically installs missing Python packages
  - Attempts code repairs if errors occur
- **Root Access (optional):**
  - Asks permission for sudo commands
- **Install Local Python Projects:** (`--install-project`)
- **Markdown or Raw Output Modes:** (`--md` or `--raw`)
- **Secret Mode:** (`--secret`) don't save history for sensitive queries

---

## ⚡ Quick Installation

```bash
pip install lobi-cli
```

✅ Requires Python 3.9+

---

## 🧰 Usage

```bash
lobi "your message here" [options]
```

### Common Options

| Option             | Description |
|--------------------|-------------|
| `--python`          | Ask Lobi to write and run a Python script |
| `--shell`           | Ask Lobi to write and run a Bash command |
| `--recall N`        | Recall last **N** coding memories (short-term) |
| `--recall-type`     | `1 = success`, `0 = failure`, `both = both` |
| `--long-term N`     | Recall **N** best matches from long-term memory |
| `--install-project` | Install a Python project into `.lobienv` |
| `--empty`           | Start a new conversation |
| `--purge`           | Purge long-term memory |
| `--search`          | Perform a web search for your query |
| `--deep`            | Perform a deep dive into top web result |
| `--secret`          | Do not save this conversation |
| `--model`           | Specify an OpenAI model (default: `gpt-4o-mini`) |
| `--md`              | Render output as Markdown |
| `--raw`             | Render output as plain text |

---

## 🔥 Example Commands

### Basic Chat
```bash
lobi "What is the best way to learn Linux?"
```

### Write and Run Python Code
```bash
lobi "Plot a histogram of random numbers" --python
```

### Write and Run a Bash Command
```bash
lobi "List all active IPs on the local network" --shell
```

### Recall Past Attempts to Improve
```bash
lobi "Scan the network better" --python --recall 3 --recall-type 0
```

### Recall Long-Term Memories
```bash
lobi "Find hidden devices on network" --python --recall 2 --long-term 3
```

### Install a Project
```bash
lobi --install-project
```

---

## 📦 Developer Setup

Clone and install manually:

```bash
git clone https://github.com/ginkorea/lobi.git
cd lobi
pip install .
```

Optional: use a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Lobi automatically creates a lightweight `.lobienv` virtual environment for running generated Python safely.

---

## 📜 Memory Files

| File                  | Purpose |
|------------------------|---------|
| `~/.lobi_history.json` | Persistent short-term conversation and coding memory |
| `~/.lobi_longterm.json`| Vectorized long-term memory for retrieval-augmented prompts |

---

## ⚠️ Security Notice

Lobi can generate and run Bash commands and Python code.  
**Always review the generated code** before running it, especially when using `--shell` or `--python`.

---

## 🧠 How Lobi Thinks

When asked to code, Lobi can:
- Recall up to N past exploits
- Focus on only failures (`--recall-type 0`) or successes (`--recall-type 1`)
- Search long-term memory
- Inject structured reflections into his next coding attempt
- Adapt automatically and retry if errors occur

If needed, Lobi will politely ask you for sudo powers to poke the network bits. 🧙‍♂️

---

## 💬 Example Memory Reflection Injected into Prompt

```text
✨ Memory 1:
Lobi attempted to scan the network, but no devices were found.

🐍 Python Code:
import scapy.all as scapy
...

📜 Execution Result:
PermissionError: [Errno 1] Operation not permitted
```

---

## ❤️ About

Created with mischief, magic, and memory to be your quirky Linux companion.  
Always learning. Always whispering. Always trying to help, precious.

---
