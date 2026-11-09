from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from config.contracts import Artifact, Message, QuoteRequest, Scope, Task, fingerprint


class State(TypedDict, total=False):
    request: dict
    scope: dict
    route: str
    facts: dict
    option: dict
    capacity: dict
    attempt: int
    events: list[dict]
    messages: list[dict]
    tasks: list[dict]
    artifact: dict
    answer: str


def build_workflow(tools, checkpointer):
    def triage(state):
        prompt = state["request"]["prompt"].strip().lower()
        route = (
            "direct"
            if prompt in {"what is fob?", "what does fob mean?"}
            else "lookup"
            if prompt.startswith("lookup ecn")
            else "quote"
        )
        return {
            "route": route,
            "events": [{"step": "triage_router", "route": route}],
            "messages": [],
            "tasks": [],
            "attempt": 0,
        }

    def direct(state):
        return {
            "answer": "FOB is a shipping trade term. The named port and agreed contract determine the applicable obligations."
        }

    def quote(state):
        request = QuoteRequest.model_validate(state["request"])
        scope = Scope.model_validate(state["scope"])
        facts = state.get("facts") or tools.query_bom_and_ecn(scope, request.part_id)
        cost = facts["unit_cost_cents"]
        price = max(
            (request.unit_price_cents * (10000 - request.discount_bps) + 9999) // 10000,
            (cost * 10000 + 8999) // 9000,
        )
        option = {
            "unit_cost_cents": cost,
            "unit_price_cents": price,
            "quantity": request.quantity,
            "total_cost_cents": cost * request.quantity,
            "total_price_cents": price * request.quantity,
            "lead_days": facts["lead_days"],
            "volume_commitment": "unconfirmed",
            "required_conditions": [
                "Required inspection remains included",
                "Future volume is not a signed commitment",
            ],
        }
        if state.get("capacity"):
            option.update(
                {
                    "factory_id": state["capacity"]["factory_id"],
                    "lead_days": max(facts["lead_days"], state["capacity"]["process_days"]),
                }
            )
        parent = fingerprint([scope.key, request.model_dump()])
        task = Task(
            task_id=parent,
            agent="QuoteAgent",
            state="working",
            inputs={"quantity": request.quantity},
        )
        message = Message(
            sender="QuoteAgent",
            recipient="CapacityAgent",
            task_id=parent,
            content={"required_units": request.quantity, "minimum_days": facts["lead_days"]},
        )
        preferences = tools.recall_customer_memory(scope)
        return {
            "facts": facts,
            "option": option,
            "events": [
                *state["events"],
                {
                    "step": "quote_agent",
                    "tools": ["query_bom_and_ecn", "recall_customer_memory"]
                    if not state.get("facts")
                    else ["recall_customer_memory"],
                    "confirmed_preferences": preferences,
                },
            ],
            "messages": [*state["messages"], message.model_dump()],
            "tasks": [*state["tasks"], task.model_dump()],
        }

    def capacity(state):
        request = QuoteRequest.model_validate(state["request"])
        options = [
            tools.check_factory_capacity(
                {
                    "factory_id": factory,
                    "target_quarter": request.quarter,
                    "required_units": request.quantity,
                }
            )
            for factory in dict.fromkeys([request.preferred_factory, "PLANT-A", "PLANT-B"])
        ]
        feasible = [row for row in options if row["can_fit"]]
        chosen = feasible[0] if feasible else options[0]
        chosen = {**chosen, "feasible": bool(feasible), "examined": options}
        request_change = (
            chosen["factory_id"] != request.preferred_factory
            or request.requested_days < state["facts"]["lead_days"]
        )
        attempt = state["attempt"] + 1
        task = Task(
            task_id=fingerprint([state["tasks"][0]["task_id"], "capacity", attempt]),
            parent_task_id=state["tasks"][0]["task_id"],
            agent="CapacityAgent",
            state="completed" if feasible else "needs_review",
            inputs={"quarter": request.quarter, "quantity": request.quantity},
        )
        message = Message(
            sender="CapacityAgent",
            recipient="QuoteAgent",
            task_id=task.task_id,
            content={
                "factory_id": chosen["factory_id"],
                "minimum_days": max(state["facts"]["lead_days"], chosen["process_days"]),
                "revision_needed": request_change,
            },
        )
        return {
            "capacity": chosen,
            "attempt": attempt,
            "events": [
                *state["events"],
                {
                    "step": "capacity_agent",
                    "tool": "check_factory_capacity",
                    "candidate_count": len(options),
                },
            ],
            "messages": [*state["messages"], message.model_dump()],
            "tasks": [*state["tasks"], task.model_dump()],
        }

    def supervise(state):
        request = QuoteRequest.model_validate(state["request"])
        capacity = state["capacity"]
        option = {
            **state["option"],
            "factory_id": capacity["factory_id"],
            "lead_days": max(state["facts"]["lead_days"], capacity["process_days"]),
        }
        if option["total_cost_cents"] != option["unit_cost_cents"] * request.quantity:
            raise ValueError("Cost calculation failed")
        result = {
            **option,
            "available_units": capacity["available_units"],
            "customer_requested_days": request.requested_days,
            "capacity_feasible": capacity["feasible"],
            "capacity_snapshot": fingerprint(capacity),
            "no_production_capacity_reserved": True,
        }
        artifact = Artifact(
            name="quote_proposal",
            revision=fingerprint([request.model_dump(), state["facts"], capacity]),
            status="needs_review" if capacity["feasible"] else "blocked",
            result=result,
            evidence=state["facts"]["evidence"],
        )
        return {
            "artifact": artifact.model_dump(),
            "events": [*state["events"], {"step": "risk_supervisor", "status": artifact.status}],
        }

    def lookup(state):
        request = QuoteRequest.model_validate(state["request"])
        facts = tools.query_bom_and_ecn(Scope.model_validate(state["scope"]), request.part_id)
        return {
            "answer": f"The current ECN requires at least {facts['lead_days']} days.",
            "facts": facts,
            "events": [*state["events"], {"step": "factual_lookup", "tool": "query_bom_and_ecn"}],
        }

    graph = StateGraph(State)
    for name, node in [
        ("triage", triage),
        ("direct", direct),
        ("lookup", lookup),
        ("quote", quote),
        ("capacity", capacity),
        ("supervise", supervise),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "triage")
    graph.add_conditional_edges(
        "triage",
        lambda state: state["route"],
        {"direct": "direct", "lookup": "lookup", "quote": "quote"},
    )
    graph.add_edge("quote", "capacity")
    graph.add_conditional_edges(
        "capacity",
        lambda state: (
            "quote"
            if state["attempt"] == 1
            and state["capacity"]["feasible"]
            and (
                state["capacity"]["factory_id"] != state["request"]["preferred_factory"]
                or state["request"]["requested_days"] < state["facts"]["lead_days"]
            )
            else "supervise"
        ),
    )
    for node in ["direct", "lookup", "supervise"]:
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer)
