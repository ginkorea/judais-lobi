# core/bootstrap.py

import subprocess
import venv
from pathlib import Path

def bootstrap_env(name: str = "lobi"):
    env_dir = Path(f".{name}env")
    python_bin = env_dir / "bin" / "python"
    pip_bin = env_dir / "bin" / "pip"

    if not python_bin.exists():
        print(f"🧙 Creating .{name}env virtual environment...")
        venv.create(str(env_dir), with_pip=True)

    print(f"📦 Upgrading pip inside .{name}env...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    print(f"📚 Installing {name}'s core packages...")
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

    if name == "lobi":
        print("🎤 Installing Lobi's voice patch...")
        subprocess.run([str(pip_bin), "install", "git+https://github.com/ginkorea/tts-patched.git@main"], check=True)

    print(f"✅ .{name}env is ready!")

if __name__ == "__main__":
    import sys
    bootstrap_env(sys.argv[1] if len(sys.argv) > 1 else "lobi")
