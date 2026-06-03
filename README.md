# Cognitor Folder Sync Daemon

This worker keeps a local folder of `.doc` / `.docx` files synchronized with a
Cognitor collection.

## Behavior

- On startup, it reconciles the configured folder and collection.
- While running, it periodically syncs:
	- files added locally are ingested
	- files removed locally are deleted from Cognitor
	- files changed locally are reingested

This guarantees restart safety: after shutdown/startup, the first sync pass
aligns Cognitor with current folder contents.

## Configuration

Set these environment variables (for example in `.env`):

- `DOCS_FOLDER` (required): target folder path to watch/sync
- `COGNITOR_COLLECTION_NAME` (required): target collection name
- `COGNITOR_URL` (required): Cognitor base URL (example: `http://localhost:7530`)
- `COGNITOR_API_KEY` (optional): API key if authentication is enabled

Optional:

- `SYNC_INTERVAL_SECONDS` (default: `5`): sync polling interval

## Run

```bash
source .venv/bin/activate
python src/worker-daemon/main.py
```

Stop with `Ctrl+C` (graceful shutdown).
