"""Gera os fixtures sintéticos (XML de NF-e, DANFE em PDF e planilha do cliente).

Determinístico: mesma seed => mesmos arquivos, byte a byte. As divergências são injetadas de
forma declarada no dicionário DIVERGENCES, então o resultado do pipeline é previsível e testável.

Nada aqui vem de empresa, cliente ou documento real — os CNPJs são bases sintéticas com DV calculado.
"""
from __future__ import annotations

import argparse
import os
import random
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from src.pdf import write_pdf
from src.rules import cnpj_with_dv, nfe_key_digit
from src.xlsx import write_xlsx

NS = "http://www.portalfiscal.inf.br/nfe"
EMITTERS = [
    ("112223330001", "EMITENTE ALFA SERVICOS LTDA"),
    ("998887770001", "EMITENTE BETA COMERCIO LTDA"),
]
RECEIVER = cnpj_with_dv("123456780001")
OPERATIONS = ["VENDA", "SERVICO"]
CFOP_BY_OPERATION = {"VENDA": "5102", "SERVICO": "5933"}
INVALID_CFOP = {"VENDA": "5201"}

DIVERGENCES = {
    "spreadsheet_amount": {3, 17, 29},
    "spreadsheet_cnpj": {8},
    "spreadsheet_due_before_issue": {12},
    "spreadsheet_duplicate_row": {22},
    "spreadsheet_missing_document": {40, 41},
    "document_invalid_cnpj": {33},
    "document_total_mismatch": {44},
    "document_bad_cfop": {50},
    "document_bad_key": {55},
}
EXTRA_SPREADSHEET_ROWS = 2


def _key(cnpj: str, number: int, month: str = "2606", uf_code: str = "35") -> str:
    body = (f"{uf_code}{month}{cnpj}55" f"{1:03d}" f"{number:09d}" f"{1}" f"{random.randint(0, 99999999):08d}")
    assert len(body) == 43, len(body)
    return body + nfe_key_digit(body)


def _xml_document(cnpj: str, name: str, key: str, number: int, operation: str, cfop: str,
                  total: str, issued: str, due: str, items_total: str | None = None) -> ET.ElementTree:
    """`total` é o valor declarado no documento; `items_total` é a soma real dos itens (podem divergir
    de propósito nos fixtures — é o cenário clássico de erro de digitação no ERP)."""
    root = ET.Element(f"{{{NS}}}nfeProc")
    nfe = ET.SubElement(root, f"{{{NS}}}NFe")
    inf = ET.SubElement(nfe, f"{{{NS}}}infNFe", {"Id": f"NFe{key}", "versao": "4.00"})
    ide = ET.SubElement(inf, f"{{{NS}}}ide")
    ET.SubElement(ide, f"{{{NS}}}nNF").text = str(number)
    ET.SubElement(ide, f"{{{NS}}}serie").text = "1"
    ET.SubElement(ide, f"{{{NS}}}mod").text = "55"
    ET.SubElement(ide, f"{{{NS}}}natOp").text = operation
    ET.SubElement(ide, f"{{{NS}}}dhEmi").text = f"{issued}T10:00:00-03:00"
    emit = ET.SubElement(inf, f"{{{NS}}}emit")
    ET.SubElement(emit, f"{{{NS}}}CNPJ").text = cnpj
    ET.SubElement(emit, f"{{{NS}}}xNome").text = name
    dest = ET.SubElement(inf, f"{{{NS}}}dest")
    ET.SubElement(dest, f"{{{NS}}}CNPJ").text = RECEIVER
    det = ET.SubElement(inf, f"{{{NS}}}det", {"nItem": "1"})
    prod = ET.SubElement(det, f"{{{NS}}}prod")
    ET.SubElement(prod, f"{{{NS}}}CFOP").text = cfop
    ET.SubElement(prod, f"{{{NS}}}vProd").text = items_total if items_total is not None else total
    ET.SubElement(prod, f"{{{NS}}}xProd").text = "ITEM UNICO"
    total_node = ET.SubElement(inf, f"{{{NS}}}total")
    icms = ET.SubElement(total_node, f"{{{NS}}}ICMSTot")
    ET.SubElement(icms, f"{{{NS}}}vNF").text = total
    cobranca = ET.SubElement(inf, f"{{{NS}}}cobr")
    duplicata = ET.SubElement(cobranca, f"{{{NS}}}dup")
    ET.SubElement(duplicata, f"{{{NS}}}nDup").text = "001"
    ET.SubElement(duplicata, f"{{{NS}}}dVenc").text = due
    ET.SubElement(duplicata, f"{{{NS}}}vDup").text = total
    return ET.ElementTree(root)


def generate(seed: int = 42, count: int = 60, directory: str = "fixtures") -> dict:
    random.seed(seed)
    os.makedirs(directory, exist_ok=True)
    pdf_dir = os.path.join(directory, "pdf")
    xml_dir = os.path.join(directory, "xml")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(xml_dir, exist_ok=True)

    spreadsheet_rows = [["documento", "cnpj", "valor", "vencimento", "chave"]]
    documents: list[dict] = []

    for index in range(count):
        number = 1000 + index
        emitter_cnpj, emitter_name = EMITTERS[index % len(EMITTERS)]
        emitter_cnpj = cnpj_with_dv(emitter_cnpj)
        operation = OPERATIONS[index % len(OPERATIONS)]
        cfop = CFOP_BY_OPERATION[operation]
        key = _key(emitter_cnpj, number)
        total = f"{random.uniform(150.0, 9800.0):.2f}"
        issued = date(2026, 6, 1) + timedelta(days=index % 25)
        due = issued + timedelta(days=30)

        if index in DIVERGENCES["document_invalid_cnpj"]:
            emitter_cnpj = emitter_cnpj[:13] + ("0" if emitter_cnpj[13] != "0" else "1")
        if index in DIVERGENCES["document_bad_key"]:
            key = key[:43] + ("0" if key[43] != "0" else "1")
        if index in DIVERGENCES["document_bad_cfop"]:
            cfop = INVALID_CFOP[operation]
        total_in_file = total
        if index in DIVERGENCES["document_total_mismatch"]:
            total_in_file = f"{float(total) + 99.99:.2f}"  # total do documento != soma dos itens

        as_pdf = index % 4 == 3
        if as_pdf:
            path = os.path.join(pdf_dir, f"danfe_{number}.pdf")
            write_pdf(path, [
                "DANFE - DOCUMENTO AUXILIAR DE VENDA",
                f"RAZAO SOCIAL: {emitter_name}",
                f"CNPJ EMITENTE: {emitter_cnpj}",
                f"NATUREZA DA OPERACAO: {operation}",
                f"VALOR TOTAL: {total_in_file.replace('.', ',')}",
                f"DATA DE EMISSAO: {issued.isoformat()}",
                "CHAVE DE ACESSO:",
                key,
            ], title=f"danfe_{number}")
            document = {
                "source": "pdf", "file": path, "document_number": str(number), "series": "1", "model": "55",
                "operation": operation, "issued_at": issued.isoformat(), "due_date": due.isoformat(),
                "emitter_cnpj": emitter_cnpj, "emitter_name": emitter_name, "receiver_cnpj": RECEIVER,
                "total": total_in_file, "nfe_key": key,
                "items": [{"item": "1", "cfop": cfop, "amount": total, "description": "ITEM UNICO"}],
            }
        else:
            path = os.path.join(xml_dir, f"nfe_{number}.xml")
            tree = _xml_document(emitter_cnpj, emitter_name, key, number, operation, cfop,
                                 total_in_file, issued.isoformat(), due.isoformat(), items_total=total)
            ET.indent(tree, space="  ")
            tree.write(path, encoding="utf-8", xml_declaration=True)
            document = {
                "source": "xml", "file": path, "document_number": str(number), "series": "1", "model": "55",
                "operation": operation, "issued_at": issued.isoformat(), "due_date": due.isoformat(),
                "emitter_cnpj": emitter_cnpj, "emitter_name": emitter_name, "receiver_cnpj": RECEIVER,
                "total": total_in_file, "nfe_key": key,
                "items": [{"item": "1", "cfop": cfop, "amount": total, "description": "ITEM UNICO"}],
            }

        documents.append(document)

        if index in DIVERGENCES["spreadsheet_missing_document"]:
            continue
        row_total = total
        row_cnpj = emitter_cnpj
        row_due = due.isoformat()
        if index in DIVERGENCES["spreadsheet_amount"]:
            row_total = f"{float(total) + 15.55:.2f}"
        if index in DIVERGENCES["spreadsheet_cnpj"]:
            row_cnpj = cnpj_with_dv("445566770001")
        if index in DIVERGENCES["spreadsheet_due_before_issue"]:
            row_due = (issued - timedelta(days=1)).isoformat()
        spreadsheet_rows.append([str(number), row_cnpj, row_total, row_due, key])
        if index in DIVERGENCES["spreadsheet_duplicate_row"]:
            spreadsheet_rows.append([str(number), row_cnpj, row_total, row_due, key])

    for extra in range(EXTRA_SPREADSHEET_ROWS):
        number = 9000 + extra
        spreadsheet_rows.append([str(number), cnpj_with_dv("556677880001"), f"{random.uniform(100, 900):.2f}",
                                 "2026-07-15", _key(cnpj_with_dv("556677880001"), number)])

    spreadsheet_path = os.path.join(directory, "planilha_cliente.xlsx")
    write_xlsx(spreadsheet_path, {"Lancamentos": spreadsheet_rows})
    print(f"fixtures: {len(documents)} documentos ({sum(1 for d in documents if d['source'] == 'pdf')} em PDF, "
          f"{sum(1 for d in documents if d['source'] == 'xml')} em XML) + planilha com {len(spreadsheet_rows) - 1} linhas")
    return {"documents": documents, "spreadsheet_path": spreadsheet_path, "spreadsheet_rows": spreadsheet_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--out", default="fixtures")
    args = parser.parse_args()
    generate(args.seed, args.count, args.out)


if __name__ == "__main__":
    main()
