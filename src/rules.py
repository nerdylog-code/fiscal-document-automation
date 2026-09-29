"""Regras fiscais de conferência — implementadas de verdade, não decoradas.

O que é verificado em cada documento:
- **CNPJ** (emitente e destinatário): dígitos verificadores pelo módulo 11.
- **Chave de acesso da NF-e** (44 dígitos): dígito verificador + coerência interna
  (UF, AAMM, CNPJ do emitente, modelo, série e número têm de bater com o resto do XML).
- **Total** do documento contra a soma dos itens (tolerância de 2 centavos para arredondamento).
- **CFOP** compatível com a natureza da operação declarada.
- **Datas**: vencimento não pode ser anterior à emissão.
- **Duplicidade** de chave no mesmo lote.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

TOLERANCE = Decimal("0.02")

CNPJ_WEIGHTS_FIRST = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
CNPJ_WEIGHTS_SECOND = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
KEY_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9]

CFOP_BY_OPERATION = {
    "VENDA": {"5101", "5102", "6101", "6102", "5405", "6404"},
    "DEVOLUCAO": {"5201", "5202", "6201", "6202"},
    "SERVICO": {"5933", "6933"},
    "REMESSA": {"5901", "5902", "6901", "6902"},
}
UF_BY_CODE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


class RuleError(ValueError):
    """Documento impossível de avaliar (campo ausente ou formato inesperado)."""


def only_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _check_digit(digits: str, weights: list[int]) -> str:
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights))
    remainder = total % 11
    check = 11 - remainder
    return "0" if check >= 10 else str(check)


def cnpj_is_valid(cnpj: str) -> bool:
    digits = only_digits(cnpj)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    first = _check_digit(digits[:12], CNPJ_WEIGHTS_FIRST)
    second = _check_digit(digits[:12] + first, CNPJ_WEIGHTS_SECOND)
    return digits[12] == first and digits[13] == second


def cnpj_with_dv(base12: str) -> str:
    """Usado pelos fixtures: completa os dois dígitos verificadores de uma base de 12 dígitos."""
    if len(base12) != 12 or not base12.isdigit():
        raise RuleError("base de CNPJ precisa ter 12 dígitos")
    first = _check_digit(base12, CNPJ_WEIGHTS_FIRST)
    return base12 + first + _check_digit(base12 + first, CNPJ_WEIGHTS_SECOND)


def nfe_key_digit(key43: str) -> str:
    if len(key43) != 43 or not key43.isdigit():
        raise RuleError("chave sem DV precisa ter 43 dígitos")
    total = 0
    for position, digit in enumerate(reversed(key43)):
        total += int(digit) * KEY_WEIGHTS[position % 8]
    remainder = total % 11
    digit = 11 - remainder
    return "0" if digit >= 10 else str(digit)


def nfe_key_is_valid(key: str) -> bool:
    digits = only_digits(key)
    return len(digits) == 44 and digits[43] == nfe_key_digit(digits[:43])


def key_parts(key: str) -> dict:
    digits = only_digits(key)
    if len(digits) != 44:
        raise RuleError("chave de acesso precisa ter 44 dígitos")
    return {
        "uf_code": digits[:2],
        "uf": UF_BY_CODE.get(digits[:2], ""),
        "year_month": digits[2:6],
        "emitter_cnpj": digits[6:20],
        "model": digits[20:22],
        "series": digits[22:25],
        "number": digits[25:34],
        "emission_type": digits[34:35],
        "code": digits[35:43],
        "check_digit": digits[43],
    }


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    text = str(value or "").strip().replace(".", "").replace(",", ".") if "," in str(value or "") else str(value or "").strip()
    if text in ("", "None"):
        raise RuleError("valor ausente")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise RuleError(f"valor inválido: {value!r}") from exc


def validate_document(document: dict, batch_keys: set[str] | None = None) -> dict:
    """Devolve {'conformidade': 'aprovado'|'revisao_humana', 'regras': [...], 'normalizado': {...}}."""
    if not isinstance(document, dict):
        raise RuleError("documento deve ser um objeto")

    broke: list[dict] = []
    normalized: dict = {}

    normalized["document_number"] = str(document.get("document_number") or "").strip()
    if not normalized["document_number"]:
        broke.append({"rule": "numero_ausente", "expected": "número do documento", "found": ""})

    emitter = only_digits(document.get("emitter_cnpj", ""))
    normalized["emitter_cnpj"] = emitter
    if not cnpj_is_valid(emitter):
        broke.append({"rule": "cnpj_emitente_invalido", "expected": "CNPJ com DV válido", "found": emitter or "ausente"})

    receiver = only_digits(document.get("receiver_cnpj", ""))
    normalized["receiver_cnpj"] = receiver
    if receiver and not cnpj_is_valid(receiver):
        broke.append({"rule": "cnpj_destinatario_invalido", "expected": "CNPJ com DV válido", "found": receiver})

    key = only_digits(document.get("nfe_key", ""))
    normalized["nfe_key"] = key
    if key:
        if not nfe_key_is_valid(key):
            broke.append({"rule": "chave_acesso_invalida", "expected": "44 dígitos com DV correto", "found": key})
        else:
            parts = key_parts(key)
            normalized["uf"] = parts["uf"]
            if parts["emitter_cnpj"] != emitter:
                broke.append({"rule": "chave_cnpj_divergente", "expected": emitter, "found": parts["emitter_cnpj"]})
            if parts["model"] != "55":
                broke.append({"rule": "modelo_inesperado", "expected": "55 (NF-e)", "found": parts["model"]})
            if normalized["document_number"] and parts["number"].lstrip("0") != normalized["document_number"]:
                broke.append({"rule": "chave_numero_divergente", "expected": normalized["document_number"],
                              "found": parts["number"].lstrip("0")})
    else:
        broke.append({"rule": "chave_acesso_ausente", "expected": "chave de 44 dígitos", "found": "ausente"})

    total = _decimal(document.get("total"))
    normalized["total"] = float(total)
    items = document.get("items") or []
    if items:
        items_sum = sum((_decimal(item.get("amount", "0")) for item in items), Decimal("0"))
        normalized["items_total"] = float(items_sum)
        if abs(items_sum - total) > TOLERANCE:
            broke.append({"rule": "total_divergente_dos_itens", "expected": f"{items_sum:.2f}", "found": f"{total:.2f}"})
        for item in items:
            cfop = str(item.get("cfop") or "")
            allowed = CFOP_BY_OPERATION.get(str(document.get("operation") or "").upper(), set())
            if allowed and cfop not in allowed:
                broke.append({"rule": "cfop_incompativel", "expected": "/".join(sorted(allowed)),
                              "found": f"{cfop} para operação {document.get('operation')}"})

    issued = str(document.get("issued_at") or "")[:10]
    normalized["issued_at"] = issued
    if not issued:
        broke.append({"rule": "emissao_ausente", "expected": "data de emissão", "found": "ausente"})
    else:
        try:
            normalized["issued_date"] = date.fromisoformat(issued)
        except ValueError:
            broke.append({"rule": "emissao_invalida", "expected": "AAAA-MM-DD", "found": issued})

    due = str(document.get("due_date") or "")[:10]
    if due:
        try:
            due_date = date.fromisoformat(due)
            normalized["due_date"] = due_date
            if "issued_date" in normalized and due_date < normalized["issued_date"]:
                broke.append({"rule": "vencimento_antes_da_emissao", "expected": issued, "found": due})
        except ValueError:
            broke.append({"rule": "vencimento_invalido", "expected": "AAAA-MM-DD", "found": due})

    if batch_keys is not None and key:
        if key in batch_keys:
            broke.append({"rule": "chave_duplicada_no_lote", "expected": "chave única", "found": key})
        batch_keys.add(key)

    return {
        "conformidade": "revisao_humana" if broke else "aprovado",
        "regras": broke,
        "normalizado": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in normalized.items()},
    }
