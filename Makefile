install:
	python3.11 -m venv .lobienv
	. .lobienv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt

bootstrap:
	python3.11 lobi/bootstrap.py

rebuild:
	rm -rf build dist *.egg-info .lobienv
	make install
	make bootstrap
