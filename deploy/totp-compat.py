"""Operator-only TOTP migration compatibility; never prints factor material.

Run with the service account and its EnvironmentFile before restoring old code:
  python deploy/totp-compat.py --restore-legacy
Use --check to verify every migrated seed can be decrypted without changing data.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select, inspect
from sqlalchemy.orm import Session
from app.config import Settings
from app.models import UserTotp, TotpVault


def compatibility(engine, vault, restore_legacy=False):
    if not inspect(engine).has_table("totp_vault"):
        return 0
    with Session(engine) as db:
        count = 0
        for row in db.scalars(select(UserTotp).where(UserTotp.secret == "vault")):
            encrypted = db.get(TotpVault, row.user_id)
            if not encrypted:
                raise ValueError("Missing encrypted factor; rollback refused")
            secret = vault.decrypt(encrypted.encrypted.encode()).decode()
            from app.security import totp_code

            totp_code(secret)  # validate the recovered base32 value before any write
            if restore_legacy:
                row.secret = secret
            count += 1
        if restore_legacy:
            db.commit()
        return count


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--restore-legacy", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        key = settings.data_dir / "totp.key"
        if not key.exists():
            with Session(engine) as db:
                if (
                    db.scalar(
                        select(UserTotp.user_id).where(UserTotp.secret == "vault")
                    )
                    is not None
                ):
                    raise ValueError("Key unavailable; rollback refused")
            print("No migrated factors")
            return
        count = compatibility(engine, Fernet(key.read_bytes()), args.restore_legacy)
        print(
            f"Factor compatibility verified: {count}; legacy restoration={args.restore_legacy}"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
