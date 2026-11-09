import os
import time

from agent.service import Service
from config.contracts import QuoteRequest, Scope


def invoke_local(payload, service):
    request = QuoteRequest.model_validate(payload)
    started = time.perf_counter()
    result = service.run(
        "demo-manager",
        Scope(customer_id="CUSTOMER-A", project_id="PROJECT-A"),
        request.model_dump(),
    )
    return {
        "result": result.get("answer") or result.get("artifact"),
        "artifacts": [result["artifact"]] if result.get("artifact") else [],
        "events": result["events"],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "mode": "local-deterministic",
        "external_api_calls": 0,
    }


def create_app(service):
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload):
        return invoke_local(payload, service)

    return app


if __name__ == "__main__":
    if os.getenv("AGENT_ENV", "local") != "local":
        raise RuntimeError(
            "Configure verified identity and tenant authorization before production deployment"
        )
    create_app(Service("runtime")).run()
