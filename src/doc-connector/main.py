"""
Utilities for parsing .doc/.docx files and producing chunk payloads.

This module intentionally contains no daemon/worker orchestration logic.
"""

import math
import struct
from pathlib import Path
from typing import Any

import olefile
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from tiktoken import get_encoding


CHUNK_SIZE = 500  # tokens per chunk
OVERLAP_RATIO = 0.15  # 15% chunk overlap
OVERLAP_SIZE = math.ceil(CHUNK_SIZE * OVERLAP_RATIO)
ENCODING_NAME = "cl100k_base"


def starts_new_page(para: Any) -> bool:
    pPr = para._element.find(qn("w:pPr"))
    if pPr is not None:
        pb = pPr.find(qn("w:pageBreakBefore"))
        if pb is not None:
            val = pb.get(qn("w:val"), "true")
            return val not in ("false", "0")
    return False


def run_has_page_break(run: Any) -> bool:
    for br in run._element.findall(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            return True
    return False


def extract_paragraphs_from_docx(path: Path) -> list[dict[str, Any]]:
    doc: Any = DocxDocument(str(path))
    records: list[dict[str, Any]] = []
    page = 1
    para_idx = 0

    for para in doc.paragraphs:
        if starts_new_page(para):
            page += 1

        text = para.text.strip()
        para_idx += 1

        if text:
            records.append({"text": text, "paragraph_num": para_idx, "page_num": page})

        for run in para.runs:
            if run_has_page_break(run):
                page += 1

    return records


def read_binary_doc_text(path: Path) -> str:
    with olefile.OleFileIO(str(path)) as ole:
        if not ole.exists("WordDocument"):
            raise ValueError("Not a Word document: 'WordDocument' stream missing")

        wd = ole.openstream("WordDocument").read()

        if len(wd) < 32:
            raise ValueError("WordDocument stream too short")
        wIdent = struct.unpack_from("<H", wd, 0)[0]
        if wIdent != 0xA5EC:
            raise ValueError(f"Unexpected FIB magic {wIdent:#06x} (expected 0xa5ec)")

        flags = struct.unpack_from("<H", wd, 10)[0]
        fWhichTblStm = bool(flags & 0x0200)

        csw = struct.unpack_from("<H", wd, 32)[0]
        fibrglw = 32 + 2 + csw * 2
        cslw = struct.unpack_from("<H", wd, fibrglw)[0]
        ccpText = struct.unpack_from("<I", wd, fibrglw + 14)[0]

        fibrgfclcb = fibrglw + 2 + cslw * 4
        fcclx_off = fibrgfclcb + 2 + 33 * 8
        fcClx = struct.unpack_from("<I", wd, fcclx_off)[0]
        lcbClx = struct.unpack_from("<I", wd, fcclx_off + 4)[0]
        if lcbClx == 0:
            raise ValueError("CLX structure missing")

        tbl_name = "1Table" if fWhichTblStm else "0Table"
        if not ole.exists(tbl_name):
            raise ValueError(f"Table stream {tbl_name!r} not found")
        tbl = ole.openstream(tbl_name).read()
        clx = tbl[fcClx : fcClx + lcbClx]

        pos = 0
        while pos < len(clx) and clx[pos] == 0x01:
            rg_len = struct.unpack_from("<H", clx, pos + 1)[0]
            pos += 3 + rg_len
        if pos >= len(clx) or clx[pos] != 0x02:
            raise ValueError("CLX: Pcdt marker (0x02) not found")
        pos += 1

        plcPcd_len = struct.unpack_from("<I", clx, pos)[0]
        pos += 4
        plcPcd = clx[pos : pos + plcPcd_len]

        n = (len(plcPcd) - 4) // 12
        cps = [struct.unpack_from("<I", plcPcd, i * 4)[0] for i in range(n + 1)]
        pcd_base = (n + 1) * 4

        parts: list[str] = []
        for i in range(n):
            cp_s, cp_e = cps[i], cps[i + 1]
            if cp_s >= ccpText:
                break
            n_chars = min(cp_e, ccpText) - cp_s

            fc_raw = struct.unpack_from("<I", plcPcd, pcd_base + i * 8 + 2)[0]
            fCompressed = bool(fc_raw & 0x40000000)
            fc = fc_raw & 0x3FFFFFFF

            if fCompressed:
                byte_off = fc >> 1
                parts.append(wd[byte_off : byte_off + n_chars].decode("cp1252", errors="replace"))
            else:
                parts.append(wd[fc : fc + n_chars * 2].decode("utf-16-le", errors="replace"))

        return "".join(parts)


def extract_paragraphs_from_binary_doc(path: Path) -> list[dict[str, Any]]:
    raw = read_binary_doc_text(path)

    records: list[dict[str, Any]] = []
    page = 1
    para_idx = 0
    current: list[str] = []

    for ch in raw:
        code = ord(ch)
        if ch == "\x0c":
            para_idx += 1
            if current:
                text = "".join(current).strip()
                if text:
                    records.append({"text": text, "paragraph_num": para_idx, "page_num": page})
                current = []
            page += 1
        elif ch in ("\r", "\x07"):
            para_idx += 1
            if current:
                text = "".join(current).strip()
                if text:
                    records.append({"text": text, "paragraph_num": para_idx, "page_num": page})
                current = []
        elif ch == "\x0b":
            current.append(" ")
        elif code in (0x13, 0x14, 0x15):
            pass
        elif code >= 0x20 or ch == "\t":
            current.append(ch)

    if current:
        para_idx += 1
        text = "".join(current).strip()
        if text:
            records.append({"text": text, "paragraph_num": para_idx, "page_num": page})

    return records


def extract_paragraphs(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".docx":
        return extract_paragraphs_from_docx(path)
    return extract_paragraphs_from_binary_doc(path)


def build_token_stream(paragraphs: list[dict[str, Any]], enc: Any) -> list[tuple[int, int, int]]:
    stream: list[tuple[int, int, int]] = []
    space_tokens = enc.encode(" ")

    for p in paragraphs:
        for tok in enc.encode(p["text"]):
            stream.append((tok, p["paragraph_num"], p["page_num"]))
        for tok in space_tokens:
            stream.append((tok, p["paragraph_num"], p["page_num"]))

    return stream


def make_chunks(
    stream: list[tuple[int, int, int]],
    chunk_size: int,
    overlap_size: int,
    enc: Any,
) -> list[dict[str, Any]]:
    step = chunk_size - overlap_size
    chunks: list[dict[str, Any]] = []
    total = len(stream)
    start = 0

    while start < total:
        end = min(start + chunk_size, total)
        window = stream[start:end]
        text = enc.decode([t[0] for t in window])
        chunks.append(
            {
                "text": text,
                "paragraph_num": window[0][1],
                "page_num": window[0][2],
            }
        )
        if end == total:
            break
        start += step

    return chunks


def build_doc_chunks(
    path: Path,
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap_size: int = OVERLAP_SIZE,
    encoding_name: str = ENCODING_NAME,
) -> list[dict[str, Any]]:
    paragraphs = extract_paragraphs(path)
    if not paragraphs:
        return []

    enc = get_encoding(encoding_name)
    stream = build_token_stream(paragraphs, enc)
    return make_chunks(stream, chunk_size, overlap_size, enc)
