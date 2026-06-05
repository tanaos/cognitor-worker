FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install the project and its dependencies.
COPY pyproject.toml ./
COPY src ./src
COPY README.md ./
RUN pip install --no-cache-dir .

# Ensure runtime directories exist.
RUN mkdir -p /app/logs

CMD ["python", "src/start_worker.py"]
