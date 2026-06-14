import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import extract_msg
from bs4 import BeautifulSoup

from chunking import build_chunks_from_paragraphs
from utils import batch_ingest_documents


logger = logging.getLogger(__name__)


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _strip_invisible_characters(value: str) -> str:
    characters: list[str] = []
    for character in value:
        if character in {"\n", "\r", "\t"}:
            characters.append(character)
            continue
        category = unicodedata.category(character)
        if category not in {"Cc", "Cf"}:
            characters.append(character)
    return "".join(characters)


def _normalize_message_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_invisible_characters(text)
    return text


def _extract_html_text(html_body: str) -> str:
    soup = BeautifulSoup(html_body, "html.parser")
    return soup.get_text("\n", strip=True)


def _stringify_message_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _extract_attachment_names(message: extract_msg.Message) -> list[str]:
    names: list[str] = []
    for attachment in message.attachments:
        name = (
            getattr(attachment, "longFilename", None)
            or getattr(attachment, "shortFilename", None)
            or getattr(attachment, "filename", None)
        )
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _build_header_block(message: extract_msg.Message, attachment_names: list[str]) -> str:
    lines: list[str] = []

    subject = _stringify_message_field(getattr(message, "subject", None))
    sender = _stringify_message_field(getattr(message, "sender", None))
    recipients = _stringify_message_field(getattr(message, "to", None))
    copied = _stringify_message_field(getattr(message, "cc", None))
    blind_copied = _stringify_message_field(getattr(message, "bcc", None))
    sent_at = _stringify_message_field(getattr(message, "date", None))

    if subject:
        lines.append(f"Subject: {subject}")
    if sender:
        lines.append(f"From: {sender}")
    if recipients:
        lines.append(f"To: {recipients}")
    if copied:
        lines.append(f"Cc: {copied}")
    if blind_copied:
        lines.append(f"Bcc: {blind_copied}")
    if sent_at:
        lines.append(f"Date: {sent_at}")
    if attachment_names:
        lines.append(f"Attachments: {', '.join(attachment_names)}")

    return "\n".join(lines).strip()


def _extract_message_body(message: extract_msg.Message) -> str:
    plain_body = _stringify_message_field(getattr(message, "body", None))
    if plain_body:
        return _normalize_message_text(plain_body)

    html_body = _stringify_message_field(getattr(message, "htmlBody", None))
    if html_body:
        return _normalize_message_text(_extract_html_text(html_body))

    return ""


def extract_paragraphs_from_msg(path: Path) -> list[dict[str, Any]]:
    """
    Extract message headers and body paragraphs from an Outlook .msg file.
    """

    message = extract_msg.Message(str(path))
    try:
        attachment_names = _extract_attachment_names(message)
        header_block = _build_header_block(message, attachment_names)
        body_text = _extract_message_body(message)

        combined_text = header_block
        if body_text:
            combined_text = f"{header_block}\n\n{body_text}" if header_block else body_text

        normalized_text = _normalize_message_text(combined_text).strip()
        if not normalized_text:
            return []

        records: list[dict[str, Any]] = []
        para_idx = 0
        blocks = re.split(r"\n\s*\n+", normalized_text)
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            text = _normalize_whitespace(" ".join(lines))
            if not text:
                continue

            para_idx += 1
            records.append({"text": text, "paragraph_num": para_idx, "page_num": 1})

        return records
    finally:
        message.close()


def extract_paragraphs(path: Path) -> list[dict[str, Any]]:
    """
    Extract paragraphs from a .msg file.
    """

    return extract_paragraphs_from_msg(path)


def build_msg_chunks(
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
    Build text chunks from a .msg file.
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
    Ingest a .msg file into the target collection.
    """

    try:
        chunks = build_msg_chunks(
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

    message = extract_msg.Message(str(path))
    try:
        attachment_names = _extract_attachment_names(message)
        metadata = {
            "subject": _stringify_message_field(getattr(message, "subject", None)),
            "sender": _stringify_message_field(getattr(message, "sender", None)),
            "to": _stringify_message_field(getattr(message, "to", None)),
            "cc": _stringify_message_field(getattr(message, "cc", None)),
            "bcc": _stringify_message_field(getattr(message, "bcc", None)),
            "date": _stringify_message_field(getattr(message, "date", None)),
            "attachments": "; ".join(attachment_names),
        }
    finally:
        message.close()

    texts = [chunk["text"] for chunk in chunks]
    metadatas = [
        {
            "source_name": path.name,
            "source_path": str(path.resolve()),
            "paragraph_num": chunk["paragraph_num"],
            "page_num": chunk["page_num"],
            "file_signature": file_signature,
            **metadata,
        }
        for chunk in chunks
    ]

    return batch_ingest_documents(client, collection, texts, metadatas, path.name)