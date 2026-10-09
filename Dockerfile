FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/agentforge
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 agentforge \
    && mkdir -p /srv/agentforge/data \
    && chown -R agentforge:agentforge /srv/agentforge
USER agentforge
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]