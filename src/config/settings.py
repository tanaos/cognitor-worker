from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Config(BaseSettings):
    
    # Cognitor configuration
    COGNITOR_URL: str
    COGNITOR_API_KEY: Optional[str] = None
    DOCS_FOLDER: str
    COGNITOR_COLLECTION_NAME: str = "cognitor-worker"
    
    # Chunking configuration
    DEFAULT_CHUNK_SIZE: int = 500
    DEFAULT_OVERLAP_RATIO: float = 0.15
    DEFAULT_ENCODING_NAME: str = "cl100k_base"
    
    # Other settings
    SYNC_INTERVAL_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="allow",
    )