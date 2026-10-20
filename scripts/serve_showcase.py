import argparse
import json
import tempfile
from pathlib import Path

from agents.store import DraftStore
from agents.workflow import DraftWorkflow
from app.eval_dashboard import make_server
from app.showcase import Showcase
from rag.retrieval import EvidenceService
from rag.store import KnowledgeStore
from scripts.run_agents import prepare


def open_showcase(root, model_path=None, resume=False):
    if resume:
        workflow = DraftWorkflow(
            EvidenceService(
                KnowledgeStore(root / "inputs/knowledge.db"), root / "inputs/etl/warehouse.db"
            ),
            DraftStore(root / "drafts.db"),
            json.loads((root / "scenario.json").read_text()),
            json.loads((root / "model.json").read_text()),
        )
        with workflow.store.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1"
            ).fetchone():
                raise ValueError("unfinished worker job; use a fresh workspace for this local demo")
    else:
        workflow, config = prepare(root, model_path)
        (root / "scenario.json").write_text(json.dumps(config, indent=2) + "\n")
    return Showcase(workflow, root)


def main():
    parser = argparse.ArgumentParser(description="Open the zero-cost local decision showcase")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    if args.resume and args.model:
        parser.error("choose --resume or --model")
    if args.resume:
        workspace = args.resume.resolve()
        if not workspace.is_relative_to(artifacts) or not workspace.is_dir():
            parser.error("resume must select an existing workspace under artifacts")
    else:
        workspace = Path(tempfile.mkdtemp(prefix="showcase-", dir=artifacts))
    showcase = open_showcase(workspace, args.model, bool(args.resume))
    try:
        server = make_server(root, args.port, showcase=showcase)
    except BaseException:
        showcase.close()
        raise
    print(f"Decision Workspace: http://127.0.0.1:{server.server_port}/workbench", flush=True)
    print(f"Evaluation Studio: http://127.0.0.1:{server.server_port}/#agents", flush=True)
    print(f"Session: {workspace.relative_to(root)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        showcase.close()


if __name__ == "__main__":
    main()
