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

    @classmethod
    def from_env(cls):
        return cls(database_url=os.getenv("DATABASE_URL", "sqlite:///data/portal.db"),
                   data_dir=Path(os.getenv("DATA_DIR", "data")),
                   origin=os.getenv("PORTAL_ORIGIN", "http://127.0.0.1:8000"),
                   secure_cookies=os.getenv("SECURE_COOKIES", "true") == "true",
                   bucket=os.getenv("S3_BUCKET", ""), region=os.getenv("AWS_REGION", "ap-northeast-2"))
