import logging
import logging.config
from pathlib import Path
from typing import Any, Dict

from pydantic_settings import BaseSettings, SettingsConfigDict


LOG_FILE_PATH = Path("logs") / "cognitor-worker.log"
HTTP_LOGGER_PREFIXES = (
    "httpx",
    "httpcore",
    "urllib3",
    "aiohttp",
)

_HTTP_INFO_ENABLED = False


class LoggingSettings(BaseSettings):
    WORKER_LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
    )


def _resolve_log_level() -> int:
    level_name = LoggingSettings().WORKER_LOG_LEVEL.strip().upper()
    return getattr(logging, level_name, logging.INFO)


class HttpInfoToDebugFilter(logging.Filter):
    """
    Suppress HTTP client INFO records unless the worker runs at DEBUG.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if _HTTP_INFO_ENABLED:
            return True

        if record.levelno == logging.INFO and any(
            record.name.startswith(prefix) for prefix in HTTP_LOGGER_PREFIXES
        ):
            return False
        return True


class ConditionalFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        """
        Formats a log record into a string, including timestamp, log level, and message.
        For log records with level ERROR or CRITICAL, also appends the source file path and line number.
        Args:
            record (logging.LogRecord): The log record to format.
        Returns:
            str: The formatted log message.
        """
                
        raw_log_type = getattr(record, "log_type", None)
        tag_segment = ""
        if raw_log_type:
            log_type = str(raw_log_type).strip()
            if log_type:
                if log_type.startswith("[") and log_type.endswith("]"):
                    tag_segment = f" | {log_type}"
                else:
                    tag_segment = f" | [{log_type}]"

        if record.levelno >= logging.ERROR:
            return (
                f"{self.formatTime(record)} | [{record.levelname}] | "
                f"({record.pathname}:{record.lineno}){tag_segment} | {record.getMessage()}"
            )

        return f"{self.formatTime(record)} | [{record.levelname}]{tag_segment} | {record.getMessage()}"


def _build_logging_config(log_level: int, include_file_handler: bool) -> Dict[str, Any]:
    handlers: Dict[str, Any] = {
        "console": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "level": log_level,
            "filters": ["http_info_to_debug"],
        },
    }

    if include_file_handler:
        handlers["file"] = {
            "formatter": "default",
            "class": "logging.FileHandler",
            "filename": str(LOG_FILE_PATH),
            "mode": "a",
            "encoding": "utf-8",
            "level": log_level,
            "filters": ["http_info_to_debug"],
        }

    root_handlers = ["console"] + (["file"] if include_file_handler else [])

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "http_info_to_debug": {
                "()": HttpInfoToDebugFilter,
            }
        },
        "formatters": {
            "default": {
                "()": ConditionalFormatter,
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": handlers,
        "root": {"handlers": root_handlers, "level": log_level},
    }

def setup_logging() -> None:
    global _HTTP_INFO_ENABLED

    log_level = _resolve_log_level()
    _HTTP_INFO_ENABLED = log_level <= logging.DEBUG

    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        logging.config.dictConfig(_build_logging_config(log_level, include_file_handler=True))
    except (OSError, PermissionError, ValueError):
        logging.config.dictConfig(_build_logging_config(log_level, include_file_handler=False))
        logging.getLogger(__name__).warning(
            "File logging disabled because %s is not writable",
            LOG_FILE_PATH.resolve(),
        )