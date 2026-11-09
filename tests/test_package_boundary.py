import ast
import socket
import tokenize
from pathlib import Path


def test_source_has_no_comments_or_docstrings():
    root = Path(__file__).resolve().parents[1]
    for directory in [
        "config",
        "mock_data",
        "data_pipeline",
        "memory",
        "rag",
        "agent",
        "evaluation",
        "deployment",
        "scripts",
        "tests",
    ]:
        for path in (root / directory).rglob("*.py"):
            with path.open("rb") as handle:
                assert not [
                    token
                    for token in tokenize.tokenize(handle.readline)
                    if token.type == tokenize.COMMENT
                ], str(path)
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    assert ast.get_docstring(node) is None, str(path)


def test_demo_needs_no_outbound_connections(tmp_path, monkeypatch):
    from scripts.demo import run

    def denied(*args, **kwargs):
        raise AssertionError("Unexpected outbound connection")

    monkeypatch.setattr(socket.socket, "connect", denied)
    report = run(tmp_path)
    assert report["external_api_calls"] == 0
    assert report["passed"] == report["cases"]
