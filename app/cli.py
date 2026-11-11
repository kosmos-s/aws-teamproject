import argparse
import getpass
import json
from pathlib import Path

from .config import Settings
from .main import create_app
from .security import create_user
from .ops import monitor, backup, restore


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    user = sub.add_parser("create-user")
    user.add_argument("username")
    user.add_argument("--role", choices=["member", "admin", "viewer"], default="member")
    sub.add_parser("monitor")
    sub.add_parser("backup")
    recovery = sub.add_parser("restore")
    recovery.add_argument("archive", type=Path)
    args = parser.parse_args()
    app = create_app(Settings.from_env())
    engine, storage = app.state.engine, app.state.storage
    try:
        if args.command == "create-user":
            password = getpass.getpass("New portal password (14+ characters): ")
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("Passwords do not match")
            create_user(engine, args.username, password, args.role)
            print("User created")
        elif args.command == "monitor":
            print(json.dumps(monitor(engine, app.state.settings.data_dir)))
        elif args.command == "backup":
            data = backup(engine, storage)
            print(f"Backup stored: {len(data)} bytes")
        else:
            print(json.dumps(restore(engine, storage, args.archive.read_bytes())))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
