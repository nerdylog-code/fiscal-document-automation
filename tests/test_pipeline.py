"""Ponta a ponta: os fixtures declaram as divergências, o pipeline tem de achá-las todas."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.make_fixtures import DIVERGENCES, generate  # noqa: E402
from src.pipeline import load_documents, run, spreadsheet_rows  # noqa: E402
from src.reconcile import reconcile  # noqa: E402
from src.xlsx import read_xlsx  # noqa: E402

def drizzle(number: int) -> int:
    """O fixture trabalha com índice; o documento fiscal é numerado a partir de 1000."""
    return 1000 + number


EXPECTED_STATUS = {}
for index in DIVERGENCES["spreadsheet_amount"] | DIVERGENCES["spreadsheet_cnpj"] | DIVERGENCES["spreadsheet_due_before_issue"]:
    EXPECTED_STATUS[str(drizzle(index))] = "divergencia"
for index in DIVERGENCES["spreadsheet_duplicate_row"]:
    EXPECTED_STATUS[str(drizzle(index))] = "duplicado"
for index in DIVERGENCES["spreadsheet_missing_document"]:
    EXPECTED_STATUS[str(drizzle(index))] = "ausente_na_planilha"
for group in ("document_invalid_cnpj", "document_total_mismatch", "document_bad_cfop", "document_bad_key"):
    for index in DIVERGENCES[group]:
        EXPECTED_STATUS[str(drizzle(index))] = "revisao_documento"


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fixtures = os.path.join(cls.tmp.name, "fixtures")
        cls.output = os.path.join(cls.tmp.name, "output")
        cls.result = run(cls.fixtures, cls.output, seed=42, count=60)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_injected_divergence_is_found(self):
        found = {item["document_number"]: item["status"] for item in
                 reconcile(load_documents(self.fixtures),
                           spreadsheet_rows(os.path.join(self.fixtures, "planilha_cliente.xlsx")))["results"]}
        for number, expected in sorted(EXPECTED_STATUS.items()):
            self.assertEqual(found.get(number), expected, f"documento {number}")

    def test_summary_matches_the_injected_scenario(self):
        summary = self.result["reconciliation"]["summary"]
        self.assertEqual(summary["divergencia"], 5)
        self.assertEqual(summary["revisao_documento"], 4)
        self.assertEqual(summary["duplicado"], 1)
        self.assertEqual(summary["ausente_na_planilha"], 2)
        self.assertEqual(summary["ausente_nos_documentos"], 2)
        self.assertEqual(summary["aprovado_automatico"], 48)
        self.assertEqual(self.result["reconciliation"]["documents"], 60)

    def test_readers_cover_both_formats(self):
        documents = load_documents(self.fixtures)
        kinds = {document["source"] for document in documents}
        self.assertEqual(kinds, {"xml", "pdf"})
        self.assertEqual(len([d for d in documents if d["source"] == "pdf"]), 15)

    def test_workbook_has_three_sheets_with_expected_headers(self):
        workbook = self.result["workbook"]
        self.assertTrue(os.path.exists(workbook))
        sheets = read_xlsx(workbook)
        self.assertEqual(list(sheets), ["Conferência", "Divergências", "Resumo"])
        self.assertEqual(sheets["Conferência"][0][:3], ["documento", "origem", "cnpj_emitente"])
        self.assertEqual(sheets["Divergências"][0][:3], ["documento", "status", "regra"])
        self.assertGreaterEqual(len(sheets["Conferência"]) - 1, 60)
        self.assertGreater(len(sheets["Divergências"]), 1, "havia divergências injetadas")
        self.assertIn("status: divergencia", [row[0] for row in sheets["Resumo"]])

    def test_summary_json_is_written_and_honest(self):
        path = os.path.join(self.output, "resumo.json")
        self.assertTrue(os.path.exists(path))
        data = json.load(open(path, encoding="utf-8"))
        self.assertIn("PARÂMETRO DECLARADO", data["impact"]["note"])
        self.assertNotIn("elapsed_seconds_measured", data["impact"], "tempo medido não entra no entregável")
        self.assertEqual(data["fixtures"]["seed"], 42)
        self.assertEqual(data["fixtures"]["count"], 60)

    def test_impact_math_is_consistent(self):
        business = self.result["impact"]
        self.assertEqual(business["documents"], 60)
        self.assertEqual(business["manual_hours_for_the_batch"], 12.0)
        self.assertAlmostEqual(business["hours_saved"]["declared"], 12.0, delta=0.05)
        self.assertLess(business["hours_saved"]["pessimistic"], business["hours_saved"]["declared"])
        self.assertLess(business["hours_saved"]["declared"], business["hours_saved"]["optimistic"])
        self.assertNotIn("elapsed_seconds_measured", business)

    def test_measured_performance_lives_in_its_own_file(self):
        path = os.path.join(self.output, "desempenho.json")
        self.assertTrue(os.path.exists(path), "tempo medido tem de ficar registrado em algum lugar")
        performance = json.load(open(path, encoding="utf-8"))
        self.assertGreater(performance["elapsed_seconds_measured"], 0)
        self.assertGreater(performance["documents_per_minute_measured"], 0)
        self.assertRegex(performance["workbook_sha256"], r"^[0-9a-f]{64}$")

    def test_committed_deliverables_are_byte_identical_between_runs(self):
        """O que vai para o repositório não pode variar de uma execução para outra (é o que o CI compara)."""
        names = ("conferencia_fiscal.xlsx", "resumo.json")
        run(self.fixtures, self.output, seed=42, count=60)
        first = {name: open(os.path.join(self.output, name), "rb").read() for name in names}
        run(self.fixtures, self.output, seed=42, count=60)
        for name in names:
            second = open(os.path.join(self.output, name), "rb").read()
            self.assertEqual(first[name], second, f"{name} mudou entre execuções")

    def test_rerun_is_byte_identical(self):
        other_output = os.path.join(self.tmp.name, "output2")
        second = run(self.fixtures, other_output, seed=42, count=60)
        self.assertEqual(open(self.result["workbook"], "rb").read(), open(second["workbook"], "rb").read())

    def test_fixtures_are_deterministic_across_generations(self):
        a = generate(seed=7, count=12, directory=os.path.join(self.tmp.name, "f1"))
        b = generate(seed=7, count=12, directory=os.path.join(self.tmp.name, "f2"))
        names_a = sorted(os.path.basename(d["file"]) for d in a["documents"])
        names_b = sorted(os.path.basename(d["file"]) for d in b["documents"])
        self.assertEqual(names_a, names_b)
        self.assertEqual(a["spreadsheet_rows"], b["spreadsheet_rows"])


if __name__ == "__main__":
    unittest.main()
