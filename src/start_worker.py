import importlib.util
import logging
import math
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from cognitor import Cognitor, ConflictError, NotFoundError
from pydantic import ValidationError
from config.settings import Config
from utils.logging import setup_logging


setup_logging()

logger = logging.getLogger(__name__)


@dataclass
class _RemoteDocLite:
    id: str
    metadata: dict[str, Any]


def _to_remote_doc_lite(raw: Any) -> _RemoteDocLite | None:
    """
    Normalize SDK objects / JSON dicts to a minimal shape used by sync logic.
    """
    if isinstance(raw, dict):
        doc_id = raw.get("id")
        metadata = raw.get("metadata")
    else:
        doc_id = getattr(raw, "id", None)
        metadata = getattr(raw, "metadata", None)

    if not isinstance(doc_id, str) or not doc_id:
        return None
    if not isinstance(metadata, dict):
        metadata = {}

    return _RemoteDocLite(id=doc_id, metadata=metadata)


def _load_doc_connector() -> ModuleType:
    """
    Dynamically load the doc connector module from src/doc-connector/main.py.
    """
    
    connector_path = Path(__file__).parent / "doc-connector" / "main.py"
    spec = importlib.util.spec_from_file_location("doc_connector_main", connector_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load doc connector module at {connector_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_pdf_connector() -> ModuleType:
    """
    Dynamically load the PDF connector module from src/pdf-connector/main.py.
    """

    connector_path = Path(__file__).parent / "pdf-connector" / "main.py"
    spec = importlib.util.spec_from_file_location("pdf_connector_main", connector_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load PDF connector module at {connector_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_md_connector() -> ModuleType:
    """
    Dynamically load the Markdown connector module from src/md-connector/main.py.
    """

    connector_path = Path(__file__).parent / "md-connector" / "main.py"
    spec = importlib.util.spec_from_file_location("md_connector_main", connector_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Markdown connector module at {connector_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_html_connector() -> ModuleType:
    """
    Dynamically load the HTML connector module from src/html-connector/main.py.
    """

    connector_path = Path(__file__).parent / "html-connector" / "main.py"
    spec = importlib.util.spec_from_file_location("html_connector_main", connector_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load HTML connector module at {connector_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_msg_connector() -> ModuleType:
    """
    Dynamically load the MSG connector module from src/msg-connector/main.py.
    """

    connector_path = Path(__file__).parent / "msg-connector" / "main.py"
    spec = importlib.util.spec_from_file_location("msg_connector_main", connector_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load MSG connector module at {connector_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_config() -> Config:
    """
    Load runtime configuration and convert missing settings into a direct startup error.
    """

    try:
        return Config()  # type: ignore[return-value]
    except ValidationError as exc:
        missing = sorted(
            {
                str(err["loc"][0])
                for err in exc.errors()
                if err.get("type") == "missing" and err.get("loc")
            }
        )
        if missing:
            missing_values = ", ".join(missing)
            raise ValueError(
                f"Missing required environment variable(s): {missing_values}"
            ) from exc
        raise


def _build_file_signature(path: Path) -> str:
    """
    Build a simple signature for a file based on its size and modification time.
    
    Args:
        path: Path to the file.
    Returns:
        A string signature that changes if the file content likely changed.
    """
    
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _iter_all_documents(client: Cognitor, collection: str) -> list[_RemoteDocLite]:
    """
    Retrieve all documents from the specified collection, handling pagination.
    
    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to retrieve documents from.
    Returns:        
        A list of all documents in the collection.
    """
    
    docs: list[_RemoteDocLite] = []
    offset = 0
    page_size = 200

    while True:
        result = client.list_documents(
            collection,
            offset=offset,
            limit=page_size,
        )
        page_raw = result.documents
        total = result.total

        page_docs = [doc for doc in (_to_remote_doc_lite(raw) for raw in page_raw) if doc is not None]
        docs.extend(page_docs)
        offset += len(page_docs)
        if offset >= total or not page_docs:
            break

    return docs


def _group_docs_by_source_path(documents: list[_RemoteDocLite]) -> dict[str, list[_RemoteDocLite]]:
    """
    Group documents by their source path.

    Args:
        documents: A list of documents to group.
    Returns:
        A dictionary mapping source paths to lists of documents.
    """
    
    grouped: dict[str, list[_RemoteDocLite]] = {}
    for doc in documents:
        metadata = doc.metadata if isinstance(doc.metadata, dict) else {}
        source_path = metadata.get("source_path")
        if isinstance(source_path, str) and source_path:
            grouped.setdefault(source_path, []).append(doc)
    return grouped


def _delete_documents(client: Cognitor, collection: str, doc_ids: list[str]) -> int:
    """
    Delete documents from the specified collection.

    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to delete documents from.
        doc_ids: A list of document IDs to delete.
    Returns:
        The number of documents successfully deleted.
    """
    
    deleted = 0
    for doc_id in doc_ids:
        try:
            client.delete_document(collection, doc_id)
            deleted += 1
        except Exception as exc:
            logger.error("Failed to delete document %s: %s", doc_id, exc)
    return deleted


def _ensure_collection(client: Cognitor, collection: str) -> None:
    """
    Ensure that the specified collection exists.

    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to ensure.
    """
    
    try:
        client.get_collection(collection)
        return
    except NotFoundError:
        pass

    try:
        client.create_collection(collection)
        logger.info("Created collection '%s'", collection)
    except ConflictError:
        logger.info("Collection '%s' already exists", collection)


def _wait_for_cognitor_ready(
    client: Cognitor,
    stop_event: threading.Event,
    *,
    poll_interval_seconds: int = 10,
) -> None:
    """
    Block until Cognitor reports readiness via GET /health/ready.

    Args:
        client: An instance of the Cognitor client.
        stop_event: Worker stop event used to interrupt readiness waiting.
        poll_interval_seconds: Delay between readiness checks while loading.
    """

    while not stop_event.is_set():
        try:
            status = client.health_ready()
        except Exception as exc:
            logger.warning("Health check failed while waiting for Cognitor readiness: %s", exc)
            status = "loading"

        if status == "ready":
            logger.info("Cognitor is ready")
            return

        logger.info("Cognitor not ready yet; waiting %ss before retry", poll_interval_seconds)
        stop_event.wait(poll_interval_seconds)

    raise RuntimeError("Worker stopped while waiting for Cognitor readiness")


def _ingest_doc_file(
    client: Cognitor,
    collection: str,
    path: Path,
    file_signature: str,
    ingestion_service: Any,
    *,
    chunker_type: str,
    chunk_size: int,
    overlap_ratio: float,
    encoding_name: str,
    semantic_model_name: str,
    semantic_breakpoint_percentile: int,
    semantic_repair_sentence_boundaries: bool,
) -> None:
    """
    Ingest a document file into the specified collection.

    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to ingest into.
        path: The path to the document file.
        file_signature: The signature of the file.
        ingestion_service: The document ingestion service.
        chunk_size: The chunk size to use during ingestion.
        overlap_ratio: The overlap ratio used to compute token overlap.
        encoding_name: The token encoding to use.
    """

    overlap_size = max(1, math.ceil(chunk_size * overlap_ratio))
    if overlap_size >= chunk_size:
        overlap_size = chunk_size - 1

    ingestion_service.ingest_file(
        client,
        collection,
        path,
        file_signature,
        chunker_type=chunker_type,
        chunk_size=chunk_size,
        overlap_size=overlap_size,
        encoding_name=encoding_name,
        semantic_model_name=semantic_model_name,
        semantic_breakpoint_percentile=semantic_breakpoint_percentile,
        semantic_repair_sentence_boundaries=semantic_repair_sentence_boundaries,
    )


def _ingestion_service_for_path(
    path: Path,
    doc_connector: ModuleType,
    pdf_connector: ModuleType,
    md_connector: ModuleType,
    html_connector: ModuleType,
    msg_connector: ModuleType,
) -> Any:
    """
    Select the ingestion service that owns the given file type.
    """

    if path.suffix.lower() == ".pdf":
        return pdf_connector
    if path.suffix.lower() == ".md":
        return md_connector
    if path.suffix.lower() in {".html", ".htm"}:
        return html_connector
    if path.suffix.lower() == ".msg":
        return msg_connector
    return doc_connector


def _warm_up_semantic_chunker(
    *,
    semantic_model_name: str,
    semantic_breakpoint_percentile: int,
    semantic_repair_sentence_boundaries: bool,
) -> None:
    """
    Ensure semantic model weights are available before the first sync pass.
    """

    from chunking.semantic.main import SemanticChunker

    logger.info("Warming up semantic chunker model: %s", semantic_model_name)
    chunker = SemanticChunker(
        model_name=semantic_model_name,
        breakpoint_percentile=semantic_breakpoint_percentile,
        repair_sentence_boundaries=semantic_repair_sentence_boundaries,
    )
    chunker.chunk(["Semantic chunker warm-up sentence."])
    logger.info("Semantic chunker model warm-up complete")


def sync_once(
    client: Cognitor,
    collection: str,
    docs_folder: Path,
    doc_connector: ModuleType,
    pdf_connector: ModuleType,
    md_connector: ModuleType,
    html_connector: ModuleType,
    msg_connector: ModuleType,
    *,
    chunker_type: str,
    chunk_size: int,
    overlap_ratio: float,
    encoding_name: str,
    semantic_model_name: str,
    semantic_breakpoint_percentile: int,
    semantic_repair_sentence_boundaries: bool,
) -> None:
    """
    Perform a single synchronization pass between the local folder and the Cognitor collection.
    
    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to synchronize with.
        docs_folder: The local folder containing document files.
        doc_connector: The .doc/.docx connector module.
        pdf_connector: The .pdf connector module.
        md_connector: The .md connector module.
        html_connector: The .html/.htm connector module.
        msg_connector: The .msg connector module.
        chunk_size: The chunk size to use during ingestion.
        overlap_ratio: The overlap ratio used to compute token overlap.
        encoding_name: The token encoding to use.
    """
    
    _ensure_collection(client, collection)

    supported_suffixes = {".docx", ".doc", ".pdf", ".md", ".html", ".htm", ".msg"}
    local_files = sorted(
        path
        for path in docs_folder.rglob("*")
        if path.is_file() and path.suffix.lower() in supported_suffixes
    )
    local_map = {str(path.resolve()): path for path in local_files}

    remote_docs = _iter_all_documents(client, collection)
    remote_by_path = _group_docs_by_source_path(remote_docs)

    local_paths = set(local_map.keys())
    remote_paths = set(remote_by_path.keys())

    removed_paths = sorted(remote_paths - local_paths)
    for source_path in removed_paths:
        stale_docs = remote_by_path[source_path]
        deleted = _delete_documents(client, collection, [doc.id for doc in stale_docs])
        if deleted:
            logger.info("Removed %s stale chunk(s) for missing file: %s", deleted, source_path)

    added_or_updated = 0
    for source_path, path in local_map.items():
        signature = _build_file_signature(path)
        existing_docs = remote_by_path.get(source_path, [])

        if not existing_docs:
            logger.info("Ingesting new file: %s", path.name)
            _ingest_doc_file(
                client,
                collection,
                path,
                signature,
                _ingestion_service_for_path(
                    path,
                    doc_connector,
                    pdf_connector,
                    md_connector,
                    html_connector,
                    msg_connector,
                ),
                chunker_type=chunker_type,
                chunk_size=chunk_size,
                overlap_ratio=overlap_ratio,
                encoding_name=encoding_name,
                semantic_model_name=semantic_model_name,
                semantic_breakpoint_percentile=semantic_breakpoint_percentile,
                semantic_repair_sentence_boundaries=semantic_repair_sentence_boundaries,
            )
            added_or_updated += 1
            continue

        existing_signatures = {
            doc.metadata.get("file_signature")
            for doc in existing_docs
            if isinstance(doc.metadata, dict)
        }

        if existing_signatures != {signature}:
            deleted = _delete_documents(client, collection, [doc.id for doc in existing_docs])
            logger.info(
                "Reingesting changed file: %s (removed %s old chunk(s))",
                path.name,
                deleted,
            )
            _ingest_doc_file(
                client,
                collection,
                path,
                signature,
                _ingestion_service_for_path(
                    path,
                    doc_connector,
                    pdf_connector,
                    md_connector,
                    html_connector,
                    msg_connector,
                ),
                chunker_type=chunker_type,
                chunk_size=chunk_size,
                overlap_ratio=overlap_ratio,
                encoding_name=encoding_name,
                semantic_model_name=semantic_model_name,
                semantic_breakpoint_percentile=semantic_breakpoint_percentile,
                semantic_repair_sentence_boundaries=semantic_repair_sentence_boundaries,
            )
            added_or_updated += 1

    logger.info(
        "Sync pass complete | local_files=%s remote_docs=%s removed_paths=%s added_or_updated_files=%s",
        len(local_files),
        len(remote_docs),
        len(removed_paths),
        added_or_updated,
    )


def run_worker() -> None:
    """
    Run the Cognitor sync worker, which continuously synchronizes the local folder
    with the Cognitor collection at regular intervals.
    """
    
    config = _load_config()
    
    # Redundant check for type safety and to satisfy static analysis
    assert config.DOCS_FOLDER is not None and \
        config.COGNITOR_COLLECTION_NAME is not None and \
        config.COGNITOR_URL is not None

    docs_folder = Path(config.DOCS_FOLDER).expanduser().resolve()
    if not docs_folder.exists():
        raise FileNotFoundError(f"Configured folder does not exist: {docs_folder}")
    if not docs_folder.is_dir():
        raise NotADirectoryError(f"Configured folder is not a directory: {docs_folder}")

    if config.COGNITOR_TIMEOUT_SECONDS <= 0:
        raise ValueError("COGNITOR_TIMEOUT_SECONDS must be greater than 0")

    doc_connector = _load_doc_connector()
    pdf_connector = _load_pdf_connector()
    md_connector = _load_md_connector()
    html_connector = _load_html_connector()
    msg_connector = _load_msg_connector()
    stop_event = threading.Event()

    def _handle_shutdown(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s; shutting down worker...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    logger.info(
        "Starting Cognitor sync worker | folder=%s collection=%s url=%s interval=%ss",
        docs_folder,
        config.COGNITOR_COLLECTION_NAME,
        config.COGNITOR_URL,
        config.SYNC_INTERVAL_SECONDS,
    )

    with Cognitor(
        config.COGNITOR_URL,
        api_key=config.COGNITOR_API_KEY,
        timeout=config.COGNITOR_TIMEOUT_SECONDS,
    ) as client:
        _wait_for_cognitor_ready(client, stop_event)

        if config.CHUNKER_TYPE.strip().lower() == "semantic":
            _warm_up_semantic_chunker(
                semantic_model_name=config.SEMANTIC_MODEL_NAME,
                semantic_breakpoint_percentile=config.SEMANTIC_BREAKPOINT_PERCENTILE,
                semantic_repair_sentence_boundaries=config.SEMANTIC_REPAIR_SENTENCE_BOUNDARIES,
            )

        def _run_sync_pass_safely() -> None:
            try:
                sync_once(
                    client,
                    config.COGNITOR_COLLECTION_NAME,
                    docs_folder,
                    doc_connector,
                    pdf_connector,
                    md_connector,
                    html_connector,
                    msg_connector,
                    chunker_type=config.CHUNKER_TYPE,
                    chunk_size=config.DEFAULT_CHUNK_SIZE,
                    overlap_ratio=config.DEFAULT_OVERLAP_RATIO,
                    encoding_name=config.DEFAULT_ENCODING_NAME,
                    semantic_model_name=config.SEMANTIC_MODEL_NAME,
                    semantic_breakpoint_percentile=config.SEMANTIC_BREAKPOINT_PERCENTILE,
                    semantic_repair_sentence_boundaries=config.SEMANTIC_REPAIR_SENTENCE_BOUNDARIES,
                )
            except Exception as exc:
                logger.error("Sync pass failed: %s", exc)

        _run_sync_pass_safely()

        while not stop_event.wait(config.SYNC_INTERVAL_SECONDS):
            _run_sync_pass_safely()

def main() -> None:
    try:
        run_worker()
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
