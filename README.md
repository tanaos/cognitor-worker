# Cognitor Worker

This worker keeps a local folder synchronized with a Cognitor collection, by performing automatic parsing, chunking, indexing and ingestion. The following types of files are currently supported:

- DOC/DOCX

## Behavior

- On startup, it reconciles the configured folder and collection.
- While running, it periodically syncs:
	- files added locally are ingested
	- files removed locally are deleted from Cognitor
	- files changed locally are reingested

This guarantees restart safety: after shutdown/startup, the first sync pass
aligns Cognitor with current folder contents.

## Configuration

Set these environment variables in a `.env` file at the project root:

- `DOCS_FOLDER` (required): target folder path to watch/sync
- `COGNITOR_COLLECTION_NAME` (required): target collection name
- `COGNITOR_URL` (required): Cognitor base URL (e.g. `http://localhost:7530` for self-hosted instances, or `https://cognitor.tanaos.com` for the managed service).
- `COGNITOR_API_KEY` (optional): API key if authentication is enabled in the Cognitor instance (disabled by default in self-hosted versions, but always required in the managed service)

Optional:

- `SYNC_INTERVAL_SECONDS` (default: `300`): sync polling interval

## Usage

The worker can be launched in the foreground or as a background daemon. Use the following commands:

```bash
python src/start_worker.py         # foreground, stop with Ctrl+C
python src/start_worker.py -d      # background daemon
python src/stop_worker.py          # stop the background daemon
```

## Docker

The repository includes a `Dockerfile` to run the worker in a container.

### Build image

```bash
docker build -t cognitor-worker:latest .
```

### Run container

The worker needs:

- environment variables (`COGNITOR_URL`, `COGNITOR_COLLECTION_NAME`, and usually `COGNITOR_API_KEY`)
- a mounted host folder containing documents
- `DOCS_FOLDER` set to the mount path inside the container

Example:

```bash
docker run --rm \
	--name cognitor-worker \
	--env-file .env \
	-e DOCS_FOLDER=/data/docs \
	-v /absolute/path/to/your/docs:/data/docs:ro \
	-v "$(pwd)/logs:/app/logs" \
	cognitor-worker:latest
```

Notes:

- In containers, run in foreground mode (default) so the process is PID 1 and receives stop signals correctly.
- `src/stop_worker.py` is meant for local daemon mode and is not needed for containerized runs.
- If your Cognitor endpoint runs on your host machine, use `http://host.docker.internal:7530` as the `COGNITOR_URL`. The Compose file maps `host.docker.internal` to the host gateway automatically, so this works on Linux as well as Mac and Windows.

### Run with Docker Compose

The repository includes `docker-compose.yml`. Pass a single env file that contains all required variables:

```bash
docker compose --env-file your.env up --build
```

The env file must define:

```env
# Folder on the host to sync
DOCS_FOLDER=/absolute/path/to/your/docs

# Cognitor connection
COGNITOR_URL=http://localhost:7530
COGNITOR_COLLECTION_NAME=my-collection

# Optional
COGNITOR_API_KEY=
SYNC_INTERVAL_SECONDS=300
```

`DOCS_FOLDER` is used as the host path for the volume mount. Inside the container it is automatically remapped to `/data/docs` by Compose.
