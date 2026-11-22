PYTHON ?= python
INDEX ?= 0

.PHONY: help flow test install

help:
	@echo LDPlayer Auto Clicker
	@echo   make flow            open the editor on instance 0
	@echo   make flow INDEX=1    open the editor on instance 1
	@echo   make test            run unit tests
	@echo   make install         install dependencies

flow:
	$(PYTHON) editor/floweditor.py --index $(INDEX)

test:
	$(PYTHON) -m unittest discover -s tests -t . -p "test_*.py"

install:
	$(PYTHON) -m pip install -r requirements.txt
