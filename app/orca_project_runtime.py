"""Load project-to-loopback assignments from the operator's deployment config."""

import json
import os
from pathlib import Path
import re
import stat


SOCKET_ROOT = Path("/run/kosmos-orca-projects")
HOME_ROOT = Path("/var/lib/kosmos-orca-projects")
SHARED_SOCKET = Path("/run/kosmos-orca-broker/pair.sock")
MAX_REGISTRY_BYTES = 65536


def project_account(project_id):
    if type(project_id) is not int or not 0 < project_id < 2**31:
        raise ValueError("Invalid project ID")
    return f"kosmos-orca-p{project_id}", HOME_ROOT / str(project_id)


def unique_object(pairs):
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("Duplicate project runtime entry")
    return values


def load_project_ports(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        mode = os.fstat(stream.fileno()).st_mode
        if not stat.S_ISREG(mode) or (os.name == "posix" and mode & 0o022):
            raise ValueError("Project runtime registry must be a protected regular file")
        data = stream.read(MAX_REGISTRY_BYTES + 1)
    if len(data) > MAX_REGISTRY_BYTES:
        raise ValueError("Project runtime registry exceeds its maximum size")
    entries = json.loads(data, object_pairs_hook=unique_object)
    if not isinstance(entries, dict):
        raise ValueError("Expected a project runtime mapping")
    ports = {}
    for project, port in entries.items():
        if not re.fullmatch(r"[1-9][0-9]{0,9}", project) or int(project) > 2**31 - 1:
            raise ValueError("Invalid project ID in the runtime registry")
        if type(port) is not int or not 18000 <= port <= 18999:
            raise ValueError("Invalid project runtime port")
        ports[int(project)] = port
    if len(set(ports.values())) != len(ports):
        raise ValueError("Project runtimes must have different ports")
    return ports
