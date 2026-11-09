import json
import shutil
from pathlib import Path

import resvg_py

ROOT = Path(__file__).resolve().parents[1]


def export():
    assets = ROOT / "docs/assets"
    assets.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "docs/diagrams").glob("*.*"):
        if path.suffix in {".svg", ".png"}:
            shutil.copy2(path, assets / path.name)
    svg = (ROOT / "app/overview.svg").read_text()
    (assets / "overview.svg").write_text(svg)
    (assets / "overview.png").write_bytes(resvg_py.svg_to_bytes(svg_string=svg, width=3960))
    modules = json.loads((ROOT / "app/modules.json").read_text())
    for module in modules.values():
        stem = module.pop("stem")
        module.update(image=f"assets/{stem}.png", svg=f"assets/{stem}.svg", filename=f"{stem}.svg")
    site = ROOT / "docs/site"
    site.mkdir(parents=True, exist_ok=True)
    page = (ROOT / "app/architecture.html").read_text()
    page = page.replace("__MODULE_DATA__", json.dumps(modules)).replace("__OVERVIEW_SVG__", svg)
    (site / "index.html").write_text(page)
    shutil.copytree(assets, site / "assets", dirs_exist_ok=True)


if __name__ == "__main__":
    export()
