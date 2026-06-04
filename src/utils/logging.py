import logging
import logging.config
import os
from typing import Dict, Any


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

        # Display pathname + lineno only for ERROR and CRITICAL
        if record.levelno >= logging.ERROR:
            return f"{self.formatTime(record)} | [{record.levelname}] | ({record.pathname}:{record.lineno}){tag_segment} | {record.getMessage()}"
        
        return f"{self.formatTime(record)} | [{record.levelname}]{tag_segment} | {record.getMessage()}"

LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
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
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logging.config.dictConfig(LOGGING_CONFIG)