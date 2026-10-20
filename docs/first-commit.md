# v0.1 first-commit review

Historical v0.1 preparation record. That snapshot is now published. For the v0.2 risk-model addition, follow [Risk Model review](risk-model-review.md), [Changelog](../CHANGELOG.md) and the updated release manifest. The statements below describe the original v0.1 preparation stage.

## Candidate scope

Publish the local ETL and scoped RAG prototype, its synthetic fixtures, tests, optional API call paths and fake-client contracts. Keep ML training, risk predictions, multi-agent drafting and production cloud deployment explicitly planned. The candidate is not an enterprise deployment or evidence of business outcomes.

`release-files.txt` is an explicit, sorted list of every proposed file. A newly added file does not enter the candidate until the list is reviewed and updated. The release check also compares the list against the Git index when run inside a repository.

| Include | Exclude from the first commit |
|---|---|
| Python ETL/RAG/adapters, scripts and tests | Virtual environments, caches and generated databases |
| Invented order, mail and engineering fixtures | Real data exports, attachments and mailbox content |
| README, license notices and current design docs | Local interview notes and historical review snapshots |
| Current verification and evaluation JSON | Runtime reports under `artifacts/` |
| Empty `.env.example`, package metadata and pinned lint requirement | `.env`, OAuth tokens, private keys and credential JSON files |
| Minimal GitHub Actions workflow | Deployment jobs, cloud secrets and live API tests |

## Local checks

```bash
.venv/bin/python -m pip install -r requirements-ci.txt
.venv/bin/python -m ruff check --no-cache app pipelines rag integrations scripts tests
.venv/bin/python -m scripts.verify
.venv/bin/python -m scripts.release_check --output artifacts/release-check.json
```

The release report contains each candidate's path, size and SHA-256. It checks known credential formats, personal home paths, email addresses, missing or symlinked files, private/generated filenames, empty credentials in `.env.example`, and Markdown links that lead outside the candidate. When Git is present, indexed blobs are checked too: cleaning a working file is not enough if its staged copy still contains a detected token.

An optional local deny-term file can add confidential organization or customer names without putting those terms into source control. Keep that file outside the project and pass its path with `--deny-terms-file`. Reports contain only the rule and location, not the private terms. Detection is bounded; it cannot identify every possible credential or business secret.

## Clean candidate rehearsal

Before publication, copy only the manifest files to a temporary directory with a neutral name. Use a fresh Python 3.11 environment, install only `requirements-ci.txt` and run the same lint, verification and release commands there.

A temporary Git index can verify that `git add --all` selects exactly the manifest and ignores fake `.env`, database, key, cache and interview-note probes. That isolated index is discarded after the rehearsal. It does not initialize this working project, make a commit, configure a remote or push anything.

## CI boundaries

The workflow uses push, pull-request and manual triggers. It checks out source with credential persistence disabled, grants only `contents: read`, installs pinned Ruff, and runs local verification and release checks. It has a ten-minute timeout and cancels obsolete runs. It has no secrets, deployment, artifact upload or cloud integration step.

The pinned action references were resolved from the official release tags `actions/checkout v7.0.1` and `actions/setup-python v7.0.0`. Consult the [checkout release](https://github.com/actions/checkout/releases/tag/v7.0.1), [setup-python release](https://github.com/actions/setup-python/releases/tag/v7.0.0) and [GitHub secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use) when deliberately updating them.

Local rehearsal verifies the commands and file set. GitHub event handling, hosted-runner behavior and branch protection remain unverified until the first authorized remote run. Action/tool installation needs public network access; business-data processing remains local.

## Review before the first push

Review the README scope, exact manifest, current verification and local release report. Confirm that no real data or credentials were supplied and that the original reference project was not edited. The first commit should describe the local implementation, for example `Initial local ETL and scoped RAG prototype`.

For initial staging, use `git add --pathspec-from-file=release-files.txt`, then rerun the release check against the index before committing. A changed candidate file requires a fresh review report.

Local Git initialization and the first commit have been authorized for this v0.1 candidate. The project display name is Enterprise Sales & Supply Chain Planning Agent; its technical package identifier is `enterprise-sales-supply-chain-planning-agent`. This stage does not configure a remote, publish a repository or push to GitHub. Remote publication is a later authorized step.
