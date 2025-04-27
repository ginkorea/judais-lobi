# lobi/bootstrap.py

import subprocess
import venv
from pathlib import Path

def bootstrap_lobienv():
    """
    Ensures .lobienv exists, pip is upgraded, and ALL Lobi required packages are installed.
    """
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
        "rich"
    ]
    subprocess.run([str(pip_bin), "install"] + required_packages, check=True)

    print("✅ Lobi's magical environment (.lobienv) is now fully ready!")

if __name__ == "__main__":
    bootstrap_lobienv()
