"""
Chunk .doc/.docx files in the docs/ folder and ingest them into Cognitor.

Each chunk becomes a document with metadata:
  source_name: filename
  source_path: absolute path
  paragraph_num: paragraph number where the chunk starts (1-based)
  page_num: page number where the chunk starts (1-based, tracked via
    explicit page-break marks in the Word XML)
"""

import math
import struct
from pathlib import Path
from typing import Any

import olefile
from tiktoken import get_encoding
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from cognitor import Cognitor


COGNITOR_URL = "http://localhost:7530"
COLLECTION_NAME = "docx"
DOCS_FOLDER = Path("docs")

CHUNK_SIZE = 500 # tokens per chunk
OVERLAP_RATIO = 0.15 # 15% chunk overlap
OVERLAP_SIZE = math.ceil(CHUNK_SIZE * OVERLAP_RATIO)

ENCODING_NAME = "cl100k_base"  # tiktoken encoding


def _starts_new_page(para: Any) -> bool:
    """
    Return True if the paragraph carries a 'page break before' property.
    
    Args:
        para: a python-docx Paragraph object
    Returns:
        bool: True if the paragraph has a 'page break before' property, False otherwise.
    """
    pPr = para._element.find(qn("w:pPr"))
    if pPr is not None:
        pb = pPr.find(qn("w:pageBreakBefore"))
        if pb is not None:
            val = pb.get(qn("w:val"), "true")
            return val not in ("false", "0")
    return False


def _run_has_page_break(run: Any) -> bool:
    """
    Return True if a run contains an explicit <w:br w:type="page"/> element.

    Args:
        run: a python-docx Run object
    Returns:
        bool: True if the run contains a page break, False otherwise.
    """
    for br in run._element.findall(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            return True
    return False


def _extract_paragraphs_from_docx(path: Path) -> list[dict[str, Any]]:
    """
    Extract paragraphs from a .docx (OOXML) file via python-docx.
    Page numbers are tracked by counting explicit page-break marks in the XML.
    """
    doc: Any = DocxDocument(str(path))
    records: list[dict[str, Any]] = []
    page = 1
    para_idx = 0

    for para in doc.paragraphs:
        if _starts_new_page(para):
            page += 1

        text = para.text.strip()
        para_idx += 1

        if text:
            records.append({"text": text, "paragraph_num": para_idx, "page_num": page})

        for run in para.runs:
            if _run_has_page_break(run):
                page += 1

    return records


def _read_binary_doc_text(path: Path) -> str:
    """
    Extract the main-story text from a Word 97-2003 binary .doc file.

    Reads the OLE2 compound file, locates the CLX/piece-table in the table
    stream via the FIB, and reconstructs the text from each piece (ANSI
    CP-1252 or UTF-16-LE depending on the FcCompressed flag).

    Returns the raw text with Word special characters intact:
      \\r   (0x0D) = paragraph mark
      \\x07        = table-cell / table-row mark
      \\x0c        = explicit page / section break
      \\x0b        = soft line break
    """
    with olefile.OleFileIO(str(path)) as ole:
        if not ole.exists("WordDocument"):
            raise ValueError("Not a Word document: 'WordDocument' stream missing")

        wd = ole.openstream("WordDocument").read()

        # ── FibBase (32 bytes at offset 0) ────────────────────────────────────
        if len(wd) < 32:
            raise ValueError("WordDocument stream too short")
        wIdent = struct.unpack_from("<H", wd, 0)[0]
        if wIdent != 0xA5EC:
            raise ValueError(f"Unexpected FIB magic {wIdent:#06x} (expected 0xa5ec)")

        # flags at FibBase offset 10 — bit 9 = fWhichTblStm
        flags = struct.unpack_from("<H", wd, 10)[0]
        fWhichTblStm = bool(flags & 0x0200)

        # ── FibRgW (starts at 32) ──────────────────────────────────────────────
        csw = struct.unpack_from("<H", wd, 32)[0]

        # ── FibRgLw (starts at 32 + 2 + csw*2) ───────────────────────────────
        fibrglw = 32 + 2 + csw * 2
        cslw = struct.unpack_from("<H", wd, fibrglw)[0]
        # ccpText is index-3 LONG in FibRgLw data (offset 2 + 3×4 = 14)
        ccpText = struct.unpack_from("<I", wd, fibrglw + 14)[0]

        # ── FibRgFcLcb (starts after FibRgLw) ────────────────────────────────
        fibrgfclcb = fibrglw + 2 + cslw * 4
        # fcClx is entry index 33 (0-based) in FibRgFcLcb97
        # offset = 2 (cbFcLcb header) + 33 × 8
        fcclx_off = fibrgfclcb + 2 + 33 * 8
        fcClx = struct.unpack_from("<I", wd, fcclx_off)[0]
        lcbClx = struct.unpack_from("<I", wd, fcclx_off + 4)[0]
        if lcbClx == 0:
            raise ValueError("CLX structure missing")

        # ── Table stream ──────────────────────────────────────────────────────
        tbl_name = "1Table" if fWhichTblStm else "0Table"
        if not ole.exists(tbl_name):
            raise ValueError(f"Table stream {tbl_name!r} not found")
        tbl = ole.openstream(tbl_name).read()
        clx = tbl[fcClx : fcClx + lcbClx]

        # ── CLX → Pcdt ────────────────────────────────────────────────────────
        # CLX = zero-or-more RGPRLs (marker 0x01) + one Pcdt (marker 0x02)
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

        # ── PlcPcd → pieces ───────────────────────────────────────────────────
        # PlcPcd = (n+1) × CP[4] + n × PCD[8]  →  total = 12n + 4
        n = (len(plcPcd) - 4) // 12
        cps = [struct.unpack_from("<I", plcPcd, i * 4)[0] for i in range(n + 1)]
        pcd_base = (n + 1) * 4

        parts: list[str] = []
        for i in range(n):
            cp_s, cp_e = cps[i], cps[i + 1]
            if cp_s >= ccpText:
                break
            n_chars = min(cp_e, ccpText) - cp_s

            # PCD: fNoParaMark(2) + FcCompressed(4) + prm(2)
            fc_raw = struct.unpack_from("<I", plcPcd, pcd_base + i * 8 + 2)[0]
            fCompressed = bool(fc_raw & 0x40000000)  # bit 30
            fc = fc_raw & 0x3FFFFFFF

            if fCompressed:
                # ANSI CP-1252: byte_offset = fc // 2, 1 byte per char
                byte_off = fc >> 1
                parts.append(wd[byte_off : byte_off + n_chars].decode("cp1252", errors="replace"))
            else:
                # UTF-16-LE: byte_offset = fc, 2 bytes per char
                parts.append(wd[fc : fc + n_chars * 2].decode("utf-16-le", errors="replace"))

        return "".join(parts)


def _extract_paragraphs_from_binary_doc(path: Path) -> list[dict[str, Any]]:
    """
    Parse raw text from a binary .doc into paragraph records.

    Word special characters used as paragraph/page boundaries:
      \\r / \\x07  paragraph mark / table-cell mark  → ends a paragraph
      \\x0c        explicit page break               → ends a paragraph, advances page
      \\x0b        soft line break                   → becomes a space
    """
    raw = _read_binary_doc_text(path)

    records: list[dict[str, Any]] = []
    page = 1
    para_idx = 0
    current: list[str] = []

    for ch in raw:
        code = ord(ch)
        if ch == "\x0c":  # explicit page / section break
            para_idx += 1
            if current:
                text = "".join(current).strip()
                if text:
                    records.append({"text": text, "paragraph_num": para_idx, "page_num": page})
                current = []
            page += 1
        elif ch in ("\r", "\x07"):  # paragraph mark / table-cell mark
            para_idx += 1
            if current:
                text = "".join(current).strip()
                if text:
                    records.append({"text": text, "paragraph_num": para_idx, "page_num": page})
                current = []
        elif ch == "\x0b":  # soft line break → space
            current.append(" ")
        elif code in (0x13, 0x14, 0x15):  # field-code delimiters
            pass
        elif code >= 0x20 or ch == "\t":
            current.append(ch)

    if current:  # flush trailing paragraph with no terminating mark
        para_idx += 1
        text = "".join(current).strip()
        if text:
            records.append({"text": text, "paragraph_num": para_idx, "page_num": page})

    return records


def extract_paragraphs(path: Path) -> list[dict[str, Any]]:
    """
    Open a Word document and return paragraph records.

    Dispatches to the appropriate reader:
      .docx  → python-docx (OOXML / ZIP)
      .doc   → olefile    (Word 97-2003 binary OLE2)
    """
    if path.suffix.lower() == ".docx":
        return _extract_paragraphs_from_docx(path)
    return _extract_paragraphs_from_binary_doc(path)


def build_token_stream(
    paragraphs: list[dict[str, Any]],
    enc: Any,
) -> list[tuple[int, int, int]]:
    """
    Flatten paragraphs into a list of (token_id, paragraph_num, page_num).
    A single space is added between consecutive paragraphs.
    
    Args:
        paragraphs: list of dicts with keys 'text', 'paragraph_num', 'page_num'
        enc: a tiktoken encoding object
    Returns:
        list of tuples (token_id, paragraph_num, page_num)
    """
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
    """
    Slide a window of *chunk_size* tokens over *stream* advancing by
    ``chunk_size - overlap_size`` tokens each step.
    Each chunk carries the paragraph/page number of its **first** token.

    Args:
        stream: list of tuples (token_id, paragraph_num, page_num)
        chunk_size: number of tokens in each chunk
        overlap_size: number of tokens to overlap between chunks
        enc: a tiktoken encoding object
    Returns:
        list of dicts with keys 'text', 'paragraph_num', 'page_num'
    """
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


def ingest_file(
    client: Cognitor,
    collection: str,
    path: Path,
    chunk_size: int,
    overlap_size: int,
    enc: Any,
) -> None:
    """
    Ingest a single .doc/.docx file into the specified Cognitor collection.
    
    Args:
        client: Cognitor client instance
        collection: name of the Cognitor collection to ingest into
        path: Path to the .doc/.docx file
        chunk_size: number of tokens in each chunk
        overlap_size: number of tokens to overlap between chunks
        enc: a tiktoken encoding object
    """
    
    try:
        paragraphs = extract_paragraphs(path)
    except Exception as exc:
        print(f"  Skipped {path.name}: {exc}")
        return

    if not paragraphs:
        print(f"  Skipped {path.name}: no text found")
        return

    stream = build_token_stream(paragraphs, enc)
    chunks = make_chunks(stream, chunk_size, overlap_size, enc)

    texts = [c["text"] for c in chunks]
    metadatas = [
        {
            "source_name": path.name,
            "source_path": str(path.resolve()),
            "paragraph_num": c["paragraph_num"],
            "page_num": c["page_num"],
        }
        for c in chunks
    ]

    ids = client.bulk_add_documents(collection, texts, metadatas)
    print(f"  {path.name}: {len(ids)} chunk(s) ingested")


def main() -> None:
    enc: Any = get_encoding(ENCODING_NAME)

    doc_files = sorted(
        list(DOCS_FOLDER.glob("*.docx")) + list(DOCS_FOLDER.glob("*.doc"))
    )
    if not doc_files:
        print(f"No .doc/.docx files found in {DOCS_FOLDER}/")
        return

    print(
        f"Found {len(doc_files)} file(s)  |  "
        f"chunk_size={CHUNK_SIZE} tokens  |  overlap={OVERLAP_SIZE} tokens ({OVERLAP_RATIO:.0%})"
    )

    with Cognitor(COGNITOR_URL) as client:
        try:
            client.get_collection(COLLECTION_NAME)
            client.delete_collection(COLLECTION_NAME)
            print(f"Dropped existing collection '{COLLECTION_NAME}'")
        except Exception:
            pass
        client.create_collection(COLLECTION_NAME)
        print(f"Created collection '{COLLECTION_NAME}'")

        for path in doc_files:
            print(f"Processing {path.name} …")
            ingest_file(client, COLLECTION_NAME, path, CHUNK_SIZE, OVERLAP_SIZE, enc)

    print("Done.")


if __name__ == "__main__":
    main()
