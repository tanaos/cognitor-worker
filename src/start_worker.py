import importlib.util
import logging
import os
import signal
import threading
from pathlib import Path
from types import ModuleType
from typing import Any
import subprocess
import sys
from cognitor import Cognitor
from config.settings import Config
from utils.logging import setup_logging


setup_logging()

logger = logging.getLogger(__name__)


config = Config() # type: ignore[assignment]


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


def _iter_all_documents(client: Cognitor, collection: str) -> list[Any]:
    """
    Retrieve all documents from the specified collection, handling pagination.
    
    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to retrieve documents from.
    Returns:        
        A list of all documents in the collection.
    """
    
    docs: list[Any] = []
    offset = 0
    page_size = 200

    while True:
        result = client.list_documents(collection, offset=offset, limit=page_size)
        docs.extend(result.documents)
        offset += len(result.documents)
        if offset >= result.total or not result.documents:
            break

    return docs


def _group_docs_by_source_path(documents: list[Any]) -> dict[str, list[Any]]:
    """
    Group documents by their source path.

    Args:
        documents: A list of documents to group.
    Returns:
        A dictionary mapping source paths to lists of documents.
    """
    
    grouped: dict[str, list[Any]] = {}
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
    except Exception:
        client.create_collection(collection)
        logger.info("Created collection '%s'", collection)


def _ingest_doc_file(
    client: Cognitor,
    collection: str,
    path: Path,
    file_signature: str,
    ingestion_service: Any,
) -> None:
    """
    Ingest a document file into the specified collection.

    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to ingest into.
        path: The path to the document file.
        file_signature: The signature of the file.
        ingestion_service: The document ingestion service.
    """

    ingestion_service.ingest_file(client, collection, path, file_signature)


def sync_once(
    client: Cognitor,
    collection: str,
    docs_folder: Path,
    ingestion_service: Any,
) -> None:
    """
    Perform a single synchronization pass between the local folder and the Cognitor collection.
    
    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to synchronize with.
        docs_folder: The local folder containing document files.
        ingestion_service: The document ingestion service.
    """
    
    _ensure_collection(client, collection)

    local_files = sorted(
        list(docs_folder.rglob("*.docx")) + list(docs_folder.rglob("*.doc"))
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
            _ingest_doc_file(client, collection, path, signature, ingestion_service)
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
            _ingest_doc_file(client, collection, path, signature, ingestion_service)
            added_or_updated += 1

    logger.info(
        "Sync pass complete | local_files=%s remote_docs=%s removed_paths=%s added_or_updated_files=%s",
        len(local_files),
        len(remote_docs),
        len(removed_paths),
        added_or_updated,
    )


def run_daemon() -> None:
    """
    Run the Cognitor sync daemon, which continuously synchronizes the local folder
    with the Cognitor collection at regular intervals.
    """
    
    missing: list[str] = []
    if not config.DOCS_FOLDER:
        missing.append("DOCS_FOLDER")
    if not config.COGNITOR_COLLECTION_NAME:
        missing.append("COGNITOR_COLLECTION_NAME")
    if not config.COGNITOR_URL:
        missing.append("COGNITOR_URL")
    if missing:
        missing_values = ", ".join(missing)
        raise ValueError(f"Missing required environment variable(s): {missing_values}")
    
    # Redundant check for type safety and to satisfy static analysis
    assert config.DOCS_FOLDER is not None and \
        config.COGNITOR_COLLECTION_NAME is not None and \
        config.COGNITOR_URL is not None

    docs_folder = Path(config.DOCS_FOLDER).expanduser().resolve()
    if not docs_folder.exists():
        raise FileNotFoundError(f"Configured folder does not exist: {docs_folder}")
    if not docs_folder.is_dir():
        raise NotADirectoryError(f"Configured folder is not a directory: {docs_folder}")

    doc_connector = _load_doc_connector()
    ingestion_service = doc_connector.DocumentIngestionService(
        chunker=doc_connector.DocumentChunker(
            chunk_size=config.DEFAULT_CHUNK_SIZE,
            overlap_ratio=config.DEFAULT_OVERLAP_RATIO,
            encoding_name=config.DEFAULT_ENCODING_NAME,
        )
    )
    stop_event = threading.Event()

    def _handle_shutdown(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s; shutting down daemon...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    logger.info(
        "Starting Cognitor sync daemon | folder=%s collection=%s url=%s interval=%ss",
        docs_folder,
        config.COGNITOR_COLLECTION_NAME,
        config.COGNITOR_URL,
        config.SYNC_INTERVAL_SECONDS,
    )

    with Cognitor(config.COGNITOR_URL, api_key=config.COGNITOR_API_KEY) as client:
        sync_once(client, config.COGNITOR_COLLECTION_NAME, docs_folder, ingestion_service)

        while not stop_event.wait(config.SYNC_INTERVAL_SECONDS):
            try:
                sync_once(client, config.COGNITOR_COLLECTION_NAME, docs_folder, ingestion_service)
            except Exception as exc:
                logger.error("Sync pass failed: %s", exc)


PID_FILE = Path("logs") / "cognitor-worker.pid"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Cognitor sync worker")
    parser.add_argument(
        "-d", "--daemon", action="store_true", help="Run detached in the background"
    )
    args = parser.parse_args()

    if not args.daemon:
        run_daemon()
        return

    # Daemon mode: spawn a detached subprocess that runs this same script without -d
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }

    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen([sys.executable, __file__], **kwargs)
    PID_FILE.write_text(str(proc.pid))
    print(f"Cognitor worker started in background (PID {proc.pid}). Logs are being written to {PID_FILE.parent.resolve()}.")
    print("Use 'python src/stop_worker.py' to stop the background worker.")


if __name__ == "__main__":
    main()
