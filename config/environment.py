import logging
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def redact(value):
    text = str(value)
    for name, secret in os.environ.items():
        if any(marker in name for marker in ["API_KEY", "ACCESS_TOKEN", "SECRET_KEY"]) and secret:
            text = text.replace(secret, "[REDACTED]")
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)


def secure_logging():
    previous = logging.getLogRecordFactory()
    if getattr(previous, "secure_environment", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            import traceback

            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return record

    factory.secure_environment = True
    logging.setLogRecordFactory(factory)
    for name in ["httpx", "httpcore", "openai", "huggingface_hub"]:
        logging.getLogger(name).setLevel(logging.WARNING)


def load_environment(path=None):
    if os.getenv("AGENT_MODE") == "mock" or os.getenv("ENV_FILE_DISABLED") == "true":
        secure_logging()
        return
    from dotenv import load_dotenv

    target = Path(path) if path else ROOT / ".env"
    if target.exists():
        target.chmod(0o600)
        load_dotenv(target, override=False)
    for old, new in [
        ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"),
        ("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT"),
    ]:
        if os.getenv(old) and not os.getenv(new):
            os.environ[new] = os.environ[old]
    secure_logging()
