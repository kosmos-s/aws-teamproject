import re


class Storage:
    def __init__(self, settings):
        self.root = settings.data_dir / "objects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket = settings.bucket
        self.client = None
        if self.bucket:
            import boto3
            from botocore.config import Config
            self.client = boto3.client("s3", region_name=settings.region,
                                       config=Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2}))

    def path(self, key):
        if not re.fullmatch(r"(?:attachments|backups)/[a-f0-9]{32}(?:\.json)?", key):
            raise ValueError("Invalid object key")
        return self.root / key

    def put(self, key, content, media_type):
        path = self.path(key)
        if self.client:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=content,
                                   ContentType=media_type, ServerSideEncryption="AES256")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def discard(self, key):
        """Best-effort removal of an object (attachment deleted from the portal).
        Returns False when the backend refuses (e.g. the EC2 role lacks s3:DeleteObject)."""
        try:
            path = self.path(key)
            if self.client:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            else:
                path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def get(self, key, max_bytes=64 * 1024 * 1024):
        path = self.path(key)
        if self.client:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            stream = response["Body"]
            try:
                if response["ContentLength"] > max_bytes:
                    raise ValueError("Object exceeds size budget")
                value = stream.read(max_bytes + 1)
            finally:
                stream.close()
        else:
            if path.stat().st_size > max_bytes:
                raise ValueError("Object exceeds size budget")
            with path.open("rb") as stream:
                value = stream.read(max_bytes + 1)
        if len(value) > max_bytes:
            raise ValueError("Object exceeds size budget")
        return value
