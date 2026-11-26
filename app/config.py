import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    database_url: str = "sqlite:///data/portal.db"
    data_dir: Path = Path("data")
    origin: str = "http://127.0.0.1:8000"
    secure_cookies: bool = True
    bucket: str = ""
    region: str = "ap-northeast-2"
    orca_folders_path: Path = Path("/run/kosmos-orca-link/orca-folders.json")
    orca_project_registry: Path | None = None

    @classmethod
    def from_env(cls):
        registry = os.getenv("ORCA_PROJECT_REGISTRY")
        return cls(database_url=os.getenv("DATABASE_URL", "sqlite:///data/portal.db"),
                   data_dir=Path(os.getenv("DATA_DIR", "data")),
                   origin=os.getenv("PORTAL_ORIGIN", "http://127.0.0.1:8000"),
                   secure_cookies=os.getenv("SECURE_COOKIES", "true") == "true",
                   bucket=os.getenv("S3_BUCKET", ""), region=os.getenv("AWS_REGION", "ap-northeast-2"),
                   orca_project_registry=Path(registry) if registry is not None else None)
