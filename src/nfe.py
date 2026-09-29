"""XML de NF-e (modelo 55): leitura dos campos que a conferência fiscal usa."""
from __future__ import annotations

import xml.etree.ElementTree as ET

NFE_NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def read_nfe_xml(path: str) -> dict:
    """Extrai campos de um XML de NF-e. Levanta ValueError se o XML não tiver a estrutura mínima."""
    root = ET.parse(path).getroot()
    inf = root.find(".//nfe:infNFe", NFE_NS)
    if inf is None:
        raise ValueError(f"{path}: XML sem infNFe")
    key = (inf.get("Id") or "").removeprefix("NFe")
    if not key:
        raise ValueError(f"{path}: infNFe sem atributo Id (chave de acesso)")

    def text(tag_path: str, attribute: str | None = None) -> str:
        element = inf.find(tag_path, NFE_NS)
        if element is None:
            return ""
        return (element.get(attribute) if attribute else element.text) or ""

    items = []
    for det in inf.findall("nfe:det", NFE_NS):
        product = det.find("nfe:prod", NFE_NS)
        items.append({
            "item": det.get("nItem", ""),
            "cfop": (product.findtext("nfe:CFOP", default="", namespaces=NFE_NS) if product is not None else ""),
            "amount": (product.findtext("nfe:vProd", default="", namespaces=NFE_NS) if product is not None else ""),
            "description": (product.findtext("nfe:xProd", default="", namespaces=NFE_NS) if product is not None else ""),
        })

    return {
        "source": "xml",
        "document_number": text("nfe:ide/nfe:nNF"),
        "series": text("nfe:ide/nfe:serie"),
        "model": text("nfe:ide/nfe:mod"),
        "operation": text("nfe:ide/nfe:natOp"),
        "issued_at": text("nfe:ide/nfe:dhEmi")[:10],
        "emitter_cnpj": text("nfe:emit/nfe:CNPJ"),
        "emitter_name": text("nfe:emit/nfe:xNome"),
        "receiver_cnpj": text("nfe:dest/nfe:CNPJ"),
        "total": text("nfe:total/nfe:ICMSTot/nfe:vNF"),
        "due_date": text("nfe:cobr/nfe:dup/nfe:dVenc")[:10],
        "nfe_key": key,
        "items": items,
        "file": path,
    }
