<p align="center">
    <a href="https://github.com/tanaos/cognitor">
        <img src="https://raw.githubusercontent.com/tanaos/cognitor/master/assets/banner.png" width="90%" alt="Cognitor | All-in-one semantic search engine for AI and humans.">
    </a>
</p>

# Cognitor Worker

This worker automatically chunks, embeds and indexes the entire content of a target folder (and its subfolders) into a [Cognitor](https://github.com/tanaos/cognitor) collection, making it easily searchable by both AI agents and humans. The folder's content is continuously monitored for changes, ensuring that the Cognitor collection remains up-to-date with the local files.

The following types of files are currently supported (we will be adding more soon):

- .doc and .docx
- .pdf
- .md
- .html and .htm
- .msg

Files that are not supported are ignored.

## Behavior

- On startup, it reconciles the configured folder and collection.
- While running, it periodically syncs:
	- files added locally are ingested
	- files removed locally are deleted from Cognitor
	- files changed locally are reingested

This guarantees restart safety: after shutdown/startup, the first sync pass
aligns Cognitor with current folder contents.

## Usage

This worker is intended to be used together with a [Cognitor](https://github.com/tanaos/cognitor) instance, which is assumed to be running on the same system. It is **not** intended to be used as a standalone application, and will do nothing if it cannot connect to a Cognitor instance.

For simplicity and ease of use, we recommend following the instructions contained in the [Cognitor README's how to use section](https://github.com/tanaos/cognitor#how-to-use) to set up a Cognitor instance, and then running this worker.

### Development usage

If, for development purposes, you wish to run this worker separately from Cognitor (still, it requires a running Cognitor instance), you can use `docker compose`. Pass a single env file that contains all required variables:

```bash
docker compose --env-file your.env up --build
```

The env file **must** define:

```bash
# Folder on the host to sync
DOCS_FOLDER=/absolute/path/to/your/docs

# Cognitor connection
COGNITOR_URL=http://localhost:7530
COGNITOR_COLLECTION_NAME=my-collection
```

Optionally, you can also set:

```bash
COGNITOR_API_KEY=              # Cognitor API key, if your instance requires authentication
COGNITOR_TIMEOUT_SECONDS=300   # HTTP timeout for Cognitor API calls
SYNC_INTERVAL_SECONDS=600      # Polling interval for synchronization (default: 300 seconds)

# Chunking
CHUNKER_TYPE=semantic           # semantic (default) or simple
DEFAULT_CHUNK_SIZE=500          # used by simple chunker
DEFAULT_OVERLAP_RATIO=0.15      # used by simple chunker
DEFAULT_ENCODING_NAME=cl100k_base  # used by simple chunker
SEMANTIC_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
SEMANTIC_BREAKPOINT_PERCENTILE=70
SEMANTIC_REPAIR_SENTENCE_BOUNDARIES=true
```
