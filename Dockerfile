FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install the project and its dependencies.
COPY pyproject.toml ./
COPY cognitor-0.1.0-py3-none-any.whl ./
COPY src ./src
COPY README.md ./
# Install the local cognitor wheel first (uv.sources is not understood by pip),
# then install the project and its remaining dependencies.
RUN pip install --no-cache-dir cognitor-0.1.0-py3-none-any.whl && \
    pip install --no-cache-dir .

# Ensure runtime directories exist.
RUN mkdir -p /app/logs

CMD ["python", "src/start_worker.py"]
