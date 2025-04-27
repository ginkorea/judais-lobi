# lobi/bootstrap.py

import subprocess
import venv
from pathlib import Path

def bootstrap_lobienv():
    lobienv = Path(".lobienv")
    python_bin = lobienv / "bin" / "python"
    pip_bin = lobienv / "bin" / "pip"

    if not python_bin.exists():
        print("🧙 Creating .lobienv virtual environment...")
        venv.create(str(lobienv), with_pip=True)

    print("📦 Upgrading pip inside .lobienv...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    print("📚 Installing Lobi's core packages...")
    required_packages = [
        "openai>=1.0.0",
        "faiss-cpu",
        "numpy",
        "python-dotenv",
        "requests",
        "beautifulsoup4",
        "rich",
        "pyttsx3",
        "spacy[ja]==3.6.1"
    ]
    subprocess.run([str(pip_bin), "install"] + required_packages, check=True)

    print("🎤 Installing Patched TTS (Lobi voice)...")
    subprocess.run([str(pip_bin), "install", "git+https://github.com/ginkorea/tts-patched.git@main"], check=True)

    print("✅ Lobi's magical environment (.lobienv) is now fully ready with a voice!")

if __name__ == "__main__":
    bootstrap_lobienv()
