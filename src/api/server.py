"""
Worker REST API server.

Exposes endpoints for managing the worker's indexing operations,
folder configuration, and status monitoring.
"""

from typing import Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel


class WorkerStatus(BaseModel):
    """Worker status response."""
    indexing: bool
    error: str | None = None


class WorkerFolder(BaseModel):
    """Folder configuration response."""
    folder_path: str | None = None
    configured: bool


class WorkerFolderRequest(BaseModel):
    """Request to set folder path."""
    folder_path: str


class WorkerMessage(BaseModel):
    """Generic worker response message."""
    message: str


# Router will be populated by the worker process
router = APIRouter()

# Shared state - will be set by the worker process
_worker_state: dict[str, Any] = {
    "sync_event": None,  # threading.Event to trigger sync
    "status_lock": None,  # threading.Lock for status access
    "status": {
        "indexing": False,
        "error": None,
    },
    "folder_path": None,
    "set_folder_callback": None,  # callback function to set folder
    "clear_folder_callback": None,  # callback function to clear folder
}


def set_worker_state(state: dict[str, Any]) -> None:
    """Initialize the shared worker state."""
    global _worker_state
    _worker_state = state


@router.get("/status", response_model=WorkerStatus)
async def get_status() -> WorkerStatus:
    """Get the current worker status (indexing, errors)."""
    if _worker_state.get("status_lock"):
        with _worker_state["status_lock"]:
            status_data = _worker_state.get("status", {})
            return WorkerStatus(
                indexing=status_data.get("indexing", False),
                error=status_data.get("error"),
            )
    return WorkerStatus(indexing=False, error=None)


@router.post("/reindex", response_model=WorkerMessage)
async def trigger_reindex() -> WorkerMessage:
    """Trigger an immediate reindex of the configured folder."""
    sync_event = _worker_state.get("sync_event")
    if not sync_event:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker not ready",
        )
    
    # Signal the worker thread to perform a sync immediately
    sync_event.set()
    
    return WorkerMessage(message="Reindex triggered")


@router.get("/folder", response_model=WorkerFolder)
async def get_folder() -> WorkerFolder:
    """Get the currently configured folder path."""
    folder_path = _worker_state.get("folder_path")
    return WorkerFolder(
        folder_path=folder_path,
        configured=folder_path is not None,
    )


@router.post("/folder", response_model=WorkerMessage)
async def set_folder(request: WorkerFolderRequest) -> WorkerMessage:
    """Set the folder path to index."""
    callback = _worker_state.get("set_folder_callback")
    if not callback:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker not ready",
        )
    
    try:
        callback(request.folder_path)
        return WorkerMessage(message="Folder configured successfully")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/folder", response_model=WorkerMessage)
async def clear_folder() -> WorkerMessage:
    """Clear the folder configuration."""
    callback = _worker_state.get("clear_folder_callback")
    if not callback:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker not ready",
        )
    
    try:
        callback()
        return WorkerMessage(message="Folder cleared successfully")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
