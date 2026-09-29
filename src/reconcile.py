"""Conciliação: o que os documentos dizem vs o que a planilha do cliente registra.

Status possíveis (um por documento, sem meio-termo):
- `aprovado_automatico` — documento conforme e igual ao que a planilha registra;
- `divergencia` — valor, CNPJ ou vencimento diferente entre documento e planilha;
- `revisao_documento` — o próprio documento viola regra fiscal (chave, CNPJ, total, CFOP, data);
- `duplicado` — a mesma chave aparece mais de uma vez no lote (documento ou planilha);
- `ausente_na_planilha` — documento existe e a planilha não tem a linha;
- `ausente_nos_documentos` — a planilha tem linha sem documento correspondente.
"""
from __future__ import annotations

from decimal import Decimal

from src.rules import RuleError, only_digits, validate_document

AMOUNT_TOLERANCE = Decimal("0.02")


def _decimal(value: object) -> Decimal:
    text = str(value or "").strip().replace(".", "").replace(",", ".") if "," in str(value or "") else str(value or "").strip()
    if text == "":
        return Decimal("0")
    try:
        return Decimal(text)
    except Exception:
        return Decimal("0")


def _key_of(document: dict) -> str:
    key = only_digits(document.get("nfe_key", ""))
    return key or f"NUM:{str(document.get('document_number') or '').strip()}"


def reconcile(documents: list[dict], spreadsheet_rows: list[dict]) -> dict:
    """Casa documento e planilha pela chave de acesso (ou número, quando não há chave)."""
    batch_keys: set[str] = set()
    spreadsheet_by_key: dict[str, list[dict]] = {}
    for row in spreadsheet_rows:
        spreadsheet_by_key.setdefault(_key_of(row), []).append(row)

    results: list[dict] = []
    matched: set[str] = set()

    for document in documents:
        try:
            evaluation = validate_document(document, batch_keys=batch_keys)
        except RuleError as exc:
            results.append({
                "key": _key_of(document), "document_number": document.get("document_number", ""),
                "status": "revisao_documento", "rules": [{"rule": "documento_ilegivel", "expected": "documento válido",
                                                          "found": str(exc)}],
                "source_file": document.get("file", ""), "total_document": "", "total_spreadsheet": "", "due_date": "",
            })
            matched.add(_key_of(document))
            continue

        key = _key_of(document)
        normalized = evaluation["normalizado"]
        rows = spreadsheet_by_key.get(key, [])
        row = rows[0] if rows else None
        matched.add(key)

        entry = {
            "key": key,
            "document_number": normalized.get("document_number", ""),
            "emitter_cnpj": normalized.get("emitter_cnpj", ""),
            "source_file": document.get("file", ""),
            "source_kind": document.get("source", ""),
            "total_document": f"{normalized.get('total', 0):.2f}",
            "total_spreadsheet": "",
            "due_date": normalized.get("due_date", ""),
            "status": "aprovado_automatico",
            "rules": list(evaluation["regras"]),
        }

        if evaluation["conformidade"] == "revisao_humana":
            entry["status"] = "revisao_documento"
        elif len(rows) > 1:
            entry["status"] = "duplicado"
            entry["rules"].append({"rule": "linha_duplicada_na_planilha", "expected": "1 linha",
                                   "found": f"{len(rows)} linhas"})
        elif row is None:
            entry["status"] = "ausente_na_planilha"
            entry["rules"].append({"rule": "documento_ausente_na_planilha", "expected": "linha na planilha",
                                   "found": "não encontrada"})
        else:
            entry["total_spreadsheet"] = f"{_decimal(row.get('total')):.2f}"
            if abs(_decimal(row.get("total")) - _decimal(entry["total_document"])) > AMOUNT_TOLERANCE:
                entry["status"] = "divergencia"
                entry["rules"].append({"rule": "valor_divergente", "expected": entry["total_document"],
                                       "found": entry["total_spreadsheet"]})
            if only_digits(row.get("emitter_cnpj", "")) != normalized.get("emitter_cnpj", ""):
                entry["status"] = "divergencia"
                entry["rules"].append({"rule": "cnpj_divergente", "expected": normalized.get("emitter_cnpj", ""),
                                       "found": only_digits(row.get("emitter_cnpj", "")) or "ausente"})
            document_due = str(normalized.get("due_date") or "")[:10]
            spreadsheet_due = str(row.get("due_date") or "")[:10]
            if document_due and spreadsheet_due and spreadsheet_due != document_due:
                entry["status"] = "divergencia"
                entry["rules"].append({"rule": "vencimento_divergente", "expected": str(normalized.get("due_date") or ""),
                                       "found": str(row.get("due_date"))[:10]})
        results.append(entry)

    for key, rows in spreadsheet_by_key.items():
        if key not in matched:
            results.append({
                "key": key, "document_number": str(rows[0].get("document_number") or ""),
                "emitter_cnpj": only_digits(rows[0].get("emitter_cnpj", "")), "source_file": "", "source_kind": "",
                "total_document": "", "total_spreadsheet": f"{_decimal(rows[0].get('total')):.2f}",
                "due_date": str(rows[0].get("due_date") or "")[:10], "status": "ausente_nos_documentos",
                "rules": [{"rule": "linha_sem_documento", "expected": "documento correspondente",
                           "found": "nenhum documento no lote"}],
            })

    order = {"divergencia": 0, "revisao_documento": 1, "duplicado": 2, "ausente_na_planilha": 3,
             "ausente_nos_documentos": 4, "aprovado_automatico": 5}
    results.sort(key=lambda item: (order.get(item["status"], 9), item["document_number"], item["key"]))

    summary: dict[str, int] = {}
    for item in results:
        summary[item["status"]] = summary.get(item["status"], 0) + 1
    rules_count: dict[str, int] = {}
    for item in results:
        for rule in item["rules"]:
            rules_count[rule["rule"]] = rules_count.get(rule["rule"], 0) + 1

    total = len(results)
    approved = summary.get("aprovado_automatico", 0)
    return {
        "documents": len(documents),
        "spreadsheet_rows": len(spreadsheet_rows),
        "results": results,
        "summary": summary,
        "rules_count": dict(sorted(rules_count.items(), key=lambda item: -item[1])),
        "automation_rate": round(approved / total, 4) if total else 0.0,
        "review_words": total - approved,
    }
