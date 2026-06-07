import math
import re

from typing import Any, Iterable
from tiktoken import get_encoding
from typing import Optional
from llama_index.core import Document
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core.schema import BaseNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

class DocumentChunker:
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


class SemanticChunker:
    def __init__(
        self,
        *,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        breakpoint_percentile: int = 70,
        repair_sentence_boundaries: bool = True,
    ) -> None:
        if not 0 <= breakpoint_percentile <= 100:
            raise ValueError(
                "breakpoint_percentile must be between 0 and 100"
            )

        self.model_name = model_name
        self.breakpoint_percentile = breakpoint_percentile
        self.repair_sentence_boundaries = repair_sentence_boundaries

    def chunk(self, texts: Iterable[str]) -> list[BaseNode]:
        documents = self._build_documents(texts)

        embed_model = HuggingFaceEmbedding(
            model_name=self.model_name,
        )

        parser = SemanticSplitterNodeParser(
            embed_model=embed_model,
            breakpoint_percentile_threshold=self.breakpoint_percentile,
            include_metadata=True,
            include_prev_next_rel=True,
        )

        nodes = parser.get_nodes_from_documents(documents)

        if self.repair_sentence_boundaries:
            nodes = self._repair_sentence_boundaries(nodes)

        return nodes

    def _build_documents(
        self,
        texts: Iterable[str],
    ) -> list[Document]:
        return [
            Document(
                text=text,
                metadata={"doc_num": index},
            )
            for index, text in enumerate(texts)
        ]

    def _split_into_sentences(
        self,
        text: str,
    ) -> list[str]:
        normalized_text = re.sub(r"\s+", " ", text).strip()

        if not normalized_text:
            return []

        sentences = re.split(
            r"(?<=[.!?])\s+",
            normalized_text,
        )

        return [
            sentence.strip()
            for sentence in sentences
            if sentence.strip()
        ]

    def _repair_sentence_boundaries(
        self,
        nodes: list[BaseNode],
    ) -> list[BaseNode]:
        repaired_nodes: list[BaseNode] = []
        buffer = ""

        for node in nodes:
            text = node.get_content().strip()

            if not text:
                continue

            combined_text = (
                f"{buffer} {text}".strip()
                if buffer
                else text
            )

            sentences = self._split_into_sentences(
                combined_text
            )

            if not sentences:
                buffer = combined_text
                continue

            ends_cleanly = combined_text.rstrip().endswith(
                (".", "?", "!")
            )

            if ends_cleanly:
                complete_text = " ".join(sentences)
                buffer = ""
            else:
                complete_text = " ".join(sentences[:-1])
                buffer = sentences[-1]

            if not complete_text:
                continue

            node.text = complete_text
            repaired_nodes.append(node)

        self._append_buffer(
            repaired_nodes=repaired_nodes,
            original_nodes=nodes,
            buffer=buffer,
        )

        return repaired_nodes

    def _append_buffer(
        self,
        *,
        repaired_nodes: list[BaseNode],
        original_nodes: list[BaseNode],
        buffer: str,
    ) -> None:
        if not buffer:
            return

        if repaired_nodes:
            repaired_nodes[-1].text = (
                repaired_nodes[-1]
                .get_content()
                .rstrip()
                + " "
                + buffer
            ).strip()
            return

        if not original_nodes:
            return

        original_nodes[0].text = buffer
        repaired_nodes.append(original_nodes[0])
