"""
Shared utilities for document ingestion.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Batch size for ingesting documents to avoid memory issues
INGEST_BATCH_SIZE = 200


def batch_ingest_documents(
    client: Any,
    collection: str,
    texts: list[str],
    metadatas: list[dict[str, Any]],
    source_name: str = "document",
) -> int:
    """
    Ingest documents in batches to avoid memory issues.

    Args:
        client: Cognitor client instance
        collection: Collection name to ingest into
        texts: List of text chunks to ingest
        metadatas: List of metadata dicts corresponding to texts
        source_name: Name of the source file (for logging)

    Returns:
        Total number of documents ingested
    """
    if not texts:
        return 0

    total_ingested = 0
    num_batches = (len(texts) + INGEST_BATCH_SIZE - 1) // INGEST_BATCH_SIZE

    for i in range(0, len(texts), INGEST_BATCH_SIZE):
        batch_texts = texts[i : i + INGEST_BATCH_SIZE]
        batch_metadatas = metadatas[i : i + INGEST_BATCH_SIZE]
        
        ids = client.bulk_add_documents(collection, batch_texts, batch_metadatas)
        total_ingested += len(ids)
        
        batch_num = (i // INGEST_BATCH_SIZE) + 1
        logger.debug(
            "%s: ingested batch %d/%d (%d documents)",
            source_name,
            batch_num,
            num_batches,
            len(ids),
        )

    logger.info(
        "%s: %d chunk(s) ingested in %d batch(es)",
        source_name,
        total_ingested,
        num_batches,
    )
    return total_ingested
