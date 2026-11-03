"""Pipeline completo: lê os documentos, aplica as regras, concilia com a planilha e mede.

Medição honesta, separando o que é medido do que é parâmetro:

- **medido**: tempo de processamento real do lote (relógio monotônico), documentos por segundo,
  taxa de aprovação automática e volume de cada tipo de divergência;
- **parâmetro declarado**: minutos de conferência manual por documento (`--manual-minutes`), usado
  apenas para estimar o ganho. A estimativa vem com faixa de sensibilidade de ±30%.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from src.make_fixtures import generate
from src.nfe import read_nfe_xml
from src.pdf import find_field, read_pdf
from src.reconcile import reconcile
from src.xlsx import read_xlsx, write_xlsx

PDF_FIELDS = {
    "document_number": r"N(?:UMERO|º|O)\s*:?\s*(\d+)",
    "emitter_cnpj": r"CNPJ EMITENTE:\s*([\d./-]+)",
    "operation": r"NATUREZA DA OPERACAO:\s*([A-Za-z_ ]+)",
    "total": r"VALOR TOTAL:\s*([\d.,]+)",
    "issued_at": r"DATA DE EMISSAO:\s*(\d{4}-\d{2}-\d{2})",
    "nfe_key": r"CHAVE DE ACESSO:\s*$",
}


def document_from_pdf(path: str, lines: list[str]) -> dict:
    """Lê um DANFE textual. A chave aparece na linha seguinte ao rótulo."""
    key = ""
    for index, line in enumerate(lines):
        if line.upper().startswith("CHAVE DE ACESSO") and index + 1 < len(lines):
            key = "".join(ch for ch in lines[index + 1] if ch.isdigit())
            break
    if not key:
        key = next(("".join(ch for ch in line if ch.isdigit()) for line in lines
                    if len("".join(ch for ch in line if ch.isdigit())) == 44), "")
    document = {
        "source": "pdf",
        "file": path,
        "document_number": find_field(lines, PDF_FIELDS["document_number"]) or (key[25:34].lstrip("0") if key else ""),
        "series": "1",
        "model": "55",
        "operation": find_field(lines, PDF_FIELDS["operation"]),
        "issued_at": find_field(lines, PDF_FIELDS["issued_at"]),
        "due_date": "",
        "emitter_cnpj": find_field(lines, PDF_FIELDS["emitter_cnpj"]),
        "receiver_cnpj": "",
        "total": find_field(lines, PDF_FIELDS["total"]).replace(".", "").replace(",", "."),
        "nfe_key": key,
        "items": [],
    }
    return document


def load_documents(fixtures_dir: str) -> list[dict]:
    documents: list[dict] = []
    xml_dir = os.path.join(fixtures_dir, "xml")
    pdf_dir = os.path.join(fixtures_dir, "pdf")
    for name in sorted(os.listdir(xml_dir)) if os.path.isdir(xml_dir) else []:
        if name.endswith(".xml"):
            documents.append(read_nfe_xml(os.path.join(xml_dir, name)))
    for name in sorted(os.listdir(pdf_dir)) if os.path.isdir(pdf_dir) else []:
        if name.endswith(".pdf"):
            path = os.path.join(pdf_dir, name)
            documents.append(document_from_pdf(path, read_pdf(path)))
    return documents


def spreadsheet_rows(path: str) -> list[dict]:
    """Lê a planilha do cliente traduzindo os nomes de coluna para o vocabulário interno.

    Planilha de cliente nunca vem com o nome de campo que a gente quer — o adaptador existe para
    que a conciliação não dependa do rótulo que a pessoa escolheu na planilha.
    """
    aliases = {
        "documento": "document_number", "numero": "document_number", "nº": "document_number", "nf": "document_number",
        "cnpj": "emitter_cnpj", "cnpj_emitente": "emitter_cnpj", "emitente": "emitter_cnpj",
        "valor": "total", "valor_total": "total", "total": "total",
        "vencimento": "due_date", "data_vencimento": "due_date",
        "chave": "nfe_key", "chave_acesso": "nfe_key", "nfe_key": "nfe_key",
    }
    sheets = read_xlsx(path)
    rows = list(sheets.values())[0]
    header = [str(cell).strip().lower().replace(" ", "_") for cell in rows[0]]
    parsed: list[dict] = []
    for row in rows[1:]:
        raw = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
        parsed.append({aliases.get(k, k): v for k, v in raw.items()})
    return parsed


def estimate_impact(documents: int, elapsed_seconds: float, manual_minutes: float, sensitivity: float = 0.3) -> dict:
    """Horas economizadas = (minutos manuais por documento - tempo automático por documento) × documentos."""
    automatic_minutes_per_document = (elapsed_seconds / documents) / 60 if documents else 0.0
    hours = {label: round((manual_minutes * factor - automatic_minutes_per_document) * documents / 60, 2)
             for label, factor in (("pessimistic", 1 - sensitivity), ("declared", 1.0), ("optimistic", 1 + sensitivity))}
    return {
        "documents": documents,
        "elapsed_seconds_measured": round(elapsed_seconds, 4),
        "seconds_per_document_measured": round(elapsed_seconds / documents, 4) if documents else 0.0,
        "documents_per_minute_measured": round(documents / (elapsed_seconds / 60), 1) if elapsed_seconds else 0.0,
        "manual_minutes_per_document_declared": manual_minutes,
        "hours_saved": hours,
        "formula": ("horas_economizadas = (minutos_manuais_declarados × fator − minutos_automaticos_medidos) "
                    "× documentos ÷ 60"),
        "note": "minutos manuais é PARÂMETRO DECLARADO (conferência fiscal doc a doc); o resto é medido em execução.",
    }


def run(fixtures_dir: str = "fixtures", output_dir: str = "output", seed: int = 42, count: int = 60,
        manual_minutes: float = 12.0, generate_fixtures: bool = True) -> dict:
    """Conferência de um lote.

    `generate_fixtures=True` cria o lote sintético antes de processar (modo demo/reprodutível).
    `generate_fixtures=False` processa o que já existe em `fixtures_dir`, sem escrever nada nele:
    é o modo de uso real, em que os documentos e a planilha vêm do cliente.
    """
    started = time.perf_counter()
    fixtures = generate(seed, count, fixtures_dir) if generate_fixtures else None
    documents = load_documents(fixtures_dir)
    spreadsheet_path = (fixtures["spreadsheet_path"] if fixtures
                        else os.path.join(fixtures_dir, "planilha_cliente.xlsx"))
    # caminhos vão para artefatos versionados: sempre com barra normal, senão o
    # resumo muda entre Windows e Linux e o gate de drift do CI quebra
    portable_spreadsheet = Path(spreadsheet_path).as_posix()
    portable_workbook = Path(output_dir, "conferencia_fiscal.xlsx").as_posix()
    if not os.path.exists(spreadsheet_path):
        raise FileNotFoundError(
            f"planilha do cliente não encontrada em {spreadsheet_path}; "
            "informe o diretório do lote com --fixtures ou gere o lote sintético com --generate"
        )
    rows = spreadsheet_rows(spreadsheet_path)
    reconciliation = reconcile(documents, rows)
    elapsed = time.perf_counter() - started

    impact = estimate_impact(len(documents), elapsed, manual_minutes)
    business = {
        "documents": len(documents),
        "manual_minutes_per_document_declared": manual_minutes,
        "manual_hours_for_the_batch": round(manual_minutes * len(documents) / 60, 2),
        "hours_saved": {"declared": impact["hours_saved"]["declared"],
                        "pessimistic": impact["hours_saved"]["pessimistic"],
                        "optimistic": impact["hours_saved"]["optimistic"]},
        "formula": impact["formula"],
        "note": impact["note"],
    }
    os.makedirs(output_dir, exist_ok=True)

    conference = [["documento", "origem", "cnpj_emitente", "chave_acesso", "valor_documento",
                   "valor_planilha", "vencimento", "status", "regras"]]
    divergences = [["documento", "status", "regra", "esperado", "encontrado"]]
    for item in reconciliation["results"]:
        conference.append([item["document_number"], item["source_kind"], item["emitter_cnpj"], item["key"],
                           item["total_document"], item["total_spreadsheet"], item["due_date"], item["status"],
                           "; ".join(rule["rule"] for rule in item["rules"])])
        for rule in item["rules"]:
            divergences.append([item["document_number"], item["status"], rule["rule"], rule["expected"], rule["found"]])

    summary_rows = [["indicador", "valor"]]
    summary_rows += [
        ["documentos no lote", reconciliation["documents"]],
        ["linhas na planilha do cliente", reconciliation["spreadsheet_rows"]],
        ["aprovados automaticamente", reconciliation["summary"].get("aprovado_automatico", 0)],
        ["taxa de aprovação automática", f"{reconciliation['automation_rate']:.1%}"],
        ["itens em revisão humana", reconciliation["review_words"]],
        ["conferência manual do lote (parâmetro)", f"{business['manual_hours_for_the_batch']} h"],
        ["horas economizadas no lote (declarado)", impact["hours_saved"]["declared"]],
        ["faixa (pessimista–otimista)", f"{impact['hours_saved']['pessimistic']}–{impact['hours_saved']['optimistic']}"],
        ["reproduzível", "sim — mesma seed gera planilha byte a byte idêntica (sem relógio no artefato)"],
    ]
    for status, count_value in sorted(reconciliation["summary"].items()):
        summary_rows.append([f"status: {status}", count_value])

    workbook = os.path.join(output_dir, "conferencia_fiscal.xlsx")
    write_xlsx(workbook, {
        "Conferência": conference,
        "Divergências": divergences,
        "Resumo": summary_rows,
    })

    result = {
        "fixtures": {"seed": seed, "count": count, "generated": fixtures is not None,
                     "spreadsheet": portable_spreadsheet},
        "reconciliation": {k: v for k, v in reconciliation.items() if k != "results"},
        "impact": business,
        "workbook": portable_workbook,
    }
    summary_path = os.path.join(output_dir, "resumo.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    # desempenho é medição de execução: muda a cada run, então NÃO entra no entregável versionado
    performance = {**impact, "workbook_sha256": __import__("hashlib").sha256(open(workbook, "rb").read()).hexdigest()}
    with open(os.path.join(output_dir, "desempenho.json"), "w", encoding="utf-8") as fh:
        json.dump(performance, fh, ensure_ascii=False, indent=2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", default="fixtures")
    parser.add_argument("--out", default="output")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--manual-minutes", type=float, default=12.0,
                        help="minutos de conferência manual por documento (parâmetro declarado)")
    parser.add_argument("--no-generate", action="store_true",
                        help="processa o lote que já está em --fixtures, sem gerar dados sintéticos")
    args = parser.parse_args()
    result = run(args.fixtures, args.out, args.seed, args.count, args.manual_minutes,
                 generate_fixtures=not args.no_generate)
    recon = result["reconciliation"]
    impact = result["impact"]
    performance = json.load(open(os.path.join(args.out, "desempenho.json"), encoding="utf-8"))
    print(f"lote: {recon['documents']} documentos x {recon['spreadsheet_rows']} linhas da planilha | "
          f"aprovados automaticamente {recon['automation_rate']:.0%} | em revisão {recon['review_words']}")
    for status, count_value in sorted(recon["summary"].items(), key=lambda item: -item[1]):
        print(f"   {status:<24}{count_value}")
    print(f"medido: {performance['elapsed_seconds_measured']}s no lote "
          f"({performance['documents_per_minute_measured']} doc/min) — vai para output/desempenho.json, não para o entregável")
    print(f"estimado (parâmetro declarado {impact['manual_minutes_per_document_declared']} min/doc = "
          f"{impact['manual_hours_for_the_batch']}h de conferência manual): economia de {impact['hours_saved']['declared']}h "
          f"(faixa {impact['hours_saved']['pessimistic']}–{impact['hours_saved']['optimistic']}h)")
    print(f"planilha de conferência: {result['workbook']}")


if __name__ == "__main__":
    main()
