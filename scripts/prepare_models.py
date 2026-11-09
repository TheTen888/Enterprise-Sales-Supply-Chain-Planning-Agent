import json
import os
from pathlib import Path

from config.environment import ROOT, load_environment, redact


def prepare(root=None):
    load_environment()
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    from huggingface_hub import HfApi, snapshot_download

    root = Path(root or ROOT / "runtime/models")
    root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, repo in [
        ("embedding", "sentence-transformers/all-MiniLM-L6-v2"),
        ("reranker", "cross-encoder/ms-marco-TinyBERT-L-2-v2"),
    ]:
        info = HfApi(token=False).model_info(repo)
        destination = root / name
        snapshot_download(
            repo,
            revision=info.sha,
            local_dir=destination,
            token=False,
            allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "1_Pooling/*"],
            ignore_patterns=["onnx/*", "openvino/*"],
        )
        manifest.append(
            {
                "role": name,
                "repository": repo,
                "revision": info.sha,
                "path": str(destination),
                "bytes": sum(
                    path.stat().st_size for path in destination.rglob("*") if path.is_file()
                ),
            }
        )
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    try:
        print(json.dumps(prepare(), indent=2))
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__, "error": redact(exc)[:600]}))
        raise SystemExit(1) from None
