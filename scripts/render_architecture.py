from html import escape
from pathlib import Path

import resvg_py

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/diagrams'
GREEN = '#d5e8d4'
PINK = '#f8cecc'


class Diagram:
    def __init__(self, title, height=1080):
        self.height = height
        self.items = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{height}" viewBox="0 0 1600 {height}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#222"/></marker></defs><rect width="1600" height="{height}" fill="white"/><g font-family="Arial, Helvetica, sans-serif" fill="#222" stroke-linejoin="round" stroke-linecap="round">']
        self.text(800, 48, [title], 28, True)

    def text(self, x, y, lines, size=20, bold=False):
        for i, line in enumerate(lines):
            self.items.append(f'<text x="{x}" y="{y+i*(size+9)}" text-anchor="middle" font-size="{size}" font-weight="{600 if bold and i == 0 else 400}">{escape(line)}</text>')

    def box(self, x, y, w, h, lines, fill='white', size=20):
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="{fill}" stroke="#222" stroke-width="1.8"/>')
        self.text(x+w/2, y+h/2-(len(lines)-1)*(size+9)/2+7, lines, size, True)

    def ellipse(self, x, y, w, h, lines, size=20):
        self.items.append(f'<ellipse cx="{x+w/2}" cy="{y+h/2}" rx="{w/2}" ry="{h/2}" fill="{PINK}" stroke="#222" stroke-width="1.8"/>')
        self.text(x+w/2, y+h/2-(len(lines)-1)*(size+9)/2+7, lines, size, True)

    def diamond(self, x, y, w, h, lines, size=19):
        self.items.append(f'<path d="M{x+w/2},{y} L{x+w},{y+h/2} L{x+w/2},{y+h} L{x},{y+h/2} Z" fill="white" stroke="#222" stroke-width="1.8"/>')
        self.text(x+w/2, y+h/2-(len(lines)-1)*(size+9)/2+7, lines, size, True)

    def db(self, x, y, w, h, lines):
        self.items.append(f'<path d="M{x},{y+20} A{w/2},20 0 0 1 {x+w},{y+20} V{y+h-20} A{w/2},20 0 0 1 {x},{y+h-20} Z" fill="#f5f5f5" stroke="#222" stroke-width="1.8"/><ellipse cx="{x+w/2}" cy="{y+20}" rx="{w/2}" ry="20" fill="white" stroke="#222" stroke-width="1.8"/>')
        self.text(x+w/2, y+h/2+5, lines, 19, True)

    def frame(self, x, y, w, h, title):
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="30" fill="none" stroke="#222" stroke-width="1.6"/>')
        self.text(x+w/2, y+32, [title], 21, True)

    def arrow(self, points, dashed=False, both=False):
        pts = ' '.join(f'{x},{y}' for x, y in points)
        self.items.append(f'<polyline points="{pts}" fill="none" stroke="#222" stroke-width="1.7" marker-end="url(#arrow)"'+(' marker-start="url(#arrow)"' if both else '')+(' stroke-dasharray="6 6"' if dashed else '')+'/>')

    def footer(self, title, metrics):
        self.box(40, self.height-105, 1520, 78, [title, metrics], '#f5f5f5', 19)

    def save(self, name):
        svg = '\n'.join(self.items + ['</g></svg>'])
        (OUT/f'{name}.svg').write_text(svg)
        (OUT/f'{name}.png').write_bytes(resvg_py.svg_to_bytes(svg_string=svg, width=3200))


def memory():
    d = Diagram('Agent Memory Architecture')
    d.frame(40, 80, 1520, 270, 'Active Session')
    d.box(75, 135, 220, 52, ['User Prompt'], GREEN)
    d.box(75, 205, 220, 52, ['Current Chat History'], size=18)
    d.box(75, 275, 220, 52, ['System Prompt'])
    d.box(415, 192, 265, 94, ['Working Memory', 'Context RAM'])
    d.text(550, 139, ['Context Editing'], 19, True)
    d.text(550, 166, ['Tool pruning · Context trimming'], 16)
    for y in [161, 231, 301]:
        d.arrow([(295,y),(350,y),(350,239),(415,239)])
    d.ellipse(810, 185, 290, 110, ['Multi-Agent'])
    d.arrow([(680,239),(810,239)])
    d.box(1250, 212, 220, 62, ['Reply'], GREEN)
    d.arrow([(1100,239),(1250,239)])
    d.box(80, 475, 310, 145, ['Procedural Memory','Files / Text','Skills · Rules'])
    d.box(475,475,310,145,['Semantic Memory','Vector Store','Durable facts · User profiles'],size=18)
    d.box(870,475,310,145,['Episodic Memory','Vector Store','Dated events · Session logs'],size=18)
    d.arrow([(235,475),(235,393),(460,393),(460,286)])
    d.text(310,382,['Load skills'],18)
    d.arrow([(630,475),(630,286)])
    d.text(780,400,['Hybrid Retrieval'],18,True)
    d.text(780,426,['Vector + BM25'],17)
    d.arrow([(1025,475),(1025,365),(665,365),(665,286)])
    d.text(1160,389,['Recall events'],18)
    d.db(530,665,200,120,['Fact Store'])
    d.arrow([(630,665),(630,620)])
    d.db(1255,480,220,140,['Event Store'])
    d.arrow([(1360,274),(1360,480)])
    d.text(1435,422,['Save events'],18)
    d.arrow([(1255,550),(1180,550)])
    d.diamond(1200,680,310,120,['New events?'])
    d.arrow([(1365,620),(1365,680)])
    d.ellipse(895,825,310,100,['Memory Consolidator'])
    d.arrow([(1355,800),(1355,875),(1205,875)])
    d.text(1300,852,['Yes'],17)
    d.arrow([(895,875),(630,875),(630,785)])
    d.text(765,852,['Distill into facts'],18)
    d.arrow([(1050,925),(1050,975)],True,True)
    d.footer('Memory Eval','Temporal Recall · Contradiction Resolution · Abstention Rate')
    d.save('memory_architecture')


def rag():
    d = Diagram('Two-Lane Ingestion & Hybrid RAG')
    d.frame(40,80,1520,420,'Ingestion Pipeline')
    d.box(70,245,235,90,['Raw Files','XLSX · PDF · ECN · Email'],GREEN,18)
    d.diamond(355,220,270,140,['Can device','convert locally?'])
    d.arrow([(305,290),(355,290)])
    d.box(720,150,330,110,['Local Lane (WASM / Edge)','Text / JSON · No provider cost','Raw bytes stay local'],size=18)
    d.box(720,330,330,110,['Server Lane','Formula & Layout Engine','openpyxl + restricted evaluator'],size=18)
    d.arrow([(490,220),(490,205),(720,205)])
    d.text(595,190,['Yes'],18)
    d.arrow([(490,360),(490,385),(720,385)])
    d.text(595,373,['No'],18)
    d.ellipse(1180,225,340,140,['Inngest Durable Pipeline','5-Step Stateful Checkpoints','Idempotent SHA-256 Upsert'],17)
    d.arrow([(1050,205),(1120,205),(1120,270),(1188,270)])
    d.arrow([(1050,385),(1120,385),(1120,320),(1188,320)])
    d.text(870,285,['Edge lane: target integration'],16)
    d.text(1345,412,['Inngest adapter · Local SQLite runner'],16)
    d.text(800,550,['Hybrid Retrieval & Reranking'],22,True)
    d.box(450,605,390,110,['Metadata & Version Filter','Tenant / Customer / Project Isolation','Active ECN Override (v2 > v1)'],size=18)
    d.ellipse(940,605,290,110,['Cross-Encoder','Reranker'])
    d.box(1300,610,235,100,['Grounded Context','Top-K Clean Chunks'],GREEN,18)
    d.arrow([(840,660),(940,660)])
    d.arrow([(1230,660),(1300,660)])
    d.db(160,805,300,125,['BM25 Lexical Index','Part IDs · ECN IDs'])
    d.db(650,805,300,125,['Vector Store','Semantic embeddings'])
    d.arrow([(1520,295),(1545,295),(1545,950),(70,950),(70,865),(160,865)])
    d.arrow([(600,950),(600,865),(650,865)])
    d.text(1250,935,['Publish scoped chunks'],18)
    d.arrow([(460,865),(510,865),(510,715)])
    d.arrow([(730,805),(730,715)])
    d.text(1190,805,['Scope + version constraints','apply before ranking'],16)
    d.footer('RAG & Ingestion Eval','Idempotent Resume Rate · Active ECN Precision · Context Grounding Faithfulness')
    d.save('rag_ingestion_architecture')


def agents():
    d = Diagram('LangGraph & A2A Protocol Orchestration',1180)
    d.frame(40,80,1520,960,'Active A2A Task Session')
    d.box(75,150,270,80,['Client Request','Working Memory Context'],GREEN,18)
    d.ellipse(440,145,245,90,['Triage Router'])
    d.arrow([(345,190),(440,190)])
    d.box(1180,155,300,70,['Direct Answer'],GREEN)
    d.arrow([(685,190),(1180,190)])
    d.text(915,172,['Direct Answer'],17)
    d.arrow([(560,235),(560,330)])
    d.text(780,280,['Current Info · Factual Lookup'],18)
    d.ellipse(420,330,280,110,['QuoteAgent'])
    d.ellipse(1090,330,280,110,['CapacityAgent'])
    d.arrow([(700,385),(1090,385)],both=True)
    d.text(895,323,['A2A Task Envelope'],18,True)
    d.text(895,349,['task_id · parent_task_id · Message'],16)
    d.box(410,510,300,105,['BOM & Discount Calculator','Hybrid RAG Lookup'],size=18)
    d.box(1070,510,330,105,['Factory Line Utilization','PLANT-A / PLANT-B','ECN Lead-Time Validator'],size=18)
    d.arrow([(560,440),(560,510)],both=True)
    d.arrow([(1230,440),(1230,510)],both=True)
    d.arrow([(1370,385),(1500,385),(1500,715),(1380,715)])
    d.diamond(1080,650,300,130,['Capacity & ECN','Constraints Met?'])
    d.arrow([(1080,715),(180,715),(180,385),(420,385)])
    d.text(610,680,['No · Conflict / Over-capacity'],18,True)
    d.text(610,706,['Re-negotiate plant / Extend lead time to 28d'],18)
    d.text(610,752,['Bounded retries · Unresolved conflicts block approval'],16)
    d.arrow([(1230,780),(1230,815),(825,815),(825,865)])
    d.text(1040,804,['Yes'],18)
    d.ellipse(680,865,290,100,['Risk Supervisor'])
    d.box(1160,870,340,90,['A2A Artifact','Verified Quote JSON'],GREEN)
    d.arrow([(970,915),(1160,915)])
    d.text(800,1005,['Typed task handoffs within one LangGraph · Manager review before external action'],17)
    d.footer('Multi-Agent Trajectory Eval','Tool Selection Accuracy · Parameter Schema Conformance · A2A State Consistency')
    d.save('multi_agent_a2a_architecture')


def evaluation():
    d = Diagram('3-Stage Eval, Gate & Observability Loop')
    d.frame(40,80,1520,330,'Pre-Deploy 3-Stage Evaluation Pipeline')
    d.box(80,175,350,130,['1. Benchmark Generation','5 Authored Fixtures','18 Parameterized Edge Cases'])
    d.ellipse(585,165,370,150,['2. Multi-Turn Simulation','Real LLM · gpt-4o-mini','Adversarial Inputs'],19)
    d.ellipse(1100,165,420,150,['3. Independent Judge & Audit','Cross-Model · gpt-4.1-mini','Deterministic Business Rules'],18)
    d.arrow([(430,240),(585,240)])
    d.arrow([(955,240),(1100,240)])
    d.text(800,455,['Observability & Qualification Gate'],22,True)
    d.db(65,580,440,220,['LangSmith Telemetry Blackbox','23 Run IDs & Waterfall Traces','Token & Latency Profiling','4-Level Root Cause Diagnosis'])
    d.arrow([(770,315),(770,340),(550,340),(550,495),(280,495),(280,580)])
    d.diamond(670,560,350,170,['Production Gate','Passed?'])
    d.arrow([(1310,315),(1310,505),(845,505),(845,560)])
    d.arrow([(505,645),(670,645)],True)
    d.text(585,628,['Evidence'],16)
    d.box(1110,580,420,130,['AWS Bedrock AgentCore Runtime','@app.entrypoint + Docker','Target deployment'],GREEN,19)
    d.arrow([(1020,645),(1110,645)])
    d.text(1060,626,['Yes'],16)
    d.text(848,773,['Local Contracts · Independent Judge'],17)
    d.text(848,801,['Real LLM · AgentCore HTTP'],17)
    d.text(848,829,['/ping & /invocations'],17)
    d.arrow([(845,730),(1040,730),(1040,895),(30,895),(30,240),(80,240)],True)
    d.text(490,882,['No → Diagnose · Fix · Replay'],18)
    d.text(800,944,['Local release validated · Docker execution and AWS rollout pending'],18,True)
    d.footer('Production Gate Metrics · Recorded synthetic acceptance run','Capacity Over-commitment (0%) · Delivery Constraints Met (100%) · Pass Rate (23/23)')
    d.save('eval_observability_architecture')


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    for render in [memory, rag, agents, evaluation]:
        render()
