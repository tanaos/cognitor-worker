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
