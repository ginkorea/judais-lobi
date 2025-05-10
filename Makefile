# Makefile for judais-lobi CLI project

VENV_NAME = jlenv
PYTHON = python3.11
VERSION = 0.5.4
TAG = v$(VERSION)
BRANCH = $(shell git symbolic-ref --short HEAD)


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

tag:
	@echo "🏷️ Tagging release $(TAG)..."
	@git add .
	@git commit -m "release: $(TAG)" || true
	@git tag $(TAG)
	@git push origin master
	@git push origin $(TAG)

build:
	@echo "📦 Building distribution for PyPI..."
	@rm -rf dist build *.egg-info
	@$(PYTHON) -m build

upload:
	@echo "🚀 Uploading to PyPI..."
	@$(PYTHON) -m twine upload dist/*

publish: tag build upload
	@echo "✅ Published version $(VERSION) to GitHub and PyPI."
