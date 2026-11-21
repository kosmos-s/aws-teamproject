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


def rules_for(uids):
    uids = list(uids)
    if not uids or any(type(uid) is not int or not 0 < uid < 2**32 - 1 for uid in uids):
        raise ValueError("Expected non-root OS user IDs")
    uid_set = "{ " + ", ".join(str(uid) for uid in sorted(set(uids))) + " }"
    return f"""add table inet {TABLE}
delete table inet {TABLE}
table inet {TABLE} {{
    chain output {{
        type filter hook output priority -10; policy accept;
        meta skuid {uid_set} ip daddr 169.254.169.254 reject
        meta skuid {uid_set} ip6 daddr fd00:ec2::254 reject
    }}
}}
"""


def main():
    import pwd

    rules = rules_for(orca_uids(pwd.getpwall()))
    subprocess.run([NFT, "-f", "-"], input=rules, text=True, check=True)


if __name__ == "__main__":
    main()
