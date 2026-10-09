FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115,<1.0" \
    "uvicorn[standard]>=0.30,<1.0" \
    "redis[hiredis]>=5.0,<6.0" \
    "pydantic>=2.8,<3.0" \
    "prometheus-client>=0.20,<1.0"
COPY app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir --no-deps .
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log", "--backlog", "4096"]
