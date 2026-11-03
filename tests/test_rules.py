import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rules import (  # noqa: E402
    CFOP_BY_OPERATION,
    RuleError,
    cnpj_is_valid,
    cnpj_with_dv,
    key_parts,
    nfe_key_digit,
    nfe_key_is_valid,
    validate_document,
)

VALID_CNPJ = cnpj_with_dv("112223330001")


def key_for(cnpj: str, number: str = "1000", month: str = "2606", uf: str = "35") -> str:
    body = f"{uf}{month}{cnpj}55" f"001" f"{int(number):09d}" f"1" f"00000001"
    return body + nfe_key_digit(body)


def document(**overrides) -> dict:
    """Documento limpo por padrão (chave coerente incluída) — cada teste quebra só o que ele testa."""
    base = {
        "document_number": "1000",
        "emitter_cnpj": VALID_CNPJ,
        "receiver_cnpj": cnpj_with_dv("123456780001"),
        "nfe_key": key_for(VALID_CNPJ),
        "operation": "VENDA",
        "issued_at": "2026-06-01",
        "due_date": "2026-07-01",
        "total": "1000.00",
        "items": [{"item": "1", "cfop": "5102", "amount": "1000.00"}],
    }
    base.update(overrides)
    return base


class KeyCoherenceTests(unittest.TestCase):
    """A chave precisa bater com o resto do documento, não só ter DV válido."""

    def test_key_with_wrong_year_month_is_rejected(self):
        bad = key_for(VALID_CNPJ, month="9999")
        result = validate_document(document(nfe_key=bad))
        rules = {rule["rule"] for rule in result["regras"]}
        self.assertIn("chave_aamm_divergente", rules)

    def test_key_with_wrong_series_is_rejected(self):
        base = key_for(VALID_CNPJ)
        body = base[:22] + "999" + base[25:43]
        bad = body + nfe_key_digit(body)
        result = validate_document(document(nfe_key=bad, series="001"))
        rules = {rule["rule"] for rule in result["regras"]}
        self.assertIn("chave_serie_divergente", rules)

    def test_coherent_key_keeps_the_document_clean(self):
        result = validate_document(document(series="001"))
        self.assertEqual(result["regras"], [])


class TestRules(unittest.TestCase):
    def test_cnpj_check_digits(self):
        self.assertTrue(cnpj_is_valid(VALID_CNPJ))
        self.assertTrue(cnpj_is_valid("11.222.333/0001-81"))
        for invalid in ("11222333000182", "11111111111111", "1122233300018", "", "abc"):
            self.assertFalse(cnpj_is_valid(invalid))

    def test_cnpj_with_dv_matches_known_value(self):
        self.assertEqual(cnpj_with_dv("112223330001"), "11222333000181")

    def test_nfe_key_check_digit(self):
        key = key_for(VALID_CNPJ)
        self.assertEqual(len(key), 44)
        self.assertTrue(nfe_key_is_valid(key))
        broken = key[:43] + ("0" if key[43] != "0" else "1")
        self.assertFalse(nfe_key_is_valid(broken))
        self.assertFalse(nfe_key_is_valid(key[:43]))

    def test_key_parts_are_split_correctly(self):
        cnpj = cnpj_with_dv("112223330001")
        parts = key_parts(key_for(cnpj))
        self.assertEqual(parts["uf"], "SP")
        self.assertEqual(parts["emitter_cnpj"], cnpj)
        self.assertEqual(parts["model"], "55")
        self.assertEqual(parts["number"], "000001000")
        self.assertEqual(parts["year_month"], "2606")

    def test_approves_a_clean_document(self):
        result = validate_document(document(nfe_key=key_for(VALID_CNPJ)))
        self.assertEqual(result["conformidade"], "aprovado")
        self.assertEqual(result["regras"], [])

    def test_amount_tolerance_is_two_cents(self):
        ok = validate_document(document(total="1000.02", items=[{"cfop": "5102", "amount": "1000.00"}]))
        self.assertEqual(ok["conformidade"], "aprovado")
        bad = validate_document(document(total="1000.03", items=[{"cfop": "5102", "amount": "1000.00"}]))
        self.assertEqual(bad["conformidade"], "revisao_humana")
        self.assertIn("total_divergente_dos_itens", [r["rule"] for r in bad["regras"]])

    def test_cfop_must_match_operation(self):
        bad = validate_document(document(nfe_key=key_for(VALID_CNPJ), operation="VENDA",
                                         items=[{"cfop": "5201", "amount": "1000.00"}]))
        self.assertIn("cfop_incompativel", [r["rule"] for r in bad["regras"]])
        for cfop in CFOP_BY_OPERATION["VENDA"]:
            ok = validate_document(document(nfe_key=key_for(VALID_CNPJ), items=[{"cfop": cfop, "amount": "1000.00"}]))
            self.assertEqual(ok["conformidade"], "aprovado", cfop)

    def test_due_date_before_issue(self):
        result = validate_document(document(nfe_key=key_for(VALID_CNPJ), issued_at="2026-06-10",
                                            due_date="2026-06-01"))
        self.assertIn("vencimento_antes_da_emissao", [r["rule"] for r in result["regras"]])

    def test_key_must_match_document_number_and_cnpj(self):
        cnpj = cnpj_with_dv("112223330001")
        other = cnpj_with_dv("998887770001")
        wrong_cnpj = validate_document(document(emitter_cnpj=other, nfe_key=key_for(cnpj)))
        self.assertIn("chave_cnpj_divergente", [r["rule"] for r in wrong_cnpj["regras"]])
        wrong_number = validate_document(document(document_number="9999", nfe_key=key_for(cnpj)))
        self.assertIn("chave_numero_divergente", [r["rule"] for r in wrong_number["regras"]])

    def test_duplicate_key_in_batch(self):
        batch: set[str] = set()
        key = key_for(VALID_CNPJ)
        first = validate_document(document(nfe_key=key), batch_keys=batch)
        second = validate_document(document(nfe_key=key), batch_keys=batch)
        self.assertEqual(first["conformidade"], "aprovado")
        self.assertIn("chave_duplicada_no_lote", [r["rule"] for r in second["regras"]])

    def test_each_broken_field_reports_its_rule(self):
        checks = {
            "cnpj_emitente_invalido": {"emitter_cnpj": "11222333000182"},
            "chave_acesso_ausente": {"nfe_key": ""},
            "emissao_ausente": {"issued_at": ""},
            "numero_ausente": {"document_number": ""},
        }
        for rule, override in checks.items():
            result = validate_document(document(**override))
            self.assertIn(rule, [r["rule"] for r in result["regras"]], rule)

    def test_invalid_input_types_raise(self):
        with self.assertRaises(RuleError):
            validate_document("nao e dicionario")
        with self.assertRaises(RuleError):
            validate_document(document(total="valor impossivel"))
        with self.assertRaises(RuleError):
            nfe_key_digit("123")

    def test_decimals_used_for_money(self):
        result = validate_document(document(total="0.1", items=[{"cfop": "5102", "amount": "0.1"}]))
        self.assertEqual(result["conformidade"], "aprovado")
        self.assertEqual(Decimal(str(result["normalizado"]["total"])), Decimal("0.1"))


if __name__ == "__main__":
    unittest.main()
