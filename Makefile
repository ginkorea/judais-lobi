VENV_NAME = jlenv
PYTHON = python3.11

install:
	@echo "🔍 Checking system dependencies..."
	@if [ ! -f /usr/include/alsa/asoundlib.h ]; then \
		echo "⚠️ ALSA dev headers missing."; \
		if command -v dnf >/dev/null; then echo "👉 Try: sudo dnf install alsa-lib-devel gcc make $(PYTHON)-devel"; \
		elif command -v apt >/dev/null; then echo "👉 Try: sudo apt install libasound2-dev build-essential $(PYTHON)-dev"; \
		elif command -v pacman >/dev/null; then echo "👉 Try: sudo pacman -S alsa-lib base-devel $(PYTHON)"; \
		else echo "❗ Unknown distro. Install ALSA headers manually."; fi; \
	fi

	@echo "📦 Bootstrapping environment in .$(VENV_NAME)..."
	$(PYTHON) core/bootstrap.py $(VENV_NAME)

rebuild:
	rm -rf build dist *.egg-info .$(VENV_NAME)
	make install
