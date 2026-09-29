import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pdf import find_field, read_pdf, write_pdf  # noqa: E402


class TestPdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "danfe.pdf")
        cls.lines = [
            "DANFE - DOCUMENTO AUXILIAR DE VENDA",
            "CNPJ EMITENTE: 11.222.333/0001-81",
            "VALOR TOTAL: 1.234,56",
            "DATA DE EMISSAO: 2026-06-01",
            "CHAVE DE ACESSO:",
            "35260611222333000181550010000000011000000017",
        ]
        write_pdf(cls.path, cls.lines, "danfe")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_file_is_a_valid_pdf(self):
        data = open(self.path, "rb").read()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertIn(b"xref", data)
        self.assertIn(b"startxref", data)
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))

    def test_lines_come_back_in_order(self):
        self.assertEqual(read_pdf(self.path), self.lines)

    def test_field_extraction(self):
        lines = read_pdf(self.path)
        self.assertEqual(find_field(lines, r"CNPJ EMITENTE:\s*([\d./-]+)"), "11.222.333/0001-81")
        self.assertEqual(find_field(lines, r"VALOR TOTAL:\s*([\d.,]+)"), "1.234,56")
        self.assertEqual(find_field(lines, r"DATA DE EMISSAO:\s*(\d{4}-\d{2}-\d{2})"), "2026-06-01")
        self.assertEqual(find_field(lines, r"NAO EXISTE:\s*(\w+)"), "")

    def test_escaped_parentheses(self):
        path = os.path.join(self.tmp.name, "escape.pdf")
        write_pdf(path, ["OBS: valor (bruto) com \\ caractere"], "escape")
        self.assertEqual(read_pdf(path), ["OBS: valor (bruto) com \\ caractere"])

    def test_reads_deflated_streams(self):
        """PDFs de ERP costumam vir com FlateDecode: o extrator precisa descomprimir."""
        import zlib
        path = os.path.join(self.tmp.name, "deflated.pdf")
        write_pdf(path, ["LINHA COMPRIMIDA"], "d")
        data = open(path, "rb").read()
        plain = b"BT\n1 0 0 1 40 700 Tm\n(LINHA COMPRIMIDA) Tj\nET"
        compressed = zlib.compress(plain)
        rebuilt = data.replace(
            b"<< /Length " + str(len(plain)).encode() + b" >>\nstream\n" + plain + b"\nendstream",
            b"<< /Length " + str(len(compressed)).encode() + b" /Filter /FlateDecode >>\nstream\n" + compressed + b"\nendstream",
        )
        open(path, "wb").write(rebuilt)
        self.assertEqual(read_pdf(path), ["LINHA COMPRIMIDA"])


if __name__ == "__main__":
    unittest.main()
