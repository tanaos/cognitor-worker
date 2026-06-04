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

## Usage

Use with `docker compose`. Pass a single env file that contains all required variables:

```bash
docker compose --env-file your.env up --build
```

The env file **must** define:

```env
# Folder on the host to sync
DOCS_FOLDER=/absolute/path/to/your/docs

# Cognitor connection
COGNITOR_URL=http://host.docker.internal:7530
COGNITOR_COLLECTION_NAME=my-collection

# Optional
COGNITOR_API_KEY=              # Cognitor API key, if your instance requires authentication
SYNC_INTERVAL_SECONDS=600      # Polling interval for synchronization (default: 300 seconds)
```

> [!WARNING]
> - If your Cognitor instance runs on your host machine, use `http://host.docker.internal:<port>` (typically `http://host.docker.internal:7530`) as the `COGNITOR_URL`. The Compose file maps `host.docker.internal` to the host gateway automatically.
> - If your Cognitor instance requires authentication, provide a valid API key in `COGNITOR_API_KEY`. Otherwise, leave it empty or omit it.

