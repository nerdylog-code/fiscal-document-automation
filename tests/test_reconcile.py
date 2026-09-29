import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.reconcile import reconcile  # noqa: E402
from src.rules import cnpj_with_dv, nfe_key_digit  # noqa: E402

CNPJ = cnpj_with_dv("112223330001")


def key(number: int) -> str:
    body = f"35" f"2606" f"{CNPJ}" f"55" f"001" f"{number:09d}" f"1" f"00000001"
    return body + nfe_key_digit(body)


def document(number: int, total: str = "100.00", due: str = "2026-07-01", **overrides) -> dict:
    base = {
        "source": "xml", "file": f"nfe_{number}.xml", "document_number": str(number), "operation": "VENDA",
        "issued_at": "2026-06-01", "due_date": due, "emitter_cnpj": CNPJ, "receiver_cnpj": "",
        "total": total, "nfe_key": key(number), "items": [{"cfop": "5102", "amount": total}],
    }
    base.update(overrides)
    return base


def row(number: int, total: str = "100.00", due: str = "2026-07-01", cnpj: str = None) -> dict:
    return {"document_number": str(number), "nfe_key": key(number), "total": total,
            "due_date": due, "emitter_cnpj": cnpj or CNPJ}


class TestReconcile(unittest.TestCase):
    def test_approved_when_everything_matches(self):
        result = reconcile([document(1000)], [row(1000)])
        self.assertEqual(result["summary"], {"aprovado_automatico": 1})
        self.assertEqual(result["automation_rate"], 1.0)

    def test_amount_divergence(self):
        result = reconcile([document(1000, total="100.00")], [row(1000, total="150.00")])
        item = result["results"][0]
        self.assertEqual(item["status"], "divergencia")
        self.assertIn("valor_divergente", [r["rule"] for r in item["rules"]])
        self.assertEqual(item["total_document"], "100.00")
        self.assertEqual(item["total_spreadsheet"], "150.00")

    def test_tolerance_applies_to_reconciliation(self):
        result = reconcile([document(1000, total="100.00")], [row(1000, total="100.02")])
        self.assertEqual(result["results"][0]["status"], "aprovado_automatico")

    def test_cnpj_and_due_date_divergences(self):
        other = cnpj_with_dv("445566770001")
        result = reconcile([document(1000), document(2000)], [row(1000, cnpj=other), row(2000, due="2026-06-15")])
        statuses = {item["document_number"]: item for item in result["results"]}
        self.assertIn("cnpj_divergente", [r["rule"] for r in statuses["1000"]["rules"]])
        self.assertIn("vencimento_divergente", [r["rule"] for r in statuses["2000"]["rules"]])

    def test_missing_rows_both_ways(self):
        result = reconcile([document(1000), document(2000)], [row(2000), row(3000)])
        statuses = {item["document_number"]: item["status"] for item in result["results"]}
        self.assertEqual(statuses["3000"], "ausente_nos_documentos")
        self.assertEqual(statuses["1000"], "ausente_na_planilha")

    def test_duplicate_rows_are_duplicado(self):
        result = reconcile([document(1000)], [row(1000), row(1000)])
        self.assertEqual(result["results"][0]["status"], "duplicado")
        self.assertIn("linha_duplicada_na_planilha", [r["rule"] for r in result["results"][0]["rules"]])

    def test_document_rules_dominate_the_status(self):
        result = reconcile([document(1000, nfe_key="1" * 44)], [row(1000)])
        item = result["results"][0]
        self.assertEqual(item["status"], "revisao_documento")
        self.assertIn("chave_acesso_invalida", [r["rule"] for r in item["rules"]])

    def test_unreadable_document_does_not_break_the_batch(self):
        broken = document(1000)
        broken["total"] = "valor invalido"
        result = reconcile([broken, document(2000)], [row(1000), row(2000)])
        statuses = {item["document_number"]: item["status"] for item in result["results"]}
        self.assertEqual(statuses["1000"], "revisao_documento")
        self.assertEqual(statuses["2000"], "aprovado_automatico")

    def test_results_put_problems_first(self):
        result = reconcile([document(1000), document(2000, total="100.00")], [row(1000), row(2000, total="200.00")])
        self.assertEqual(result["results"][0]["status"], "divergencia")

    def test_counts_are_consistent(self):
        documents = [document(1000 + i) for i in range(10)]
        rows = [row(1000 + i) for i in range(8)]
        result = reconcile(documents, rows)
        self.assertEqual(result["documents"], 10)
        self.assertEqual(result["spreadsheet_rows"], 8)
        self.assertEqual(sum(result["summary"].values()), len(result["results"]))
        self.assertEqual(result["summary"]["ausente_na_planilha"], 2)


if __name__ == "__main__":
    unittest.main()
