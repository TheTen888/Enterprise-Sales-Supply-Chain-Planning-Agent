FROM --platform=linux/arm64 python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY config ./config
COPY mock_data ./mock_data
COPY data_pipeline ./data_pipeline
COPY memory ./memory
COPY rag ./rag
COPY agent ./agent
COPY evaluation ./evaluation
COPY deployment ./deployment
COPY scripts ./scripts
COPY .streamlit ./.streamlit
RUN pip install --no-cache-dir .[runtime] && useradd --create-home agent && mkdir runtime && chown agent:agent runtime
USER agent
RUN python -m mock_data.generator && python -m scripts.prepare
EXPOSE 8080
ENV AGENT_ENV=production
ENV AGENT_HOST=0.0.0.0
ENV AGENT_RUNTIME_ROOT=/app/runtime
HEALTHCHECK --interval=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=3)"
CMD ["python", "-m", "deployment.agentcore_app"]
