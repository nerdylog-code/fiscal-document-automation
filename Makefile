PY ?= python3

.PHONY: all fixtures test check repro clean help

help:
	@echo "make all      - fixtures + pipeline completo (gera output/conferencia_fiscal.xlsx)"
	@echo "make fixtures - só gera os documentos sintéticos"
	@echo "make test     - suíte unittest (núcleo é só stdlib)"
	@echo "make check    - confere os artefatos contra o baseline versionado"
	@echo "make repro    - roda 2x e compara o hash da planilha gerada"
	@echo "make clean    - remove fixtures e output"

all:
	$(PY) -m src.pipeline

fixtures:
	$(PY) -m src.make_fixtures

test:
	$(PY) -m unittest discover -s tests -t .

check:
	$(PY) checks/check_artifacts.py

repro:
	$(PY) -m src.pipeline > /dev/null
	@sha256sum output/conferencia_fiscal.xlsx | cut -c1-16
	$(PY) -m src.pipeline > /dev/null
	@sha256sum output/conferencia_fiscal.xlsx | cut -c1-16
	@echo "as duas linhas acima precisam ser iguais"

clean:
	rm -rf fixtures output __pycache__ */__pycache__ .coverage
