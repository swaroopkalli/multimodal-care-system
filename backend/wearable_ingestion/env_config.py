"""Load shared root environment and optional ingestion-local overrides."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def load_ingestion_environment(script_file: str) -> None:
    """Load local config, then root config, preserving shell variables.

    Also puts ``backend/`` on sys.path (shared services) and defaults the
    INGESTION_DB_* settings to the application's DB_* settings when unset, so a
    single database configuration is enough.
    """
    ingestion_dir = Path(script_file).resolve().parent
    repository_root = ingestion_dir.parents[1]
    backend_dir = ingestion_dir.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    # Existing process environment wins. Local config wins over root config.
    load_dotenv(ingestion_dir / ".env", override=False)
    load_dotenv(repository_root / ".env", override=False)
    for suffix in ("HOST", "PORT", "NAME", "USER", "PASSWORD", "SSLMODE"):
        if not os.getenv(f"INGESTION_DB_{suffix}") and os.getenv(f"DB_{suffix}"):
            os.environ[f"INGESTION_DB_{suffix}"] = os.environ[f"DB_{suffix}"]
