"""Load shared root environment and optional ingestion-local overrides."""

from pathlib import Path

from dotenv import load_dotenv


def load_ingestion_environment(script_file: str) -> None:
    """Load local config, then root config, preserving shell variables."""
    ingestion_dir = Path(script_file).resolve().parent
    repository_root = ingestion_dir.parents[1]
    # Existing process environment wins. Local config wins over root config.
    load_dotenv(ingestion_dir / ".env", override=False)
    load_dotenv(repository_root / ".env", override=False)
