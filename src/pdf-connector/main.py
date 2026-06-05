import logging
import re
from pathlib import Path
from typing import Any, Optional

from pypdf import PdfReader

from utils.chunking import DocumentChunker


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


class PDFIngestionService:
    def __init__(
        self,
        chunker: Optional[DocumentChunker] = None,
        *,
        chunk_size: int = 500,
        overlap_ratio: float = 0.15,
        encoding_name: str = "cl100k_base",
        overlap_size: Optional[int] = None,
    ) -> None:
        self.chunker = chunker or DocumentChunker(
            chunk_size=chunk_size,
            overlap_size=overlap_size,
            encoding_name=encoding_name,
            overlap_ratio=overlap_ratio,
        )

    def build_pdf_chunks(self, path: Path) -> list[dict[str, Any]]:
        paragraphs = extract_paragraphs(path)
        if not paragraphs:
            return []

        return self.chunker.chunk_paragraphs(paragraphs)

    def ingest_file(
        self,
        client: Any,
        collection: str,
        path: Path,
        file_signature: str,
    ) -> int:
        try:
            chunks = self.build_pdf_chunks(path)
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

        ids = client.bulk_add_documents(collection, texts, metadatas)
        logger.info("%s: %s chunk(s) ingested", path.name, len(ids))
        return len(ids)


def build_pdf_chunks(
    path: Path,
    *,
    chunk_size: int = 500,
    overlap_size: int = 75,
    encoding_name: str = "cl100k_base",
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

    service = PDFIngestionService(
        DocumentChunker(
            chunk_size=chunk_size,
            overlap_ratio=overlap_size / chunk_size,
            overlap_size=overlap_size,
            encoding_name=encoding_name,
        )
    )
    return service.build_pdf_chunks(path)