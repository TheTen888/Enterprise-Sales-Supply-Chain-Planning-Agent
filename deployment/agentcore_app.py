import hmac
import json
import os
import uuid
from contextvars import ContextVar

from a2a.types import Artifact, Message, Part, Task, TaskState, TaskStatus, TextPart
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from agent.service import Service
from config.contracts import QuoteRequest, Scope
from evaluation.gates import implementation_hash

principal = ContextVar("principal", default="demo-manager")


class AccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, credentials):
        super().__init__(app)
        self.credentials = credentials

    async def dispatch(self, request, call_next):
        if request.url.path == "/ping":
            return await call_next(request)
        actor = "demo-manager"
        if self.credentials:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            actor = next(
                (
                    value
                    for token, value in self.credentials.items()
                    if hmac.compare_digest(token, supplied)
                ),
                None,
            )
            if actor is None:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        token = principal.set(actor)
        try:
            return await call_next(request)
        finally:
            principal.reset(token)


def invoke_payload(payload, service, actor="demo-manager"):
    request = QuoteRequest.model_validate(payload)
    scope = Scope(customer_id="CUSTOMER-A", project_id="PROJECT-A")
    result = service.run(actor, scope, request.model_dump())
    task_id = str(uuid.uuid4())
    artifact = result.get("artifact")
    state = TaskState.input_required if artifact else TaskState.completed
    response = json.dumps(artifact) if artifact else result.get("answer", "")
    messages = [
        Message(
            message_id=str(uuid.uuid4()),
            role="agent",
            task_id=task_id,
            parts=[Part(root=TextPart(text=response))],
        )
    ]
    artifacts = (
        [
            Artifact(
                artifact_id=artifact["revision"],
                name=artifact["name"],
                parts=[Part(root=TextPart(text=json.dumps(artifact)))],
            )
        ]
        if artifact
        else []
    )
    task = Task(
        id=task_id,
        context_id=str(uuid.uuid4()),
        status=TaskStatus(state=state),
        history=messages,
        artifacts=artifacts,
    )
    return {
        "task_id": task.id,
        "status": task.status.model_dump(mode="json", by_alias=True),
        "messages": [message.model_dump(mode="json", by_alias=True) for message in messages],
        "artifacts": [item.model_dump(mode="json", by_alias=True) for item in artifacts],
        "a2a_task": task.model_dump(mode="json", by_alias=True),
        "runtime": result["runtime"],
        "events": result.get("events", []),
        "llm_trajectory": result.get("llm_trajectory", []),
        "handoffs": result.get("messages", []),
        "implementation_hash": implementation_hash(),
    }


def create_app(service, credentials=None):
    credentials = (
        credentials
        if credentials is not None
        else json.loads(os.getenv("AGENT_CALLER_TOKENS", "{}"))
    )
    if os.getenv("AGENT_ENV", "local") != "local" and not credentials:
        raise RuntimeError("Production identity configuration is required")
    if os.getenv("AGENT_ENV", "local") != "local" and not service.live_graph:
        raise RuntimeError("Real model readiness is required for production")
    app = BedrockAgentCoreApp(middleware=[Middleware(AccessMiddleware, credentials=credentials)])

    @app.entrypoint
    def invoke(payload):
        try:
            with service.lock:
                return invoke_payload(payload, service, principal.get())
        except ValidationError:
            raise HTTPException(status_code=422, detail="Invalid payload schema") from None
        except PermissionError:
            raise HTTPException(status_code=403, detail="Customer/project access denied") from None
        except ValueError:
            raise HTTPException(
                status_code=409, detail="Business evidence requires review"
            ) from None

    return app


def main():
    root = os.getenv("AGENT_RUNTIME_ROOT", "runtime/service")
    create_app(Service(root)).run(
        host=os.getenv("AGENT_HOST", "127.0.0.1"), port=int(os.getenv("AGENT_PORT", "8080"))
    )


if __name__ == "__main__":
    main()
