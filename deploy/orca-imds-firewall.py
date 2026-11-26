"""Apply the dedicated Orca IMDS filter without rewriting other firewall tables."""

import re
import subprocess


NFT = "/usr/sbin/nft"
TABLE = "kosmos_orca_imds"
PROJECT_ACCOUNT = re.compile(r"kosmos-orca-p[1-9][0-9]*\Z")


def orca_uids(accounts):
    shared = []
    projects = []
    unrelated = set()
    for account in accounts:
        if account.pw_name == "orca":
            shared.append(account.pw_uid)
        elif PROJECT_ACCOUNT.fullmatch(account.pw_name):
            projects.append(account.pw_uid)
        else:
            unrelated.add(account.pw_uid)
    if len(shared) != 1:
        raise ValueError("Expected one shared Orca account")
    blocked = set(shared + projects)
    if blocked & unrelated:
        raise ValueError("An Orca UID also belongs to an unrelated account")
    return sorted(blocked)


def rules_for(uids, *, upstreams=None, portal_uid=None):
    uids = list(uids)
    if not uids or any(type(uid) is not int or not 0 < uid < 2**32 - 1 for uid in uids):
        raise ValueError("Expected non-root OS user IDs")
    uid_set = "{ " + ", ".join(str(uid) for uid in sorted(set(uids))) + " }"
    project_rules = ""
    if upstreams:
        if type(portal_uid) is not int or not 0 < portal_uid < 2**32 - 1 or portal_uid in uids:
            raise ValueError("Expected a separate portal account")
        if (len(set(upstreams.values())) != len(upstreams)
                or any(type(port) is not int or not 18000 <= port <= 18999
                       or type(owner) is not int or owner not in uids for port, owner in upstreams.items())):
            raise ValueError("Invalid dedicated runtime port or owner")
        for port, owner in sorted(upstreams.items()):
            allowed = ", ".join(str(uid) for uid in sorted((0, owner, portal_uid)))
            project_rules += f"        fib daddr type local tcp dport {port} meta skuid != {{ {allowed} }} reject\n"
        owners = ", ".join(str(uid) for uid in sorted(upstreams.values()))
        project_rules += f"        fib daddr type local tcp dport 6768 meta skuid {{ {owners} }} reject\n"
    return f"""add table inet {TABLE}
delete table inet {TABLE}
table inet {TABLE} {{
    chain output {{
        type filter hook output priority -10; policy accept;
        meta skuid {uid_set} ip daddr 169.254.169.254 reject
        meta skuid {uid_set} ip6 daddr fd00:ec2::254 reject
{project_rules}    }}
    chain input {{
        type filter hook input priority -10; policy accept;
        iifname != "lo" tcp dport 18000-18999 drop
    }}
}}
"""


def main():
    import os
    import pwd
    from pathlib import Path
    import sys

    registry = os.getenv("ORCA_PROJECT_REGISTRY")
    upstreams = None
    portal_uid = None
    if registry is not None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.orca_project_runtime import load_project_ports, project_account

        upstreams = {port: pwd.getpwnam(project_account(project_id)[0]).pw_uid
                     for project_id, port in load_project_ports(registry).items()}
        portal_uid = pwd.getpwnam("kosmos-portal").pw_uid
    rules = rules_for(orca_uids(pwd.getpwall()), upstreams=upstreams, portal_uid=portal_uid)
    subprocess.run([NFT, "-f", "-"], input=rules, text=True, check=True)


if __name__ == "__main__":
    main()
