# ===== JudAIs-Lobi Build & Maintenance =====

# Clean up previous build artifacts
clean:
	rm -rf build dist *.egg-info __pycache__

# Install core and voice dependencies
deps:
	pip install -U pip setuptools wheel
	pip install -r requirements.txt

# Build distributables (source + wheel)
build: clean deps
	python setup.py sdist bdist_wheel

# Local editable install for dev use
install:
	pip install -e .[voice]

# Full rebuild: clean, rebuild, reinstall
rebuild: clean deps build install
	@echo "\n✅ Rebuild complete for JudAIs-Lobi v0.7.2"

# Publish to PyPI (optional)
publish:
	twine upload dist/*

# Quick test commands
test-lobi:
	lobi "Hello Lobi" --provider openai

test-judais:
	judais "Hello JudAIs" --provider mistral
