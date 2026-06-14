import json
from pathlib import Path
from datetime import datetime, timezone


class WorkerStatusManager:
    """Manages worker status persistence."""

    DEFAULT_STATUS_FILE = "worker_status.json"
    SYNC_TIMEOUT_SECONDS = 3600  # Consider sync stale after 1 hour

    def __init__(self, storage_root: str = "storage"):
        """
        Initialize the worker status manager.

        Args:
            storage_root: Root directory for status storage.
        """
        
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.status_path = self.storage_root / self.DEFAULT_STATUS_FILE

    def start_sync(self) -> None:
        """
        Mark the beginning of a synchronization operation.
        """
        
        status = {
            "sync_start_time": datetime.now(timezone.utc).isoformat(),
            "sync_end_time": None,
        }
        try:
            with open(self.status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)
        except IOError as e:
            # Log but don't fail - status tracking is non-critical
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to write sync start status: {e}")

    def end_sync(self) -> None:
        """
        Mark the completion of a synchronization operation.
        """
        
        status = {
            "sync_start_time": None,
            "sync_end_time": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self.status_path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)
        except IOError as e:
            # Log but don't fail - status tracking is non-critical
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to write sync end status: {e}")

    def is_syncing(self) -> bool:
        """
        Determine if a synchronization is currently in progress.

        Returns:
            True if sync is in progress, False otherwise.
        """
        
        if not self.status_path.exists():
            return False

        try:
            with open(self.status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False

        sync_start_time = status.get("sync_start_time")
        sync_end_time = status.get("sync_end_time")

        # If there's no start time, no sync is in progress
        if not sync_start_time:
            return False

        # If there's an end time, sync is complete
        if sync_end_time:
            return False

        # Check if the start time is too old (stale sync)
        try:
            start = datetime.fromisoformat(sync_start_time.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            elapsed = (now - start).total_seconds()
            if elapsed > self.SYNC_TIMEOUT_SECONDS:
                # Sync has been running too long, consider it stale
                return False
        except (ValueError, AttributeError):
            return False

        return True
