import logging
import re
from pathlib import Path
from typing import Any

from chunking import build_chunks_from_paragraphs


logger = logging.getLogger(__name__)


def extract_paragraphs_from_log(path: Path) -> list[dict[str, Any]]:
    """
    Extract paragraphs from a log file.

    The log file format is expected to be:
    timestamp | [level] | message

    Each line is treated as a separate log entry paragraph.

    Args:
        path: Path to the log file.
    Returns:
        A list of dictionaries, each containing the text, paragraph number, and page number of a
        log entry.
    """

    raw_text = path.read_text(encoding="utf-8", errors="replace")
    lines = raw_text.strip().split("\n")

    records: list[dict[str, Any]] = []
    para_idx = 0

    for line in lines:
        # Skip empty lines
        line = line.strip()
        if not line:
            continue

        # Extract log components
        # Format: timestamp | [level] | message
        match = re.match(r"^(.+?)\s*\|\s*\[(.+?)\]\s*\|\s*(.+)$", line)
        if match:
            timestamp, level, message = match.groups()
            # Combine all parts into a single searchable text
            text = f"{timestamp} [{level}] {message}".strip()
        else:
            # If line doesn't match the standard format, use it as-is
            text = line

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text)

        if text:
            para_idx += 1
            records.append({"text": text, "paragraph_num": para_idx, "page_num": 1})

    return records


def extract_paragraphs(path: Path) -> list[dict[str, Any]]:
    """
    Extract paragraphs from a log file.

    Args:
        path: Path to the log file.
    Returns:
        A list of dictionaries, each containing the text, paragraph number, and page number of a
        log entry.
    """

    return extract_paragraphs_from_log(path)


def build_log_chunks(
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
    Build text chunks from a log file.

    Args:
        path: Path to the log file.
        chunker_type: The type of chunker to use ("semantic" or "simple").
        chunk_size: The maximum number of tokens in a chunk.
        overlap_size: The number of tokens to overlap between consecutive chunks.
        encoding_name: The encoding name for tokenization.
        semantic_model_name: The model name for semantic chunking.
        semantic_breakpoint_percentile: The breakpoint percentile for semantic chunking.
        semantic_repair_sentence_boundaries: Whether to repair sentence boundaries in semantic chunking.
    Returns:
        A list of dictionaries, each containing the chunk text and metadata.
    """

    paragraphs = extract_paragraphs(path)
    chunks = build_chunks_from_paragraphs(
        paragraphs,
        chunker_type=chunker_type,
        chunk_size=chunk_size,
        overlap_size=overlap_size,
        encoding_name=encoding_name,
        semantic_model_name=semantic_model_name,
        semantic_breakpoint_percentile=semantic_breakpoint_percentile,
        semantic_repair_sentence_boundaries=semantic_repair_sentence_boundaries,
    )
    return chunks


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
    Ingest a log file into the target collection.
    """

    try:
        chunks = build_log_chunks(
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

    ids = client.bulk_add_documents(collection, texts, metadatas)
    logger.info("%s: %s chunk(s) ingested", path.name, len(ids))
    return len(ids)
