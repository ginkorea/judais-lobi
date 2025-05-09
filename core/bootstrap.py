# core/bootstrap.py

import subprocess
import venv
from pathlib import Path

def bootstrap_env(name: str = "elf"):
    env_dir = Path(f".{name}env")
    python_bin = env_dir / "bin" / "python"
    pip_bin = env_dir / "bin" / "pip"

    if not python_bin.exists():
        print(f"🧙 Creating .{name}env virtual environment...")
        venv.create(str(env_dir), with_pip=True)

    print(f"📦 Upgrading pip inside .{name}env...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    print(f"📚 Installing from requirements.txt...")
    subprocess.run([str(pip_bin), "install", "-r", "requirements.txt"], check=True)

    print(f"🔁 Installing project in editable mode...")
    subprocess.run([str(pip_bin), "install", "-e", "."], check=True)

    print(f"✅ .{name}env is ready!")

if __name__ == "__main__":
    import sys
    bootstrap_env(sys.argv[1] if len(sys.argv) > 1 else "elf")
