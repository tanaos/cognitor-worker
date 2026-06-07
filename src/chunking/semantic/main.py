import re
from typing import Any, Iterable

from llama_index.core import Document
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core.schema import BaseNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding


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

    def chunk_paragraphs(self, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not paragraphs:
            return []

        nodes = self.chunk(paragraph["text"] for paragraph in paragraphs)

        chunks: list[dict[str, Any]] = []
        for node in nodes:
            text = node.get_content().strip()
            if not text:
                continue

            metadata = node.metadata if isinstance(node.metadata, dict) else {}
            doc_num = metadata.get("doc_num")
            paragraph = (
                paragraphs[doc_num]
                if isinstance(doc_num, int) and 0 <= doc_num < len(paragraphs)
                else paragraphs[0]
            )

            chunks.append(
                {
                    "text": text,
                    "paragraph_num": paragraph["paragraph_num"],
                    "page_num": paragraph["page_num"],
                }
            )

        return chunks

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
