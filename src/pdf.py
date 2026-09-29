"""PDF textual: escrita mínima (abre em leitor comum) e extração de texto — sem dependência.

Escopo declarado: PDFs **textuais** (texto no fluxo de conteúdo, como os gerados aqui e como boa parte
dos relatórios emitidos por ERP). PDF escaneado exige OCR e está fora do escopo — assim como layouts
exóticos, que pedem uma biblioteca de verdade (a função `read_pdf` é o único ponto a trocar).
"""
from __future__ import annotations

import re
import zlib

PAGE_WIDTH = 595
PAGE_HEIGHT = 842


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(path: str, lines: list[str], title: str = "documento") -> str:
    """Escreve um PDF 1.4 de uma página, com xref/trailer válidos."""
    content_lines = ["BT", "/F1 9 Tf"]
    y = PAGE_HEIGHT - 60
    for line in lines:
        content_lines.append(f"1 0 0 1 40 {y} Tm")
        content_lines.append(f"({_escape(line)}) Tj")
        y -= 12
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", "replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
        f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>".encode()
    )
    objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    buffer = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(buffer))
        buffer += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(buffer)
    buffer += f"xref\n0 {len(objects) + 1}\n".encode()
    buffer += b"0000000000 65535 f \n"
    for offset in offsets:
        buffer += f"{offset:010d} 00000 n \n".encode()
    buffer += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info << /Title ({_escape(title)}) >> >>\n"
               f"startxref\n{xref_offset}\n%%EOF\n").encode()

    import os

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(bytes(buffer))
    return path


def _decode_streams(data: bytes) -> list[bytes]:
    streams: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = match.group(1)
        header = data[max(0, match.start() - 200):match.start()]
        if b"FlateDecode" in header:
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                continue
        streams.append(raw)
    return streams


def _unescape_pdf(text: str) -> str:
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            mapping = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
                       "(": "(", ")": ")", "\\": "\\"}
            if nxt in mapping:
                out.append(mapping[nxt])
                index += 2
                continue
            octal = re.match(r"[0-7]{1,3}", text[index + 1:])
            if octal:
                out.append(chr(int(octal.group(0), 8)))
                index += 1 + len(octal.group(0))
                continue
        out.append(char)
        index += 1
    return "".join(out)


def read_pdf(path: str) -> list[str]:
    """Devolve as linhas de texto do PDF, agrupadas pela coordenada vertical (como um leitor faz)."""
    data = open(path, "rb").read()
    lines: list[tuple[float, list[str]]] = []
    for stream in _decode_streams(data):
        text = stream.decode("latin-1", "replace")
        current_y: float | None = None
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                lines.append((current_y if current_y is not None else 0.0, list(buffer)))
                buffer.clear()

        pattern = re.compile(
            r"([-\d.]+) ([-\d.]+) (?:Td|TD)|1 0 0 1 ([-\d.]+) ([-\d.]+) Tm|"
            r"\(((?:[^()\\]|\\.)*)\)\s*Tj|\[((?:[^\[\]]|\\.)*)\]\s*TJ",
        )
        for match in pattern.finditer(text):
            text_delta_x, text_delta_y, matrix_x, matrix_y, single, array = match.groups()
            if text_delta_x is not None:
                flush()
                current_y = float(text_delta_y)
            elif matrix_y is not None:
                flush()
                current_y = float(matrix_y)
            elif single is not None:
                buffer.append(_unescape_pdf(single))
            elif array is not None:
                parts = re.findall(r"\(((?:[^()\\]|\\.)*)\)", array)
                buffer.append("".join(_unescape_pdf(p) for p in parts))
        flush()
    ordered = sorted(lines, key=lambda item: -item[0])
    return [re.sub(r"\s+", " ", "".join(parts)).strip() for _, parts in ordered if "".join(parts).strip()]


def find_field(lines: list[str], pattern: str) -> str:
    """Primeiro valor capturado pelo grupo 1 do padrão, varrendo as linhas do documento."""
    for line in lines:
        match = re.search(pattern, line, re.I)
        if match:
            return match.group(1).strip()
    return ""
