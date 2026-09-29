import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.make_fixtures import generate  # noqa: E402
from src.nfe import read_nfe_xml  # noqa: E402


class TestNfe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        fixtures = generate(seed=42, count=8, directory=os.path.join(cls.tmp.name, "fixtures"))
        cls.documents = fixtures["documents"]
        cls.xml_documents = [d for d in cls.documents if d["source"] == "xml"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reads_all_expected_fields(self):
        document = read_nfe_xml(self.xml_documents[0]["file"])
        for field in ("document_number", "series", "model", "operation", "issued_at", "due_date",
                      "emitter_cnpj", "emitter_name", "receiver_cnpj", "total", "nfe_key"):
            self.assertTrue(document[field], f"campo vazio: {field}")
        self.assertEqual(document["model"], "55")
        self.assertTrue(document["items"])
        self.assertEqual(document["items"][0]["cfop"], "5102")

    def test_due_date_comes_from_the_duplicate(self):
        """Vencimento na NF-e vive em cobr/dup/dVenc — sem isso a conciliação compararia vazio."""
        document = read_nfe_xml(self.xml_documents[0]["file"])
        self.assertRegex(document["due_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_key_matches_generated_fixture(self):
        for document in self.xml_documents[:5]:
            read = read_nfe_xml(document["file"])
            self.assertEqual(read["nfe_key"], document["nfe_key"])
            self.assertEqual(read["total"], document["total"])

    def test_missing_infnfe_raises(self):
        path = os.path.join(self.tmp.name, "vazio.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><root/>')
        with self.assertRaises(ValueError):
            read_nfe_xml(path)

    def test_missing_key_id_raises(self):
        path = os.path.join(self.tmp.name, "sem_chave.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0"?><nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">'
                     "<NFe><infNFe versao=\"4.00\"><ide><nNF>1</nNF></ide></infNFe></NFe></nfeProc>")
        with self.assertRaises(ValueError):
            read_nfe_xml(path)


if __name__ == "__main__":
    unittest.main()
