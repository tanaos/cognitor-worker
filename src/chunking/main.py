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
    """
    Build text chunks from a list of paragraphs.
    
    Args:
        paragraphs: A list of dictionaries, each containing 'text', 'paragraph_num', and
            'page_num'.
        chunker_type: The type of chunker to use ('semantic' or 'simple').
        chunk_size: The desired size of each chunk (applicable for simple chunker).
        overlap_size: The number of overlapping characters between chunks (applicable for simple 
            chunker).
        encoding_name: The name of the encoding to use for token counting (applicable for simple 
            chunker).
        semantic_model_name: The name of the model to use for semantic chunking (applicable for 
            semantic chunker).
        semantic_breakpoint_percentile: The percentile threshold for determining breakpoints in 
            semantic chunking (applicable for semantic chunker).
        semantic_repair_sentence_boundaries: Whether to attempt to repair sentence boundaries 
            in semantic chunking (applicable for semantic chunker).
    Returns:
        A list of dictionaries containing chunked text and associated metadata.
    """
    
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