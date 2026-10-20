import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "provider_token": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,}|AIza[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"
    ),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
    "private_home_path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "email_address": re.compile(r"\b[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}
PRIVATE_PARTS = {
    ".git",
    ".venv",
    "artifacts",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    "secrets",
    "build",
    "dist",
}
PRIVATE_NAMES = {".DS_Store", ".Rhistory", "credentials.json", "token.json"}
PRIVATE_SUFFIXES = {".pem", ".p8", ".key", ".db", ".db-shm", ".db-wal", ".log", ".pyc"}


def scan_text(name: str, text: str, deny_terms=()) -> list[dict]:
    findings = []
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            findings.append(
                {"file": name, "rule": rule, "line": text.count("\n", 0, match.start()) + 1}
            )
    lowered = text.casefold()
    for term in deny_terms:
        if term.casefold() in lowered:
            findings.append({"file": name, "rule": "restricted_term"})
    return findings


def example_findings(text: str) -> list[dict]:
    values = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if "=" not in line:
            return [{"file": ".env.example", "rule": "invalid_example_format"}]
        key, value = line.split("=", 1)
        if key in values:
            return [{"file": ".env.example", "rule": "duplicate_example_key"}]
        values[key] = value.strip()
    failures = []
    if values.get("ALLOW_LIVE_SERVICES") != "false":
        failures.append({"file": ".env.example", "rule": "live_services_not_disabled"})
    if values.get("ALLOW_LIVE_MODEL_CALLS", "false") != "false":
        failures.append({"file": ".env.example", "rule": "live_model_calls_not_disabled"})
    for key, value in values.items():
        if key.endswith(("_TOKEN", "_KEY", "_PASSWORD", "_ACCOUNT", "_USER")) and value:
            failures.append({"file": ".env.example", "rule": "example_contains_credential_value"})
    return failures


def load_manifest(root: Path) -> list[str]:
    names = (root / "release-files.txt").read_text().splitlines()
    if not names or names != sorted(set(names)) or "release-files.txt" not in names:
        raise ValueError("release-files.txt must be sorted, unique and include itself")
    for name in names:
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != name
            or any(ord(char) < 32 for char in name)
        ):
            raise ValueError("release manifest contains an invalid relative path")
        if (
            any(part in PRIVATE_PARTS for part in path.parts)
            or path.name in PRIVATE_NAMES
            or path.suffix in PRIVATE_SUFFIXES
            or (path.name.startswith(".env") and path.name != ".env.example")
        ):
            raise ValueError("release manifest includes a private or generated file")
    return names


def git_index(root: Path):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
    except FileNotFoundError:
        return None
    if result.returncode:
        return None
    if Path(result.stdout.strip()).resolve() != root.resolve():
        raise ValueError("candidate directory must not inherit a parent Git repository")
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    )
    return set(result.stdout.decode().rstrip("\0").split("\0")) - {""}


def inspect_release(root: Path, deny_terms=()) -> dict:
    root = root.resolve()
    names = load_manifest(root)
    findings, files = [], []
    for name in names:
        path = root / name
        if (
            path.is_symlink()
            or any(parent.is_symlink() for parent in path.parents if parent != root)
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
        ):
            findings.append({"file": name, "rule": "missing_or_symlinked_file"})
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
            if "\0" in text:
                raise UnicodeError
        except UnicodeError:
            findings.append({"file": name, "rule": "non_text_file"})
            continue
        findings.extend(scan_text(name, text, deny_terms))
        if name == ".env.example":
            findings.extend(example_findings(text))
        files.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", text):
                target = target.strip("<>").split("#", 1)[0]
                if not target or target.startswith(("https:", "http:", "mailto:")):
                    continue
                destination = (path.parent / target).resolve()
                if (
                    not destination.is_relative_to(root.resolve())
                    or destination.relative_to(root.resolve()).as_posix() not in names
                ):
                    findings.append({"file": name, "rule": "link_outside_release"})
    indexed = git_index(root)
    if indexed is not None:
        for name in sorted(indexed ^ set(names)):
            findings.append({"file": name, "rule": "git_index_differs_from_manifest"})
        for name in sorted(indexed & set(names)):
            result = subprocess.run(
                ["git", "-C", str(root), "show", ":" + name], capture_output=True, check=True
            )
            try:
                staged = result.stdout.decode("utf-8")
            except UnicodeError:
                findings.append({"file": name, "rule": "non_text_git_blob"})
                continue
            findings.extend(scan_text(name, staged, deny_terms))
            if name == ".env.example":
                findings.extend(example_findings(staged))
    return {
        "passed": not findings,
        "file_count": len(files),
        "files": files,
        "findings": findings,
        "git_index_checked": indexed is not None,
        "scope": "Explicit release candidates and, when available, indexed Git blobs. Pattern and optional local deny-term checks are bounded; no complete secret-detection guarantee.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review the exact first-commit file set without initializing Git or connecting to a service"
    )
    parser.add_argument("--deny-terms-file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        terms = []
        if args.deny_terms_file:
            if args.deny_terms_file.resolve().is_relative_to(root.resolve()):
                raise ValueError("private deny terms must stay outside the candidate directory")
            terms = [
                line.strip()
                for line in args.deny_terms_file.read_text().splitlines()
                if line.strip()
            ]
        result = inspect_release(root, terms)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n")
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        parser.exit(2, "Release check could not complete; inspect the manifest and local inputs.\n")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
