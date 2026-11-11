"""Request-scoped structured logging.

Every log line carries the trace id of the request it belongs to, so one trip-plan
request can be followed across the API layer, the LangGraph pipeline, the LLM call
and every AMap call.

Output format:
  * ``LOG_FORMAT=json``          -> one JSON object per line (use in production)
  * anything else (default)      -> ``timestamp LEVEL [trace=...] logger :: event key=value``
"""

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

LOGGER_ROOT = "src"
_FIELDS_ATTR = "fields"
_MAX_FIELD_CHARS = 300

_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="-")
_configured = False


def get_trace_id() -> str:
    """Return the trace id bound to the current request, or ``-`` outside a request."""
    return _TRACE_ID.get()


def set_trace_id(value: str) -> Token[str]:
    return _TRACE_ID.set(value)


def reset_trace_id(token: Token[str]) -> None:
    _TRACE_ID.reset(token)


def mask_secret(value: str) -> dict[str, Any]:
    """Describe a secret without ever exposing it."""
    return {"set": bool(value), "length": len(value or "")}


_SECRET_QUERY = re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token)=)[^&\s\"']+")


def redact_secrets(text: str) -> str:
    """Strip API keys out of URLs that end up in error messages.

    httpx puts the full request URL (including ``key=...``) into its exception
    text, so anything that logs ``str(exc)`` would leak the credential.
    """
    return _SECRET_QUERY.sub(r"\1***", text)


def _compact(value: Any) -> Any:
    if isinstance(value, str):
        value = redact_secrets(value)
        return value if len(value) <= _MAX_FIELD_CHARS else f"{value[:_MAX_FIELD_CHARS]}..."
    if isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return redact_secrets(str(value))[:_MAX_FIELD_CHARS]
        text = redact_secrets(text)
        return text if len(text) <= _MAX_FIELD_CHARS else f"{text[:_MAX_FIELD_CHARS]}..."
    return value


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    fields = getattr(record, _FIELDS_ATTR, None)
    return dict(fields) if isinstance(fields, dict) else {}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "trace_id": get_trace_id(),
        }
        payload.update(_fields(record))
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} {record.levelname:<7} [trace={get_trace_id()}] {record.name} :: {record.getMessage()}"
        pairs = " ".join(f"{key}={value}" for key, value in _fields(record).items())
        if pairs:
            line = f"{line} {pairs}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str = "INFO", fmt: str = "text", force: bool = False) -> None:
    """Install one stdout handler on the ``src.*`` logger tree.

    uvicorn keeps its own handlers, so its access/error lines stay untouched.
    """
    global _configured
    if _configured and not force:
        return

    stream = _utf8_stdout()
    handler = logging.StreamHandler(stream=stream)
    handler.setFormatter(JsonFormatter() if fmt.lower() == "json" else TextFormatter())

    logger = logging.getLogger(LOGGER_ROOT)
    logger.handlers = [handler]
    logger.setLevel(level.upper())
    logger.propagate = False
    _configured = True


def _utf8_stdout():
    """Windows consoles default to a legacy codec; force UTF-8 so Chinese survives."""
    stream = sys.stdout
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    # ``reconfigure`` is not part of the ``TextIO`` protocol, so fetch it through
    # getattr: a redirected or replaced stdout may not provide it at all.
    reconfigure = getattr(stream, "reconfigure", None)
    if "utf8" in encoding or reconfigure is None:
        return stream
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return stream
    return stream


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Emit one structured event. Extra keywords become structured fields."""
    if not logger.isEnabledFor(level):
        return
    logger.log(
        level,
        event,
        extra={_FIELDS_ATTR: {key: _compact(value) for key, value in fields.items()}},
        exc_info=exc_info,
    )
