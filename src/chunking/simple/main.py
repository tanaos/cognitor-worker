import math
from typing import Any, Optional

from tiktoken import get_encoding


class SimpleChunker:
    def __init__(
        self,
        *,
        chunk_size: int,
        overlap_ratio: float,
        encoding_name: str,
        overlap_size: Optional[int] = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if not 0 <= overlap_ratio < 1:
            raise ValueError("overlap_ratio must be between 0 and 1")

        computed_overlap_size = (
            math.ceil(chunk_size * overlap_ratio)
            if overlap_size is None
            else overlap_size
        )
        if computed_overlap_size < 0:
            raise ValueError("overlap_size must be greater than or equal to 0")
        if computed_overlap_size >= chunk_size:
            raise ValueError("overlap_size must be smaller than chunk_size")

        self.chunk_size = chunk_size
        self.overlap_ratio = overlap_ratio
        self.overlap_size = computed_overlap_size
        self.encoding_name = encoding_name

    def chunk_paragraphs(self, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not paragraphs:
            return []

        encoding = get_encoding(self.encoding_name)
        stream = self._build_token_stream(paragraphs, encoding)
        return self._make_chunks(stream, encoding)

    def _build_token_stream(
        self, paragraphs: list[dict[str, Any]], encoding: Any
    ) -> list[tuple[int, int, int]]:
        stream: list[tuple[int, int, int]] = []
        space_tokens = encoding.encode(" ")

        for paragraph in paragraphs:
            for token in encoding.encode(paragraph["text"]):
                stream.append((token, paragraph["paragraph_num"], paragraph["page_num"]))
            for token in space_tokens:
                stream.append((token, paragraph["paragraph_num"], paragraph["page_num"]))

        return stream

    def _make_chunks(
        self,
        stream: list[tuple[int, int, int]],
        encoding: Any,
    ) -> list[dict[str, Any]]:
        step = self.chunk_size - self.overlap_size
        chunks: list[dict[str, Any]] = []
        total = len(stream)
        start = 0

        while start < total:
            end = min(start + self.chunk_size, total)
            window = stream[start:end]
            text = encoding.decode([token for token, _paragraph_num, _page_num in window])
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
