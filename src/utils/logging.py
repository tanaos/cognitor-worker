import logging
import logging.config
from pathlib import Path
from typing import Any, Dict


LOG_FILE_PATH = Path("logs") / "cognitor-worker.log"
HTTP_LOGGER_PREFIXES = (
    "httpx",
    "httpcore",
    "urllib3",
    "aiohttp",
)


class HttpInfoToDebugFilter(logging.Filter):
    """
    Remap HTTP client INFO records to DEBUG so they are hidden at default INFO level.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO:
            return True

        if any(record.name.startswith(prefix) for prefix in HTTP_LOGGER_PREFIXES):
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"

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

LOGGING_CONFIG: Dict[str, Any] = {
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
    "handlers": {
        "console": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "level": "INFO",
            "filters": ["http_info_to_debug"],
        },
        "file": {
            "formatter": "default",
            "class": "logging.FileHandler",
            "filename": str(LOG_FILE_PATH),
            "mode": "a",
            "encoding": "utf-8",
            "level": "INFO",
            "filters": ["http_info_to_debug"],
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
}

CONSOLE_ONLY_LOGGING_CONFIG: Dict[str, Any] = {
    **LOGGING_CONFIG,
    "handlers": {
        "console": LOGGING_CONFIG["handlers"]["console"],
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

def setup_logging() -> None:
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        logging.config.dictConfig(LOGGING_CONFIG)
    except (OSError, PermissionError, ValueError):
        logging.config.dictConfig(CONSOLE_ONLY_LOGGING_CONFIG)
        logging.getLogger(__name__).warning(
            "File logging disabled because %s is not writable",
            LOG_FILE_PATH.resolve(),
        )