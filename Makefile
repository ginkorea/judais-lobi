# ===== JudAIs-Lobi Build & Maintenance =====

# setup.py owns the version. Read it here rather than repeat it: this line
# used to say v0.7.2 long after the package had stopped agreeing.
VERSION := $(shell sed -n 's/^VERSION = "\(.*\)"/\1/p' setup.py)

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
	@echo "\n✅ Rebuild complete for JudAIs-Lobi v$(VERSION)"

# Publish to PyPI (optional)
publish:
	twine upload dist/*

# Test suite
test:
	python -m pytest tests/ -v --tb=short

test-cov:
	python -m pytest tests/ -v --tb=short --cov=core --cov=lobi --cov=judais --cov-report=term-missing

# Quick test commands
test-lobi:
	lobi "Hello Lobi" --provider openai

test-judais:
	judais "Hello JudAIs" --provider mistral
