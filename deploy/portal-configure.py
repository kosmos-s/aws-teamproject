"""Server-side bootstrap: fetch a new DB password from encrypted SSM, never log it."""
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import boto3
import pymysql
from sqlalchemy import create_engine
from app.models import Base
from app.security import create_user


def main():
    config = json.loads(Path("/root/kosmos-portal-cloud.json").read_text())
    region = "ap-northeast-2"
    rds = boto3.client("rds", region_name=region)
    endpoint = None
    for _ in range(60):
        db = rds.describe_db_instances(DBInstanceIdentifier=config["db"])["DBInstances"][0]
        if db["DBInstanceStatus"] == "available":
            endpoint = db["Endpoint"]["Address"]
            break
        time.sleep(10)
    if not endpoint:
        raise RuntimeError("RDS not ready; inspect state before retrying bootstrap")
    ssm = boto3.client("ssm", region_name=region)
    credentials = json.loads(ssm.get_parameter(Name=config["parameter"], WithDecryption=True)["Parameter"]["Value"])
    ca = "/opt/kosmos-portal/rds-ca.pem"
    password = secrets.token_urlsafe(30)
    conn = pymysql.connect(host=endpoint, user=credentials["username"], password=credentials["password"],
                           database="kosmos", ssl_ca=ca, ssl_verify_cert=True, ssl_verify_identity=True)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("CREATE USER 'kosmosapp'@'%%' IDENTIFIED BY %s", (password,))
            cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, REFERENCES, INDEX ON kosmos.* TO 'kosmosapp'@'%'")
        conn.commit()
    url = f"mysql+pymysql://kosmosapp:{quote(password, safe='')}@{endpoint}/kosmos?charset=utf8mb4&ssl_ca={ca}&ssl_check_hostname=true"
    domain = config["domain"]
    env = f"DATABASE_URL={url}\nDATA_DIR=/var/lib/kosmos-portal\nPORTAL_ORIGIN=https://{domain}\nSECURE_COOKIES=true\nS3_BUCKET={config['bucket']}\nAWS_REGION={region}\n"
    path = Path("/etc/kosmos-portal.env")
    path.write_text(env)
    path.chmod(0o600)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    admin_password = secrets.token_urlsafe(20)
    create_user(engine, "owner", admin_password, "admin")
    engine.dispose()
    private = Path("/var/lib/kosmos/portal-login.json")
    private.write_text(json.dumps({"username": "owner", "password": admin_password, "url": f"https://{domain}"}))
    private.chmod(0o600)
    stop_script = f'''import boto3
from botocore.config import Config
client = boto3.client("rds", region_name="{region}", config=Config(connect_timeout=3, read_timeout=10, retries={{"max_attempts": 2}}))
client.stop_db_instance(DBInstanceIdentifier="{config['db']}")
print("RDS stop requested")
'''
    Path("/opt/kosmos-portal/deploy/stop-rds.py").write_text(stop_script)
    Path("/etc/systemd/system/kosmos-rds-stop.service").write_text('''[Unit]
Description=Stop approved lab RDS before EC2 shutdown
[Service]
Type=oneshot
ExecStart=/opt/kosmos-portal/.venv/bin/python /opt/kosmos-portal/deploy/stop-rds.py
TimeoutStartSec=60
Restart=on-failure
RestartSec=10
''')
    # RDS stop is requested 47 seconds before the existing EC2 stop deadline.
    stop_at = config["StopAt"][:16].replace("T", " ") + ":00 UTC"
    Path("/etc/systemd/system/kosmos-rds-stop.timer").write_text(f'''[Unit]
Description=Approved absolute RDS stop deadline
[Timer]
OnCalendar={stop_at}
Persistent=true
AccuracySec=1s
[Install]
WantedBy=timers.target
''')
    nginx = Path("deploy/portal-nginx.conf").read_text().replace("portal.example.com", domain)
    Path("/etc/nginx/sites-available/kosmos-portal").write_text(nginx)
    target = Path("/etc/nginx/sites-enabled/kosmos-portal")
    if not target.exists():
        target.symlink_to("/etc/nginx/sites-available/kosmos-portal")
    default = Path("/etc/nginx/sites-enabled/default")
    if default.is_symlink():
        default.unlink()
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "kosmos-portal", "kosmos-monitor.timer", "kosmos-backup.timer", "kosmos-rds-stop.timer"], check=True)
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    print("RDS TLS application account, private S3, portal service and unchanged-deadline RDS stop timer configured")


if __name__ == "__main__":
    main()
