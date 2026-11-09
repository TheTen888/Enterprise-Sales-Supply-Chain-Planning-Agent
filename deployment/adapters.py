import json


def require_network(allowed):
    if not allowed:
        raise RuntimeError("External services are disabled; use local execution")


class OpenAIPlanner:
    def __init__(self, model, allowed=False):
        self.model = model
        self.allowed = allowed

    def invoke(self, messages, schema):
        require_network(self.allowed)
        from langchain_openai import ChatOpenAI

        return (
            ChatOpenAI(model=self.model, temperature=0)
            .with_structured_output(schema)
            .invoke(messages)
        )


def redis_checkpointer(url, allowed=False):
    require_network(allowed)
    from langgraph.checkpoint.redis import RedisSaver

    return RedisSaver.from_conn_string(url)


class RedisPreferenceStore:
    def __init__(self, client, index, vector_query_factory):
        self.client = client
        self.index = index
        self.vector_query_factory = vector_query_factory

    def nearest(self, scope, embedding, k=3):
        from redisvl.query.filter import Tag

        query = self.vector_query_factory(
            vector=embedding,
            vector_field_name="embedding",
            num_results=k,
            filter_expression=Tag("scope") == scope.key,
        )
        return self.index.query(query)

    def put(self, scope, preference_id, text, embedding):
        identifier = f"{scope.key}:{preference_id}"
        keys = self.index.load(
            [{"id": identifier, "scope": scope.key, "text": text, "embedding": embedding}],
            id_field="id",
        )
        self.client.set(f"preference-key:{identifier}", keys[0])

    def delete(self, scope, preference_id):
        pointer = f"preference-key:{scope.key}:{preference_id}"
        key = self.client.get(pointer)
        if key:
            self.client.delete(key)
        self.client.delete(pointer)


async def inngest_document_handler(ctx, pipeline, source, metadata):
    return await ctx.step.run("ingest-document", lambda: pipeline.ingest(source, metadata))


def export_trace(result, allowed=False):
    require_network(allowed)
    from langsmith import traceable, tracing_context

    @traceable(name="quote-workflow-replay", run_type="chain")
    def record(payload):
        return payload

    with tracing_context(enabled=True):
        return record(json.loads(json.dumps(result)))
