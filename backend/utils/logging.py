"""
JSON log formatter for production use.

Outputs one JSON object per line with consistent fields so log aggregators
(Splunk, ELK, Datadog, CloudWatch) can parse and index every record.
"""
import json
import logging
import traceback
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }

        if record.exc_info:
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info))

        # Allow callers to attach extra structured fields:
        #   logger.info("sync done", extra={"connector": "crowdstrike", "created": 5})
        for key, value in record.__dict__.items():
            if key not in (
                "args", "created", "exc_info", "exc_text", "filename",
                "funcName", "id", "levelname", "levelno", "lineno",
                "module", "msecs", "message", "msg", "name", "pathname",
                "process", "processName", "relativeCreated", "stack_info",
                "thread", "threadName", "taskName",
            ) and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_json_logging(debug: bool = False) -> None:
    """Replace the root handler with a JSON formatter."""
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Keep SQLAlchemy and uvicorn access logs at WARNING in production
    if not debug:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
