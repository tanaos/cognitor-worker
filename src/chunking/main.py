from typing import Any, Literal

from chunking.semantic.main import SemanticChunker
from chunking.simple.main import SimpleChunker


ChunkerType = Literal["semantic", "simple"]


def build_chunks_from_paragraphs(
    paragraphs: list[dict[str, Any]],
    *,
    chunker_type: str = "semantic",
    chunk_size: int = 500,
    overlap_size: int = 75,
    encoding_name: str = "cl100k_base",
    semantic_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    semantic_breakpoint_percentile: int = 70,
    semantic_repair_sentence_boundaries: bool = True,
) -> list[dict[str, Any]]:
    if not paragraphs:
        return []

    normalized_chunker_type = chunker_type.strip().lower()
    if normalized_chunker_type == "simple":
        chunker = SimpleChunker(
            chunk_size=chunk_size,
            overlap_ratio=overlap_size / chunk_size,
            overlap_size=overlap_size,
            encoding_name=encoding_name,
        )
        return chunker.chunk_paragraphs(paragraphs)

    if normalized_chunker_type == "semantic":
        chunker = SemanticChunker(
            model_name=semantic_model_name,
            breakpoint_percentile=semantic_breakpoint_percentile,
            repair_sentence_boundaries=semantic_repair_sentence_boundaries,
        )
        return chunker.chunk_paragraphs(paragraphs)

    raise ValueError(
        "chunker_type must be either 'semantic' or 'simple'"
    )


__all__ = [
    "ChunkerType",
    "SimpleChunker",
    "SemanticChunker",
    "build_chunks_from_paragraphs",
]