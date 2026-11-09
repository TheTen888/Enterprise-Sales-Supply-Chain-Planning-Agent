import base64
import json
import runpy
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
st.set_page_config(page_title="Enterprise Sales Agent", page_icon="◈", layout="wide")
st.html("""
<style>
.stApp{background:radial-gradient(ellipse at 15% 5%,#e2eafa 0%,transparent 45%),radial-gradient(ellipse at 90% 80%,#e6f2ed 0%,transparent 45%),#f5f6fa;color:#202b40}
[data-testid="stHeader"]{display:none}
.block-container{padding:1.4rem 1.6rem 2rem;max-width:1400px}
iframe{border-radius:24px}
</style>
""")
modules = json.loads((ROOT / "app/modules.json").read_text())
for module in modules.values():
    stem = module.pop("stem")
    directory = ROOT / "docs/diagrams"
    module["image"] = (
        "data:image/png;base64,"
        + base64.b64encode((directory / f"{stem}.png").read_bytes()).decode()
    )
    module["svg"] = (
        "data:image/svg+xml;base64,"
        + base64.b64encode((directory / f"{stem}.svg").read_bytes()).decode()
    )
    module["filename"] = f"{stem}.svg"
page = (
    (ROOT / "app/architecture.html")
    .read_text()
    .replace("__MODULE_DATA__", json.dumps(modules))
    .replace("__OVERVIEW_SVG__", (ROOT / "app/overview.svg").read_text())
)
architecture, workbench = st.tabs(["System Overview", "Live Workbench"])
with architecture:
    components.html(page, height=1120, scrolling=True)
with workbench:
    runpy.run_path(str(ROOT / "evaluation/dashboard.py"), run_name="__main__")
