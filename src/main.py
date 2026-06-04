import importlib.util
import os
import signal
import threading
from pathlib import Path
from types import ModuleType
from typing import Any
from cognitor import Cognitor
from dotenv import load_dotenv

from utils.logging import setup_logging


load_dotenv()
setup_logging()


COGNITOR_URL = os.getenv("COGNITOR_URL")
COGNITOR_API_KEY = os.getenv("COGNITOR_API_KEY", None)
COLLECTION_NAME = os.getenv("COGNITOR_COLLECTION_NAME")
DOCS_FOLDER_RAW = os.getenv("DOCS_FOLDER")
SYNC_INTERVAL_SECONDS = float(os.getenv("SYNC_INTERVAL_SECONDS", "60"))


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
            print(f"  Failed to delete document {doc_id}: {exc}")
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
        print(f"Created collection '{collection}'")


def _ingest_doc_file(
    client: Cognitor,
    collection: str,
    path: Path,
    file_signature: str,
    doc_connector: ModuleType,
) -> None:
    """
    Ingest a document file into the specified collection.
    
    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to ingest into.
        path: The path to the document file.
        file_signature: The signature of the file.
        doc_connector: The document connector module.
    """
    
    try:
        chunks = doc_connector.build_doc_chunks(path)
    except Exception as exc:
        print(f"  Skipped {path.name}: {exc}")
        return

    if not chunks:
        print(f"  Skipped {path.name}: no text found")
        return

    texts = [c["text"] for c in chunks]
    metadatas = [
        {
            "source_name": path.name,
            "source_path": str(path.resolve()),
            "paragraph_num": c["paragraph_num"],
            "page_num": c["page_num"],
            "file_signature": file_signature,
        }
        for c in chunks
    ]

    ids = client.bulk_add_documents(collection, texts, metadatas)
    print(f"  {path.name}: {len(ids)} chunk(s) ingested")


def sync_once(
    client: Cognitor, collection: str, docs_folder: Path, 
    doc_connector: ModuleType
) -> None:
    """
    Perform a single synchronization pass between the local folder and the Cognitor collection.
    
    Args:
        client: An instance of the Cognitor client.
        collection: The name of the collection to synchronize with.
        docs_folder: The local folder containing document files.
        doc_connector: The document connector module to use for parsing files.
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
            print(f"Removed {deleted} stale chunk(s) for missing file: {source_path}")

    added_or_updated = 0
    for source_path, path in local_map.items():
        signature = _build_file_signature(path)
        existing_docs = remote_by_path.get(source_path, [])

        if not existing_docs:
            print(f"Ingesting new file: {path.name}")
            _ingest_doc_file(client, collection, path, signature, doc_connector)
            added_or_updated += 1
            continue

        existing_signatures = {
            doc.metadata.get("file_signature")
            for doc in existing_docs
            if isinstance(doc.metadata, dict)
        }

        if existing_signatures != {signature}:
            deleted = _delete_documents(client, collection, [doc.id for doc in existing_docs])
            print(f"Reingesting changed file: {path.name} (removed {deleted} old chunk(s))")
            _ingest_doc_file(client, collection, path, signature, doc_connector)
            added_or_updated += 1

    print(
        "Sync pass complete | "
        f"local_files={len(local_files)} remote_docs={len(remote_docs)} "
        f"removed_paths={len(removed_paths)} added_or_updated_files={added_or_updated}"
    )


def run_daemon() -> None:
    """
    Run the Cognitor sync daemon, which continuously synchronizes the local folder
    with the Cognitor collection at regular intervals.
    """
    
    missing: list[str] = []
    if not DOCS_FOLDER_RAW:
        missing.append("DOCS_FOLDER")
    if not COLLECTION_NAME:
        missing.append("COGNITOR_COLLECTION_NAME")
    if not COGNITOR_URL:
        missing.append("COGNITOR_URL")
    if missing:
        missing_values = ", ".join(missing)
        raise ValueError(f"Missing required environment variable(s): {missing_values}")
    
    # Redundant check for type safety and to satisfy static analysis
    assert DOCS_FOLDER_RAW is not None and \
        COLLECTION_NAME is not None and \
        COGNITOR_URL is not None

    docs_folder = Path(DOCS_FOLDER_RAW).expanduser().resolve()
    if not docs_folder.exists():
        raise FileNotFoundError(f"Configured folder does not exist: {docs_folder}")
    if not docs_folder.is_dir():
        raise NotADirectoryError(f"Configured folder is not a directory: {docs_folder}")

    doc_connector = _load_doc_connector()
    stop_event = threading.Event()

    def _handle_shutdown(signum: int, _frame: Any) -> None:
        print(f"Received signal {signum}; shutting down daemon...")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    print(
        "Starting Cognitor sync daemon | "
        f"folder={docs_folder} collection={COLLECTION_NAME} "
        f"url={COGNITOR_URL} interval={SYNC_INTERVAL_SECONDS}s"
    )

    with Cognitor(COGNITOR_URL, api_key=COGNITOR_API_KEY) as client:
        sync_once(client, COLLECTION_NAME, docs_folder, doc_connector)

        while not stop_event.wait(SYNC_INTERVAL_SECONDS):
            try:
                sync_once(client, COLLECTION_NAME, docs_folder, doc_connector)
            except Exception as exc:
                print(f"Sync pass failed: {exc}")


def main() -> None:
    run_daemon()


if __name__ == "__main__":
    main()
