import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.venv', '.git', 'runtime', '__pycache__', '.pytest_cache', '.ruff_cache'}


def scan():
    patterns = [re.compile(rb'\bsk-[A-Za-z0-9_-]{12,}'), re.compile(rb'\blsv2_[A-Za-z0-9_-]{12,}'), re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
    from dotenv import dotenv_values

    secrets = [v.encode() for k, v in dotenv_values(ROOT / '.env').items() if v and ('KEY' in k or 'TOKEN' in k or 'SECRET' in k)]
    paths = [p for p in ROOT.rglob('*') if p.is_file() and not any(part in EXCLUDED or part.endswith('.egg-info') for part in p.relative_to(ROOT).parts) and (not p.name.startswith('.env') or p.name == '.env.example')]
    findings = []
    for path in paths:
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in patterns) or any(secret in content for secret in secrets):
            findings.append(str(path.relative_to(ROOT)))
    with tempfile.TemporaryDirectory() as temp:
        subprocess.run(['git', 'init', '-q', temp], check=True)
        Path(temp, '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
        ignored = subprocess.run(['git', '-C', temp, 'check-ignore', '-q', '.env']).returncode == 0
    report = {'scope': 'Release candidate files; runtime, credentials and dependencies excluded', 'scanned_files': len(paths), 'credential_findings': findings, 'env_git_ignored': ignored, 'env_mode': oct((ROOT / '.env').stat().st_mode & 0o777), 'passed': not findings and ignored, 'publication_performed': False}
    destination = ROOT / 'docs/security_scan.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    scan()
