import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\blsv2_[A-Za-z0-9_-]{20,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def scan():
    secrets = []
    if (ROOT / ".env").exists():
        from dotenv import dotenv_values

        secrets = [
            v.encode()
            for k, v in dotenv_values(ROOT / ".env").items()
            if v and any(t in k for t in ("KEY", "TOKEN", "SECRET"))
        ]
    staged = git("ls-files", "-s", "-z").split(b"\0")
    objects = {}
    for entry in staged:
        if entry:
            meta, path = entry.split(b"\t", 1)
            objects[meta.split()[1].decode()] = path.decode()
    history = git("rev-list", "--objects", "--all").splitlines()
    for entry in history:
        oid, _, path = entry.partition(b" ")
        objects.setdefault(oid.decode(), path.decode(errors="replace"))
    findings = []
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    blobs = 0
    for oid, path in objects.items():
        proc.stdin.write((oid + "\n").encode())
        proc.stdin.flush()
        header = proc.stdout.readline().split()
        size = int(header[2])
        content = proc.stdout.read(size)
        proc.stdout.read(1)
        if header[1] == b"blob":
            blobs += 1
            if any(p.search(content) for p in PATTERNS) or any(s in content for s in secrets):
                findings.append({"object": oid, "path": path})
    proc.stdin.close()
    proc.wait()
    tracked = git("ls-files", "-z").split(b"\0")
    env_ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode == 0
    forbidden = [
        p.decode()
        for p in tracked
        if p and (p == b".env" or p.startswith((b"runtime/", b".venv/")))
    ]
    report = {
        "scope": "Staged files and all reachable Git history",
        "scanned_objects": len(objects),
        "scanned_blobs": blobs,
        "credential_findings": findings,
        "forbidden_tracked_paths": forbidden,
        "env_git_ignored": env_ignored,
        "passed": not findings and not forbidden and env_ignored,
    }
    (ROOT / "docs/git_security_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    scan()
