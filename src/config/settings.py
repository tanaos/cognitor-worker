from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional


class Config(BaseSettings):
    
    # Cognitor configuration
    COGNITOR_URL: str
    COGNITOR_API_KEY: Optional[str] = None
    COGNITOR_TIMEOUT_SECONDS: float = 300.0
    DOCS_FOLDER: str
    COGNITOR_COLLECTION_NAME: str = "cognitor-worker-collection"
    
    # Chunking configuration
    DEFAULT_CHUNK_SIZE: int = 500
    DEFAULT_OVERLAP_RATIO: float = 0.15
    DEFAULT_ENCODING_NAME: str = "cl100k_base"
    CHUNKER_TYPE: Literal["semantic", "simple"] = "semantic"
    SEMANTIC_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    SEMANTIC_BREAKPOINT_PERCENTILE: int = 70
    SEMANTIC_REPAIR_SENTENCE_BOUNDARIES: bool = True
    
    # Other settings
    SYNC_INTERVAL_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="allow",
    )