import hashlib
import json
import re
import textwrap
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Document:
    document_id: str
    version: int
    customer_id: str
    project_id: str
    entity_id: str
    design_version: str
    kind: str
    status: str
    source_path: str
    effective_from: str
    observed_on: str
    body: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.body.encode()).hexdigest()

    def validate(self):
        for value in (
            self.document_id,
            self.customer_id,
            self.project_id,
            self.entity_id,
            self.kind,
            self.source_path,
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError("document identifiers must be non-empty trimmed text")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("document version must be a positive integer")
        if self.status not in {"approved", "request", "draft", "deleted"}:
            raise ValueError("unsupported document status")
        if self.kind not in {"customer_request", "engineering_change", "shipping_note"}:
            raise ValueError("unsupported document kind")
        if self.kind != "customer_request" and self.status == "request":
            raise ValueError("technical documents cannot be treated as customer requests")
        for value in (self.effective_from, self.observed_on):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("canonical YYYY-MM-DD dates required")
        if not isinstance(self.body, str) or len(self.body.encode()) > 65536:
            raise ValueError("document body must be text within 64 KiB")
        if self.status != "deleted" and not self.body.strip():
            raise ValueError("non-deleted document body must not be empty")


def load_documents(directory: Path) -> tuple[list[Document], list[dict], str]:
    manifest = json.loads((directory / "manifest.json").read_text())
    access = json.loads((directory / "access.json").read_text())
    for value in (manifest, access):
        if value.get("synthetic") is not True or value.get("format_version") != 1:
            raise ValueError("version-one synthetic RAG fixtures required")
    scopes = manifest["ownerships"]
    documents = []
    for row in manifest["documents"]:
        value = dict(row)
        path = directory / value["source_path"]
        if not path.resolve().is_relative_to(directory.resolve()) or path.suffix != ".md":
            raise ValueError("document file must be Markdown inside the fixture directory")
        if path.stat().st_size > 65536:
            raise ValueError("document file exceeds 64 KiB")
        document = Document(**value, body=path.read_text())
        document.validate()
        trusted = scopes.get(document.document_id)
        actual = [document.customer_id, document.project_id, document.entity_id]
        if trusted != actual:
            raise ValueError("document ownership does not match trusted manifest mapping")
        documents.append(document)
    as_of = manifest["as_of"]
    date.fromisoformat(as_of)
    return documents, access["grants"], as_of


def chunk_document(body: str, max_chars: int = 700) -> list[dict]:
    if max_chars < 1:
        raise ValueError("chunk size must be positive")
    section, paragraph, result = "Document", [], []

    def flush():
        if paragraph:
            text = " ".join(paragraph)
            for portion in textwrap.wrap(text, width=max_chars, break_on_hyphens=False):
                result.append({"section": section, "text": portion})
            paragraph.clear()

    for line in body.splitlines():
        line = line.strip()
        if line.startswith(">"):
            continue
        if line == "--":
            break
        if re.match(r"^#{1,6}\s", line):
            flush()
            section = re.sub(r"^#{1,6}\s+", "", line)
        elif not line:
            flush()
        else:
            paragraph.append(line)
    flush()
    return result
