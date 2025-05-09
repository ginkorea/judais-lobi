VENV_NAME = .elfenv
PYTHON = python3.11

install:
	$(PYTHON) core/bootstrap.py

rebuild:
	rm -rf build dist *.egg-info .elfenv
	make install
