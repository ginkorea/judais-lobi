# Makefile for Lobi Project

# Default target
.DEFAULT_GOAL := install

# Clean build artifacts
clean:
	@echo "🧹 Cleaning up build artifacts..."
	rm -rf build dist *.egg-info

# Clean virtual environment
clean-venv:
	@echo "🧹 Removing .lobienv virtual environment..."
	rm -rf .lobienv

# Bootstrap Lobi's venv
bootstrap:
	@echo "🛠 Bootstrapping .lobienv environment..."
	python3 -m venv .lobienv
	.lobienv/bin/python -m pip install --upgrade pip setuptools wheel
	.lobienv/bin/pip install requests beautifulsoup4 rich

# Install Lobi package
install: clean
	@echo "📦 Installing Lobi package..."
	pip install .

# Full reset and install
rebuild: clean clean-venv install bootstrap
	@echo "✨ Lobi is freshly rebuilt and ready!"

# Quick start (bootstrap only if needed)
quick:
	@if [ ! -d ".lobienv" ]; then \
		echo "⚡ No .lobienv found, bootstrapping..."; \
		make bootstrap; \
	else \
		echo "✅ .lobienv already exists, skipping bootstrap."; \
	fi
	@pip install .

