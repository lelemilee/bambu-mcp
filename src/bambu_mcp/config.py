"""Settings loaded from environment variables (or a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so we don't need an extra dependency.

    Existing environment variables always win over the file.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    serial: str
    access_code: str
    studio_path: str | None
    work_dir: Path
    read_only: bool

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(Path(os.environ.get("BAMBU_ENV_FILE", ".env")))
        missing = [
            k for k in ("BAMBU_HOST", "BAMBU_SERIAL", "BAMBU_ACCESS_CODE") if not os.environ.get(k)
        ]
        if missing:
            raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
        work_dir = Path(os.environ.get("BAMBU_WORK_DIR", Path.home() / "bambu-mcp-output"))
        return cls(
            host=os.environ["BAMBU_HOST"],
            serial=os.environ["BAMBU_SERIAL"],
            access_code=os.environ["BAMBU_ACCESS_CODE"],
            studio_path=os.environ.get("BAMBU_STUDIO_PATH") or None,
            work_dir=work_dir,
            read_only=_truthy(os.environ.get("BAMBU_READ_ONLY")),
        )
