import logging
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from bs4 import Tag

from chunking import build_chunks_from_paragraphs


logger = logging.getLogger(__name__)


_NOISE_CONTAINERS = {
    "nav",
    "header",
    "footer",
    "aside",
    "form",
}


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_title(soup: BeautifulSoup) -> str:
    title = soup.title.string if soup.title and soup.title.string else ""
    return _normalize_whitespace(title)


def _is_inside_noise_container(element: Tag) -> bool:
    return any(parent.name in _NOISE_CONTAINERS for parent in element.parents if isinstance(parent, Tag))


def extract_paragraphs_from_html(path: Path) -> list[dict[str, Any]]:
    """
    Extract readable, semantic text blocks from an HTML file.

    Raw HTML, classes, styling and scripts are intentionally discarded.
    """

    raw_text = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw_text, "html.parser")

    for tag_name in ("script", "style", "noscript", "template", "svg", "canvas", "iframe"):
        for node in soup.find_all(tag_name):
            node.decompose()

    root = soup.find("main") or soup.body or soup
    page_title = _extract_title(soup)

    records: list[dict[str, Any]] = []
    para_idx = 0
    heading_stack: dict[int, str] = {}

    selectors = "h1, h2, h3, h4, h5, h6, p, li, blockquote, td, th, figcaption"
    for element in root.select(selectors):
        if _is_inside_noise_container(element):
            continue

        block_text = _normalize_whitespace(" ".join(element.stripped_strings))
        if not block_text:
            continue

        if element.name and element.name.startswith("h") and len(element.name) == 2 and element.name[1].isdigit():
            level = int(element.name[1])
            heading_stack[level] = block_text
            for stale_level in [k for k in list(heading_stack.keys()) if k > level]:
                heading_stack.pop(stale_level, None)

        section_path = " > ".join(heading_stack[level] for level in sorted(heading_stack))

        parts: list[str] = []
        if page_title:
            parts.append(f"Title: {page_title}.")
        if section_path:
            parts.append(f"Section: {section_path}.")
        parts.append(block_text)

        para_idx += 1
        records.append(
            {
                "text": " ".join(parts),
                "paragraph_num": para_idx,
                "page_num": 1,
            }
        )

    return records


def extract_paragraphs(path: Path) -> list[dict[str, Any]]:
    """
    Extract semantic paragraphs from an HTML file.
    """

    return extract_paragraphs_from_html(path)


def build_html_chunks(
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
    Build text chunks from an HTML file.
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
    Ingest an .html/.htm file into the target collection.
    """

    try:
        chunks = build_html_chunks(
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