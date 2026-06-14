import logging
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from chunking import build_chunks_from_paragraphs
from utils import batch_ingest_documents


logger = logging.getLogger(__name__)


def extract_paragraphs_from_pdf(path: Path) -> list[dict[str, Any]]:
    """
    Extract text from a PDF file, returning page-scoped paragraph records.

    Args:
        path: Path to the PDF file.
    Returns:
        A list of dictionaries, each containing the text, paragraph number, and page number of a
        paragraph-like text block.
    """

    reader = PdfReader(str(path))
    records: list[dict[str, Any]] = []
    para_idx = 0

    for page_num, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized_text:
            continue

        blocks = re.split(r"\n\s*\n+", normalized_text)
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            text = " ".join(lines).strip()
            text = re.sub(r"\s+", " ", text)
            if not text:
                continue

            para_idx += 1
            records.append({"text": text, "paragraph_num": para_idx, "page_num": page_num})

    return records


def extract_paragraphs(path: Path) -> list[dict[str, Any]]:
    """
    Extract paragraphs from a PDF file.

    Args:
        path: Path to the PDF file.
    Returns:
        A list of dictionaries, each containing the text, paragraph number, and page number of a
        paragraph-like text block.
    """

    return extract_paragraphs_from_pdf(path)


def build_pdf_chunks(
    path: Path,
    *,
    chunker_type: str = "semantic",
    chunk_size: int = 500,
    overlap_size: int = 75,
    encoding_name: str = "cl100k_base",
    semantic_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    semantic_breakpoint_percentile: int = 70,
    semantic_repair_sentence_boundaries: bool = True,
) -> list[dict[str, Any]]:
    """
    Build text chunks from a PDF file.

    Args:
        path: Path to the PDF file.
        chunk_size: The maximum number of tokens in a chunk.
        overlap_size: The number of tokens to overlap between consecutive chunks.
        encoding_name: The name of the encoding to use from tiktoken.
    Returns:
        A list of dictionaries, each containing the text, paragraph number, and page number of a
        chunk.
    """

    paragraphs = extract_paragraphs(path)
    if not paragraphs:
        return []

    return build_chunks_from_paragraphs(
        paragraphs,
        chunker_type=chunker_type,
        chunk_size=chunk_size,
        overlap_size=overlap_size,
        encoding_name=encoding_name,
        semantic_model_name=semantic_model_name,
        semantic_breakpoint_percentile=semantic_breakpoint_percentile,
        semantic_repair_sentence_boundaries=semantic_repair_sentence_boundaries,
    )


def ingest_file(
    client: Any,
    collection: str,
    path: Path,
    file_signature: str,
    *,
    chunker_type: str = "semantic",
    chunk_size: int = 500,
    overlap_size: int = 75,
    encoding_name: str = "cl100k_base",
    semantic_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    semantic_breakpoint_percentile: int = 70,
    semantic_repair_sentence_boundaries: bool = True,
) -> int:
    """
    Ingest a .pdf file into the target collection.
    """

    try:
        chunks = build_pdf_chunks(
            path,
            chunker_type=chunker_type,
            chunk_size=chunk_size,
            overlap_size=overlap_size,
            encoding_name=encoding_name,
            semantic_model_name=semantic_model_name,
            semantic_breakpoint_percentile=semantic_breakpoint_percentile,
            semantic_repair_sentence_boundaries=semantic_repair_sentence_boundaries,
        )
    except Exception as exc:
        logger.warning("Skipped %s: %s", path.name, exc)
        return 0

    if not chunks:
        logger.info("Skipped %s: no text found", path.name)
        return 0

    texts = [chunk["text"] for chunk in chunks]
    metadatas = [
        {
            "source_name": path.name,
            "source_path": str(path.resolve()),
            "paragraph_num": chunk["paragraph_num"],
            "page_num": chunk["page_num"],
            "file_signature": file_signature,
        }
        for chunk in chunks
    ]

    return batch_ingest_documents(client, collection, texts, metadatas, path.name)