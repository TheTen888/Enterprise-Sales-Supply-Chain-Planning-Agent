import hashlib
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from pipelines.etl.models import digest

SOURCE_DIRS = (
    "app",
    "pipelines",
    "rag",
    "risk_model",
    "agents",
    "integrations",
    "scripts",
    "tests",
)


def source_inventory(root):
    files = {
        str(path.relative_to(root)): path
        for directory in SOURCE_DIRS
        for path in (root / directory).rglob("*.py")
    }
    files.update(
        {
            str(path.relative_to(root)): path
            for path in (root / "app/eval_ui").glob("*")
            if path.suffix in {".html", ".js", ".css"}
        }
    )
    files.update(
        {
            str(path.relative_to(root)): path
            for path in (root / "data").rglob("*")
            if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}
        }
    )
    return files


def snapshot(root):
    root = Path(root)
    evidence = json.loads((root / "docs/evidence/verification.json").read_text())
    if (
        not isinstance(evidence, dict)
        or type(evidence.get("passed")) is not bool
        or not isinstance(evidence.get("unit_tests"), dict)
        or not isinstance(evidence.get("source_sha256"), dict)
        or not isinstance(evidence.get("verified_at_utc"), str)
    ):
        raise ValueError("invalid verification evidence")
    recorded = evidence.get("source_sha256", {})
    current = source_inventory(root)
    mismatches = sorted(set(current) ^ set(recorded))
    mismatches += [
        name
        for name in current.keys() & recorded.keys()
        if hashlib.sha256(current[name].read_bytes()).hexdigest() != recorded[name]
    ]
    local_state = {"uncommitted_changes": None, "commit": None}
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if status.returncode == commit.returncode == 0:
            local_state = {
                "uncommitted_changes": bool(status.stdout.strip()),
                "commit": commit.stdout.strip(),
            }
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "schema_version": 1,
        "snapshot_id": digest(evidence),
        "verified_at_utc": evidence.get("verified_at_utc"),
        "evidence": evidence,
        "freshness": {
            "current": bool(recorded) and not mismatches,
            "mismatched_files": sorted(set(mismatches)),
        },
        "local_state": local_state,
        "mode": "Read-only local evaluation",
        "limits": [
            "Synthetic data and deterministic roles",
            "Recorded evaluation, not live production telemetry",
            "Fault rejection is an expected test outcome",
            "No LLM groundedness or production quality claim",
            "Model remains unpromoted; customer dispatch is disabled",
        ],
    }


def make_server(root, port=8768, host="127.0.0.1", showcase=None):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("dashboard must bind to loopback")
    root = Path(root).resolve()
    assets = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.css": ("app.css", "text/css; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    }
    if showcase is not None:
        assets.update(
            {
                "/workbench": ("workbench.html", "text/html; charset=utf-8"),
                "/workbench.js": ("workbench.js", "text/javascript; charset=utf-8"),
                "/workbench.css": ("workbench.css", "text/css; charset=utf-8"),
            }
        )

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def local_host(self):
            allowed = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            return self.headers.get("Host") in allowed

        def do_GET(self):
            if not self.local_host():
                self.send(403, b'{"error":"local host required"}')
                return
            path = urlsplit(self.path).path
            if path == "/health":
                self.send(
                    200,
                    json.dumps({"status": "ok", "read_only": showcase is None}).encode(),
                )
            elif (
                path in {"/api/showcase", "/api/showcase/export", "/api/monitor"}
                and showcase is not None
            ):
                try:
                    body = (
                        showcase.export()
                        if path.endswith("export")
                        else json.dumps(
                            showcase.monitor() if path == "/api/monitor" else showcase.state(),
                            allow_nan=False,
                        ).encode()
                    )
                    self.send(200, body)
                except PermissionError:
                    self.send(403, b'{"error":"Demo scope access denied"}')
                except (ValueError, LookupError):
                    self.send(409, b'{"error":"Demo evidence changed or is unavailable"}')
                except Exception:
                    self.send(500, b'{"error":"Local demo state unavailable"}')
            elif path == "/api/evaluation":
                try:
                    body = json.dumps(
                        {**snapshot(root), "showcase_enabled": showcase is not None},
                        allow_nan=False,
                    ).encode()
                    self.send(200, body)
                except (OSError, ValueError, TypeError, KeyError):
                    self.send(
                        503,
                        b'{"error":"Evaluation evidence unavailable. Run scripts.verify --agents first."}',
                    )
            elif path in assets:
                filename, content_type = assets[path]
                try:
                    self.send(200, (root / "app/eval_ui" / filename).read_bytes(), content_type)
                except OSError:
                    self.send(404, b'{"error":"asset unavailable"}')
            else:
                self.send(404, b'{"error":"not found"}')

        def do_POST(self):
            if showcase is None or urlsplit(self.path).path != "/api/showcase/actions":
                self.send(405, b'{"error":"read-only dashboard"}')
                return
            if (
                not self.local_host()
                or self.headers.get("Origin") != "http://" + self.headers.get("Host", "")
                or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json"
            ):
                self.send(403, b'{"error":"Same-origin local JSON request required"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    self.send(413, b'{"error":"Request body must be 1 to 4096 bytes"}')
                    return
                command = json.loads(self.rfile.read(length))
                result = showcase.act(command)
                self.send(200, json.dumps(result, allow_nan=False).encode())
            except PermissionError:
                self.send(403, b'{"error":"Demo scope access denied"}')
            except LookupError:
                self.send(404, b'{"error":"Draft not found"}')
            except (ValueError, TypeError) as exc:
                self.send(409, json.dumps({"error": str(exc)}).encode())
            except Exception:
                self.send(500, b'{"error":"Local demo action failed; inspect recorded events"}')

    return ThreadingHTTPServer((host, port), Handler)
