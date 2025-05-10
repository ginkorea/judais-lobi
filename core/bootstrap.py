# core/bootstrap.py

import subprocess
import venv
from pathlib import Path
import shutil
import platform

def check_system_requirements():
    print("🔍 Checking system dependencies...")
    pkg_mgr = detect_package_manager()
    missing = []

    if not shutil.which("gcc"):
        missing.append("gcc")
    if not Path("/usr/include/alsa/asoundlib.h").exists():
        missing.append("alsa-lib-devel")

    if missing:
        print(f"⚠️ Missing system dependencies: {', '.join(missing)}")
        if pkg_mgr == "dnf":
            print("👉 Install with: sudo dnf install alsa-lib-devel gcc make python3-devel")
        elif pkg_mgr == "apt":
            print("👉 Install with: sudo apt install libasound2-dev build-essential python3-dev")
        elif pkg_mgr == "pacman":
            print("👉 Install with: sudo pacman -S alsa-lib base-devel python")
        else:
            print("❗ Unknown system. Please install the appropriate development tools and ALSA headers manually.")

def detect_package_manager():
    if shutil.which("dnf"):
        return "dnf"
    elif shutil.which("apt"):
        return "apt"
    elif shutil.which("pacman"):
        return "pacman"
    else:
        return "unknown"

def bootstrap_env(name: str = "jlenv"):
    check_system_requirements()

    env_dir = Path(f".{name}").resolve()
    python_bin = env_dir / "bin" / "python"
    pip_bin = env_dir / "bin" / "pip"

    if not python_bin.exists():
        print(f"🧙 Creating .{name} virtual environment...")
        venv.create(str(env_dir), with_pip=True)

    print(f"📦 Upgrading pip inside .{name}...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    print(f"📚 Installing from requirements.txt...")
    subprocess.run([str(pip_bin), "install", "-r", "requirements.txt"], check=True)

    print(f"🔁 Installing project in editable mode via {python_bin}...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "-e", "."], check=True)

    print(f"✅ .{name} is ready!")


if __name__ == "__main__":
    import sys
    bootstrap_env(sys.argv[1] if len(sys.argv) > 1 else "jlenv")

