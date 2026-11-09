import base64
from html import escape
from pathlib import Path

from scripts.render_architecture import Diagram

ROOT = Path(__file__).resolve().parents[1]
BRANDS = ROOT / "docs/diagrams/brands"


def icon(name, color):
    paths = list(BRANDS.glob(name + ".svg")) + list(BRANDS.glob(name + ".png"))
    if not paths:
        return None
    path = paths[0]
    data = path.read_bytes()
    if path.suffix == ".svg":
        data = data.decode().replace("<svg ", f'<svg fill="{color}" ').encode()
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    return "data:" + mime + ";base64," + base64.b64encode(data).decode()


def overview():
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1320" height="960" viewBox="0 0 1320 960" role="group" aria-label="Enterprise sales agent architecture"><defs><marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#526779"/></marker></defs><g font-family="Arial,Helvetica,sans-serif">'
    ]

    def text(x, y, value, size=16, color="#354b60", anchor="middle", weight=400):
        parts.append(
            f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>'
        )

    def frame(y, h, title):
        parts.append(
            f'<rect x="25" y="{y}" width="1270" height="{h}" rx="15" fill="#f6f9fc" fill-opacity=".8" stroke="#bdcad8" stroke-width="1.2"/>'
        )
        text(47, y + 29, title, 18, "#42596d", "start", 600)

    def badge(x, y, label, key, color="#527a9a"):
        width = 34 + len(label) * 7
        parts.append(
            f'<rect x="{x}" y="{y - 19}" width="{width}" height="27" rx="8" fill="white" stroke="#d9e2eb"/>'
        )
        src = icon(key, color)
        if src:
            parts.append(f'<image href="{src}" x="{x + 6}" y="{y - 15}" width="19" height="19"/>')
        else:
            parts.append(
                f'<rect x="{x + 6}" y="{y - 14}" width="17" height="17" rx="4" fill="{color}"/>'
            )
            text(x + 14.5, y - 1, label[0], 12, "white", weight=600)
        text(x + 30, y, label, 12, color, "start", 600)
        return width

    def badges(x, y, items):
        for label, key, color in items:
            x += badge(x, y, label, key, color) + 9

    def node(x, y, w, h, lines, view, color="#315e7b", size=17):
        parts.append(
            f'<g class="diagram-link" role="button" tabindex="0" data-view="{view}" aria-label="Open {escape(lines[0])} system design"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{color}" stroke="white" stroke-opacity=".65"/>'
        )
        start = y + h / 2 - (len(lines) - 1) * 12 + 6
        for i, line in enumerate(lines):
            text(x + w / 2, start + i * 24, line, size if i == 0 else 13, "white", weight=500)
        parts.append(
            f'<circle cx="{x + w - 3}" cy="{y + 3}" r="14" fill="white" stroke="#d5e0e9"/>'
        )
        text(x + w - 3, y + 9, "↗", 21, "#527998")
        parts.append("</g>")

    def flow(points, both=False, dash=False):
        parts.append(
            '<polyline points="'
            + " ".join(f"{x},{y}" for x, y in points)
            + '" fill="none" stroke="#526779" stroke-width="1.6" marker-end="url(#flow-arrow)"'
            + (' marker-start="url(#flow-arrow)"' if both else "")
            + (' stroke-dasharray="5 5"' if dash else "")
            + "/>"
        )

    text(660, 28, "Enterprise AI Agent Sales & Risk System Architecture", 21, weight=600)
    frame(50, 320, "01  Data Ingestion & ML Risk Pipeline")
    badge(55, 112, "AWS S3", "s3", "#728c3b")
    badge(310, 112, "openpyxl", "openpyxl", "#427c59")
    badges(640, 110, [("Inngest", "inngest", "#ad675d"), ("Pydantic", "pydantic", "#c45977")])
    node(55, 130, 210, 58, ["Raw Data Sources", "S3 / ERP / ECN"], "rag")
    node(310, 130, 245, 58, ["Two-Lane Routing", "Local vs Server"], "rag")
    parts.append(
        '<rect x="610" y="120" width="650" height="78" rx="12" fill="#eaf1f6" stroke="#bfd1e0"/>'
    )
    for i, label in enumerate(
        ["1. Fetch", "2. Convert", "3. Chunk", "4. Embed", "5. Idempotent Upsert"]
    ):
        x = 625 + i * 125
        node(x, 138, 130 if i == 4 else 112, 44, [label], "rag", size=11 if i == 4 else 12)
        if i < 4:
            flow([(x + 112, 160), (x + 125, 160)])
    flow([(265, 159), (310, 159)])
    flow([(555, 159), (625, 159)])
    badges(
        385,
        243,
        [
            ("AWS SageMaker", "sagemaker", "#7853a8"),
            ("XGBoost", "xgboost", "#df7a32"),
            ("MLflow", "mlflow", "#2873ae"),
        ],
    )
    node(
        385,
        265,
        840,
        81,
        [
            "Order Delay Early Warning System",
            "Rolling Time-Series Features · Temporal Splits · Delay Risk Scoring",
            "Target: Recall 55% → 85% · 5-day earlier warning",
        ],
        "ml",
        size=20,
    )
    flow([(345, 220), (345, 305), (385, 305)])
    frame(390, 330, "02  Memory System & Multi-Agent")
    flow([(1255, 160), (1276, 160), (1276, 220), (12, 220), (12, 499), (55, 499)])
    flow([(885, 346), (885, 500)])
    text(941, 427, "Delay risk score", 13, "#58798e")
    node(55, 470, 270, 58, ["Hybrid RAG", "BM25 + Vector + Cross-Encoder"], "retrieval")
    node(
        55,
        590,
        270,
        58,
        ["Memory System", "Working · Episodic · Semantic · Procedural"],
        "memory",
        size=17,
    )
    badge(65, 677, "Redis / RedisVL", "redis", "#b75757")
    flow([(325, 499), (352, 499), (352, 525), (385, 525)])
    node(385, 500, 155, 50, ["Triage Router"], "agents")
    badges(595, 482, [("LangGraph", "langgraph", "#397e66"), ("A2A Protocol", "a2a", "#567b9e")])
    node(600, 500, 150, 50, ["QuoteAgent"], "agents")
    node(802, 500, 165, 50, ["CapacityAgent"], "agents")
    flow([(540, 525), (600, 525)])
    flow([(750, 525), (802, 525)], both=True)
    flow([(325, 619), (559, 619), (559, 540), (600, 540)])
    node(1060, 500, 200, 50, ["Risk Supervisor"], "agents", color="#616e7c")
    flow([(967, 525), (1060, 525)])
    node(1060, 620, 200, 58, ["Manager Review", "Human-in-the-Loop"], "agents", color="#167868")
    flow([(1160, 550), (1160, 620)])
    flow([(1060, 649), (718, 649), (718, 550)], dash=True)
    text(880, 680, "Follow-up / Recompute", 13, "#58798e")
    frame(745, 190, "03  Evaluation")
    node(
        50,
        795,
        295,
        99,
        ["Agent Tracing & Debugging", "with LangSmith", "Waterfall · Tokens · Latency"],
        "tracing",
        color="#616e7c",
        size=16,
    )
    node(
        365,
        795,
        295,
        99,
        ["Automated Agent Evaluation", "Benchmark · Simulation", "Business Assertions (23/23)"],
        "eval",
        color="#616e7c",
        size=16,
    )
    node(
        680,
        795,
        285,
        99,
        ["Agent Security", "Input / Output / Tool Guardrails", "Injection · Alignment · Access"],
        "security",
        color="#616e7c",
        size=17,
    )
    node(
        985,
        795,
        285,
        99,
        ["Agent Deployment", "Managed Microservice Runtime", "@app.entrypoint · HTTP APIs"],
        "deployment",
        color="#616e7c",
        size=17,
    )
    badge(62, 921, "LangSmith", "langsmith", "#397e66")
    badges(377, 921, [("IntellAgent", "intellagent", "#8b68ac"), ("Pytest", "pytest", "#4779aa")])
    badge(692, 921, "LlamaFirewall", "meta", "#327bd2")
    badges(
        997, 921, [("AWS Bedrock AgentCore", "bedrock", "#4d9987"), ("Docker", "docker", "#2581bd")]
    )
    parts.append("</g></svg>")
    (ROOT / "app/overview.svg").write_text("\n".join(parts))


def ml():
    d = Diagram("Order Delay Early Warning System", 1080)
    d.frame(40, 90, 1520, 315, "Point-in-Time Data & Features")
    d.box(75, 195, 265, 100, ["Historical Orders", "Capacity · Schedule · ECN"], "#d5e8d4", 18)
    d.box(
        440,
        190,
        330,
        110,
        [
            "Rolling Time-Series Features",
            "Load · Yield · Schedule Slack",
            "Allocation · Pickup Gap",
        ],
        size=18,
    )
    d.box(
        875,
        190,
        285,
        110,
        ["Temporal Splits", "Train → Validate → Test", "Purge immature labels"],
        size=18,
    )
    d.box(
        1260,
        190,
        260,
        110,
        ["Frozen Label", "Late vs original promise", "Confirmed delivery outcome"],
        size=17,
    )
    d.arrow([(340, 245), (440, 245)])
    d.arrow([(770, 245), (875, 245)])
    d.arrow([(1390, 300), (1390, 365), (1015, 365), (1015, 300)])
    d.text(575, 365, ["Only facts observed by prediction time"], 18)
    d.frame(40, 440, 1520, 440, "Training, Evaluation & Scoring")
    d.ellipse(875, 515, 285, 110, ["XGBoost Training", "AWS SageMaker"], 19)
    d.arrow([(1015, 300), (1015, 515)])
    d.box(
        450,
        515,
        300,
        110,
        ["Calibration & Baseline Eval", "Separate validation window", "Fixed alert budget"],
        size=18,
    )
    d.arrow([(875, 570), (750, 570)])
    d.box(85, 515, 250, 110, ["Model Registry", "MLflow · Approved version"], size=18)
    d.arrow([(450, 570), (335, 570)])
    d.box(85, 725, 250, 95, ["Batch Risk Scoring", "Snowflake"], size=18)
    d.arrow([(210, 625), (210, 725)])
    d.box(
        450,
        725,
        300,
        95,
        ["Order Delay Risk Score", "Probability · As-of · Model ID"],
        "#d5e8d4",
        18,
    )
    d.arrow([(335, 772), (450, 772)])
    d.ellipse(875, 715, 285, 115, ["Multi-Agent Context", "CapacityAgent + Supervisor"], 18)
    d.arrow([(750, 772), (875, 772)])
    d.box(1260, 725, 260, 95, ["Manager Review", "Reschedule · Escalate"], "#d5e8d4", 18)
    d.arrow([(1160, 772), (1260, 772)])
    d.text(800, 933, ["Design target: Recall 55% → 85% · Alerts 5 days earlier"], 19, True)
    d.footer(
        "ML Eval",
        "Recall / Precision at Fixed Alert Budget · Calibration · Temporal Leakage Checks",
    )
    d.save("ml_risk_architecture")


def security():
    d = Diagram("Agent Security · LlamaFirewall Integration Design")
    d.box(60, 145, 250, 85, ["User Input"], "#d5e8d4")
    d.frame(390, 90, 1150, 430, "LlamaFirewall + Application Policy Enforcement")
    d.box(435, 145, 285, 85, ["Prompt Injection", "PromptGuard · Input scan"], size=18)
    d.box(835, 145, 285, 85, ["PII Check", "Configured privacy policy"], size=18)
    d.arrow([(310, 187), (435, 187)])
    d.arrow([(720, 187), (835, 187)])
    d.box(
        835,
        350,
        285,
        95,
        ["Tool Validation", "Schema · Allowlist · Scope", "Authorization before execution"],
        size=17,
    )
    d.arrow([(978, 230), (978, 350)])
    d.box(435, 350, 285, 95, ["Behavior Alignment", "Task-bound execution"], size=18)
    d.arrow([(835, 398), (720, 398)])
    d.box(60, 610, 250, 95, ["Output Validation", "Evidence · PII · Business Rules"], size=17)
    d.arrow([(435, 398), (350, 398), (350, 570), (185, 570), (185, 610)])
    d.diamond(435, 590, 285, 135, ["All checks pass?"])
    d.arrow([(310, 657), (435, 657)])
    d.box(850, 610, 285, 95, ["Final Response"], "#d5e8d4")
    d.arrow([(720, 657), (850, 657)])
    d.text(785, 637, ["Yes"], 17)
    d.box(435, 815, 285, 85, ["Block / Redact / Review"], size=18)
    d.arrow([(577, 725), (577, 815)])
    d.text(620, 780, ["No"], 17)
    d.text(1000, 855, ["Each failed stage stops before execution."], 18)
    d.footer(
        "Security Eval",
        "Attack Block Rate · False Positives · Scope Isolation · Sensitive Data Exposure",
    )
    d.save("agent_security_architecture")


def tracing():
    d = Diagram("Agent Tracing & Debugging with LangSmith")
    d.box(70, 170, 250, 90, ["Agent Request"], "#d5e8d4")
    d.ellipse(470, 155, 290, 120, ["LangGraph Execution", "Router · Quote · Capacity"], 18)
    d.box(
        925,
        160,
        300,
        110,
        ["Model & Tool Spans", "Inputs · Outputs · Duration", "Tokens · Errors"],
        size=18,
    )
    d.arrow([(320, 215), (470, 215)])
    d.arrow([(760, 215), (925, 215)])
    d.db(925, 425, 300, 155, ["LangSmith", "Run IDs & Waterfall"])
    d.arrow([(1075, 270), (1075, 425)])
    d.box(
        460,
        440,
        310,
        110,
        ["Root-Cause Diagnosis", "Data → Retrieval → Tools", "→ Final Decision"],
        size=18,
    )
    d.arrow([(925, 495), (770, 495)])
    d.box(70, 440, 250, 110, ["Versioned Replay", "Same evidence & inputs"], size=18)
    d.arrow([(460, 495), (320, 495)])
    d.box(460, 755, 310, 95, ["Regression Case", "Fix → Re-evaluate"], "#d5e8d4", 18)
    d.arrow([(195, 550), (195, 802), (460, 802)])
    d.arrow([(615, 755), (615, 550)])
    d.footer(
        "Telemetry Metrics", "Error Rate · P95 Latency · Tokens / Request · Cost / Completed Task"
    )
    d.save("agent_tracing_architecture")


def automated_eval():
    d = Diagram("Automated Agent Evaluation")
    d.frame(40, 90, 1520, 300, "Benchmark → Simulation → Assertions")
    d.box(
        80,
        185,
        320,
        110,
        ["Benchmark Synthesis", "5 fixtures + 18 edge cases", "IntellAgent integration design"],
        size=18,
    )
    d.ellipse(580, 170, 340, 140, ["Multi-Turn Simulation", "Real Model Execution"], 19)
    d.box(
        1100,
        185,
        360,
        110,
        ["Business Assertions", "Pytest · Independent Judge", "Quote math · ECN · Capacity"],
        size=18,
    )
    d.arrow([(400, 240), (580, 240)])
    d.arrow([(920, 240), (1100, 240)])
    d.diamond(1110, 510, 340, 160, ["Release criteria met?"])
    d.arrow([(1280, 295), (1280, 510)])
    d.box(
        580,
        545,
        340,
        100,
        ["Review Failed Trajectories", "Fix tools / retrieval / policy"],
        size=18,
    )
    d.arrow([(1110, 590), (920, 590)])
    d.text(1010, 570, ["No"], 18)
    d.arrow([(750, 545), (750, 310)])
    d.box(1110, 800, 340, 90, ["Qualified Local Release"], "#d5e8d4", 19)
    d.arrow([(1280, 670), (1280, 800)])
    d.text(1320, 745, ["Yes"], 18)
    d.text(450, 840, ["Recorded business assertions: 23 / 23"], 21, True)
    d.footer(
        "Agent Eval",
        "Tool Selection · Parameter Validity · Evidence Use · Constraints · Abstention",
    )
    d.save("automated_agent_eval_architecture")


def deployment():
    d = Diagram("Agent Deployment · AWS Bedrock AgentCore")
    d.box(70, 180, 270, 100, ["Client Request", "Task payload"], "#d5e8d4", 18)
    d.box(450, 180, 300, 100, ["Identity & Payload Check", "Schema · Customer scope"], size=18)
    d.ellipse(880, 165, 330, 130, ["AgentCore Runtime", "@app.entrypoint"], 19)
    d.arrow([(340, 230), (450, 230)])
    d.arrow([(750, 230), (880, 230)])
    d.box(880, 450, 330, 100, ["POST /invocations", "LangGraph workflow"], size=19)
    d.arrow([(1045, 295), (1045, 450)])
    d.box(
        450,
        450,
        300,
        100,
        ["A2A Task Response", "task_id · status · messages", "artifacts"],
        size=18,
    )
    d.arrow([(880, 500), (750, 500)])
    d.box(70, 450, 270, 100, ["Manager Review"], "#d5e8d4")
    d.arrow([(450, 500), (340, 500)])
    d.box(70, 765, 270, 105, ["GET /ping", "Health check"], size=19)
    d.box(450, 765, 300, 105, ["Docker ARM64", "Non-root · Port 8080"], size=19)
    d.box(
        880, 765, 330, 105, ["AWS Runtime Deployment", "Identity · Network · Monitoring"], size=18
    )
    d.arrow([(750, 817), (880, 817)])
    d.text(800, 930, ["Local HTTP validated · Docker execution and AWS rollout pending"], 18)
    d.footer("Deployment Eval", "HTTP Contracts · A2A Schema · Authorization · Health · Recovery")
    d.save("agent_deployment_architecture")


if __name__ == "__main__":
    for render in [overview, ml, security, tracing, automated_eval, deployment]:
        render()
