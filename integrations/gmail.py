import base64
import binascii
import re

from integrations.settings import require_live
from integrations.snowflake import ProviderError
from rag.documents import Document

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GmailReader:
    def __init__(self, client, ownerships: dict):
        self.client = client
        self.ownerships = dict(ownerships)

    def fetch_document(
        self, message_id: str, *, version: int, design: str, effective_on: str, observed_on: str
    ) -> Document:
        if not isinstance(message_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", message_id):
            raise ValueError("invalid Gmail message identifier")
        scope = self.ownerships.get(message_id)
        if (
            not isinstance(scope, tuple)
            or len(scope) != 3
            or not all(isinstance(value, str) and value.strip() for value in scope)
        ):
            raise PermissionError("message has no trusted customer/project/order mapping")
        try:
            message = (
                self.client.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute(num_retries=0)
            )
        except Exception:
            raise ProviderError("Gmail read failed; credentials and message body omitted") from None
        if message.get("id") != message_id:
            raise ProviderError("Gmail returned a different message")
        pieces, nodes = [], [message.get("payload", {})]
        visited = total = 0
        while nodes:
            node = nodes.pop()
            visited += 1
            if visited > 100:
                raise ProviderError("Gmail MIME structure exceeds the supported bound")
            if node.get("mimeType") == "text/plain" and not node.get("filename"):
                data = node.get("body", {}).get("data", "")
                if not isinstance(data, str) or len(data) > 90000:
                    raise ProviderError("Gmail text part exceeds the supported bound")
                try:
                    raw = base64.b64decode(
                        data + "=" * (-len(data) % 4), altchars=b"-_", validate=True
                    )
                    total += len(raw)
                    if total > 65536:
                        raise ProviderError("Gmail plain text exceeds 64 KiB")
                    pieces.append(raw.decode("utf-8"))
                except (UnicodeDecodeError, binascii.Error):
                    raise ProviderError("Gmail plain text could not be decoded") from None
            nodes.extend(reversed(node.get("parts", [])))
        if not pieces:
            raise ProviderError("plain-text message required; HTML and attachments are not parsed")
        document = Document(
            document_id="GMAIL-" + message_id,
            version=version,
            customer_id=scope[0],
            project_id=scope[1],
            entity_id=scope[2],
            design_version=design,
            kind="customer_request",
            status="request",
            source_path="gmail:" + message_id,
            effective_from=effective_on,
            observed_on=observed_on,
            body="\n\n".join(pieces),
        )
        document.validate()
        return document


def open_gmail(oauth_token: str, ownerships: dict, *, allow_live: bool = False) -> GmailReader:
    require_live(allow_live)
    if not isinstance(oauth_token, str) or not oauth_token.strip():
        raise ValueError("Gmail OAuth token required")
    try:
        import httplib2
        from google.oauth2.credentials import Credentials
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build

        credentials = Credentials(token=oauth_token, scopes=[READONLY_SCOPE])
        client = build(
            "gmail",
            "v1",
            http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=15)),
            cache_discovery=False,
            static_discovery=True,
        )
        return GmailReader(client, ownerships)
    except ImportError:
        raise ProviderError("install the optional gmail dependencies first") from None
    except Exception:
        raise ProviderError("Gmail initialization failed; credentials omitted") from None
