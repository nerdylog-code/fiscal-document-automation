#!/usr/bin/env python3
"""Checagem executável dos artefatos deste repositório — só biblioteca padrão.

Falha (exit != 0) se um artefato sumir, esvaziar ou deixar de bater com o baseline versionado
em `checks/expected.json`. Rode `python checks/check_artifacts.py --update` para regravar o baseline
depois de mudar os dados de propósito.
"""
from __future__ import annotations

import csv
import json
import pathlib
import sqlite3
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / "checks" / "expected.json"
SKIP_DIRS = {".git", "checks", "__pycache__", "node_modules"}


def walk(patterns: list[str]) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in patterns:
            found.append(path)
    return sorted(found)


def inspect_csv(path: pathlib.Path) -> dict:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        rows = sum(1 for _ in reader)
    assert header, f"{path}: CSV sem cabeçalho"
    assert rows > 0, f"{path}: CSV sem linhas de dados"
    return {"rows": rows, "columns": len(header)}


def inspect_db(path: pathlib.Path) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert tables, f"{path}: banco sem tabela"
        counts = {}
        for table in tables:
            count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert count > 0, f"{path}: tabela {table} vazia"
            counts[table] = count
    finally:
        con.close()
    return counts


def inspect_xlsx(path: pathlib.Path) -> dict:
    assert zipfile.is_zipfile(path), f"{path}: não é um arquivo xlsx válido"
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert "xl/workbook.xml" in names, f"{path}: xlsx sem workbook.xml"
        workbook = zf.read("xl/workbook.xml").decode("utf-8", "replace")
    sheets = workbook.count("<sheet ")
    assert sheets > 0, f"{path}: xlsx sem planilha"
    return {"sheets": sheets}


def inspect_sql(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    assert "select" in text.lower(), f"{path}: SQL sem nenhuma consulta"
    statements = text.count(";")
    return {"statements": statements}


def inspect_xml(path: pathlib.Path) -> dict:
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    return {"root": root.tag.split("}")[-1], "children": len(list(root.iter()))}


def collect() -> dict:
    report: dict = {"csv": {}, "sqlite": {}, "xlsx": {}, "sql": {}, "xml": {}}
    for path in walk([".csv"]):
        report["csv"][str(path.relative_to(ROOT))] = inspect_csv(path)
    for path in walk([".db", ".sqlite", ".sqlite3"]):
        report["sqlite"][str(path.relative_to(ROOT))] = inspect_db(path)
    for path in walk([".xlsx", ".xlsm"]):
        report["xlsx"][str(path.relative_to(ROOT))] = inspect_xlsx(path)
    for path in walk([".sql"]):
        report["sql"][str(path.relative_to(ROOT))] = inspect_sql(path)
    for path in walk([".xml"]):
        report["xml"][str(path.relative_to(ROOT))] = inspect_xml(path)
    total = sum(len(v) for v in report.values())
    assert total > 0, "nenhum artefato de dados encontrado — a checagem não estaria verificando nada"
    return report


def main() -> int:
    report = collect()
    if "--update" in sys.argv:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline gravado em {BASELINE.relative_to(ROOT)}")
        return 0

    assert BASELINE.exists(), "baseline ausente — rode com --update para criar"
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    problems = []
    for kind, expected_items in expected.items():
        actual_items = report.get(kind, {})
        for name, expected_value in expected_items.items():
            if name not in actual_items:
                problems.append(f"artefato desapareceu: {name}")
            elif actual_items[name] != expected_value:
                problems.append(f"{name}: esperado {expected_value}, encontrado {actual_items[name]}")
        for name in actual_items:
            if name not in expected_items:
                problems.append(f"artefato novo sem baseline: {name}")
    for line in problems:
        print(f"FALHA: {line}")
    if problems:
        return 1
    checked = sum(len(v) for v in expected.values())
    print(f"OK — {checked} artefatos conferidos contra o baseline")
    for kind, items in sorted(expected.items()):
        for name, value in sorted(items.items()):
            print(f"  {kind:<7}{name:<45}{value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
