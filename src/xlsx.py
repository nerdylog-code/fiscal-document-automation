"""Ler e escrever XLSX sem dependência externa (zipfile + XML da biblioteca padrão).

Por que não openpyxl: o núcleo deste repositório roda em qualquer Python 3.11+ (máquina de usuário
final, sem pip/rede) e o único artefato que precisamos é uma planilha de conferência simples.
Escrita determinística: o zip usa data fixa, então o arquivo é byte a byte igual a cada execução.
"""
from __future__ import annotations

import re
import zipfile
from xml.sax.saxutils import escape

FIXED_DATE = (2026, 1, 1, 0, 0, 0)

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{sheets}</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf/><xf fontId="1" applyFont="1"/></cellXfs></styleSheet>"""


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def column_index(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + (ord(char.upper()) - 64)
    return value - 1


def _cell(ref: str, value: object, bold: bool = False) -> str:
    style = ' s="1"' if bold else ""
    if value is None or value == "":
        return f'<c r="{ref}"{style}/>'
    if isinstance(value, bool):
        return f'<c r="{ref}"{style} t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'
    return f'<c r="{ref}"{style} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def write_xlsx(path: str, sheets: dict[str, list[list]]) -> str:
    """Escreve as abas na ordem informada. Primeira linha de cada aba vira cabeçalho em negrito."""
    names = list(sheets)
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(names) + 1)
    )
    sheet_tags = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{sheet_tags}</sheets></workbook>'
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(names) + 1)
    ) + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'

    import os

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        def add(name: str, content: str) -> None:
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content)

        add("[Content_Types].xml", CONTENT_TYPES.format(sheets=overrides))
        add("_rels/.rels", ROOT_RELS)
        add("xl/workbook.xml", workbook)
        add("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rels + "</Relationships>")
        add("xl/styles.xml", STYLES)
        for i, name in enumerate(names, start=1):
            rows_xml = []
            for row_number, row in enumerate(sheets[name], start=1):
                cells = "".join(_cell(f"{column_letter(col)}{row_number}", value, bold=(row_number == 1))
                                for col, value in enumerate(row))
                rows_xml.append(f'<row r="{row_number}">{cells}</row>')
            add(f"xl/worksheets/sheet{i}.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(rows_xml)}</sheetData></worksheet>')
    return path


def read_xlsx(path: str) -> dict[str, list[list]]:
    """Lê todas as abas: {nome: [linhas]} — células viram str/float conforme o tipo."""
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = re.findall(r"<si>(.*?)</si>", zf.read("xl/sharedStrings.xml").decode("utf-8"), re.S)
        workbook = zf.read("xl/workbook.xml").decode("utf-8")
        names = re.findall(r'<sheet name="([^"]+)"[^>]*r:id="rId(\d+)"', workbook)
        rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        targets = dict(re.findall(r'Id="rId(\d+)"[^>]*Target="([^"]+)"', rels))
        sheets: dict[str, list[list]] = {}
        for name, rel_id in names:
            target = targets.get(rel_id, f"worksheets/sheet{rel_id}.xml").lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            if target not in zf.namelist():
                continue
            xml = zf.read(target).decode("utf-8")
            rows: list[list] = []
            cell_pattern = re.compile(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", re.S)
            for row_xml in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
                values: list = []
                for cell in cell_pattern.finditer(row_xml):
                    attrs, body = cell.group(1), cell.group(2) or ""
                    ref_match = re.search(r'r="([A-Z]+)\d+"', attrs)
                    if not ref_match:
                        continue
                    index = column_index(ref_match.group(1))
                    while len(values) < index:
                        values.append("")
                    kind_match = re.search(r't="([^"]*)"', attrs)
                    kind = kind_match.group(1) if kind_match else "n"
                    if kind == "inlineStr":
                        text = re.findall(r"<t[^>]*>(.*?)</t>", body, re.S)
                        values.append(_unescape(text[0]) if text else "")
                    elif kind == "s":
                        position = re.findall(r"<v>(\d+)</v>", body)
                        values.append(shared[int(position[0])] if position else "")
                    elif kind == "b":
                        values.append(bool(re.findall(r"<v>(\d+)</v>", body)[0] == "1"))
                    else:
                        number = re.findall(r"<v>([^<]+)</v>", body)
                        if not number:
                            values.append("")
                        else:
                            try:
                                values.append(float(number[0]))
                            except ValueError:
                                values.append(number[0])
                rows.append(values)
            sheets[name] = rows
        return sheets


def _unescape(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
                .replace("&apos;", "'").replace("&amp;", "&"))
