# 🧝‍♂️ Lobi — The Helpful Linux Elf

**Lobi** is a minimalist yet powerful terminal-based AI assistant powered by OpenAI. It's designed for developers, sysadmins, and terminal lovers who want instant answers, markdown rendering, and persistent chat history — all from the comfort of the CLI.

![badge](https://img.shields.io/badge/terminal-ready-brightgreen?style=flat-square)
![license](https://img.shields.io/github/license/ginkorea/lobi?style=flat-square)

![Lobi the Helpful Linux Elf](https://github.com/ginkorea/lobi/raw/master/images/lobi.png)

---

## ✨ Features

- 🤖 Chat with OpenAI's GPT-4 or GPT-4 Turbo
- 📘 Streamed or Markdown-rendered answers (`--raw` / `--md`)
- 🔒 Secret mode (`--secret`) and clean resets (`--empty`)
- 💾 Persistent conversation history (`~/.hey_history.json`)
- 🎨 Beautiful color-coded terminal output with emoji flair
- 🌍 Easy to install globally, not tied to any virtualenv

---

## 🚀 Installation

### Install via GitHub:

```bash
pip install git+https://github.com/ginkorea/lobi.git
```

### Or clone and install manually:

```bash
git clone https://github.com/ginkorea/lobi.git
cd lobi
pip install .
```

---

## 🔐 Setup Your API Key

Either export it:

```bash
export OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

Or create a `.env` file in your home directory:

```bash
echo "OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxx" > ~/.lobi.env
```

Lobi will read it automatically on launch.

---

## 🧑‍💻 Usage

```bash
lobi "What are Linux runlevels?"
```

### Common Flags

| Option       | Description                                      |
|--------------|--------------------------------------------------|
| `--empty`    | Start a new conversation (no history/context)    |
| `--secret`   | Don’t save this exchange to history              |
| `--model`    | Use a specific OpenAI model (default: gpt-4-turbo) |
| `--md`       | Render markdown (non-streaming, pretty)          |
| `--raw`      | Stream raw output (default)                      |

---

## 💡 Examples

```bash
lobi "Give me a Python function that sorts a list." --md
lobi "What is systemd?" --empty
lobi "This is sensitive info" --secret
```

---

## 🧪 Developer Install

```bash
git clone https://github.com/ginkorea/lobi.git
cd lobi
pip install -e .
```

---

## 📜 License

[GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html)  
© 2025 [Josh Gompert (ginkorea)](https://github.com/ginkorea)

---

> 🧝‍♂️ Lobi lives in your terminal — ready to help, learn, and serve.