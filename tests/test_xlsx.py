import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.xlsx import column_index, column_letter, read_xlsx, write_xlsx  # noqa: E402


class TestXlsx(unittest.TestCase):
    def test_column_conversion_roundtrip(self):
        for index in (0, 1, 25, 26, 27, 51, 52, 701):
            self.assertEqual(column_index(column_letter(index)), index)

    def test_roundtrip_types_and_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.xlsx")
            write_xlsx(path, {"Conferência": [
                ["documento", "valor", "aprovado", "observação"],
                ["NF-1", 1234.56, True, "conferência automática — ção"],
                ["NF-2", 0, False, ""],
            ]})
            sheets = read_xlsx(path)
            self.assertEqual(list(sheets), ["Conferência"])
            self.assertEqual(sheets["Conferência"][0], ["documento", "valor", "aprovado", "observação"])
            self.assertEqual(sheets["Conferência"][1][1], 1234.56)
            self.assertIs(sheets["Conferência"][1][2], True)
            self.assertIs(sheets["Conferência"][2][2], False)
            self.assertEqual(sheets["Conferência"][1][3], "conferência automática — ção")

    def test_multiple_sheets_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.xlsx")
            write_xlsx(path, {"Resumo": [["a"], [1]], "Divergências": [["b"], [2]]})
            sheets = read_xlsx(path)
            self.assertEqual(list(sheets), ["Resumo", "Divergências"])
            self.assertEqual(sheets["Divergências"][1][0], 2)

    def test_write_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "a.xlsx")
            second = os.path.join(tmp, "b.xlsx")
            sheets = {"S": [["x", "y"], [1, "ç"]], "T": [["z"]]}
            write_xlsx(first, sheets)
            write_xlsx(second, sheets)
            self.assertEqual(open(first, "rb").read(), open(second, "rb").read())

    def test_escaped_characters_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.xlsx")
            write_xlsx(path, {"S": [["regra"], ["valor < 10 & esperado > 5"]]})
            self.assertEqual(read_xlsx(path)["S"][1][0], "valor < 10 & esperado > 5")


if __name__ == "__main__":
    unittest.main()
