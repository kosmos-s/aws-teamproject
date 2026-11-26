import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


def load_firewall():
    path = Path(__file__).resolve().parents[1] / "deploy" / "orca-imds-firewall.py"
    spec = importlib.util.spec_from_file_location("orca_imds_firewall", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


class OrcaImdsFirewallTests(unittest.TestCase):
    def test_rules_only_target_orca_uids_and_metadata_addresses(self):
        rules = load_firewall().rules_for([1201, 1200, 1201])
        self.assertIn("policy accept", rules)
        self.assertIn("meta skuid { 1200, 1201 } ip daddr 169.254.169.254 reject", rules)
        self.assertIn("meta skuid { 1200, 1201 } ip6 daddr fd00:ec2::254 reject", rules)
        self.assertNotIn("flush ruleset", rules)

    def test_never_blocks_root_or_uses_empty_rules(self):
        worker = load_firewall()
        for uids in ([], [0, 1200], [-1], ["1200"]):
            with self.subTest(uids=uids), self.assertRaises(ValueError):
                worker.rules_for(uids)

    def test_service_accounts_exclude_portal_and_unrelated_accounts(self):
        accounts = [SimpleNamespace(pw_name=name, pw_uid=uid) for name, uid in (
            ("orca", 1200), ("kosmos-orca-p13", 1201), ("kosmos-portal", 1202),
            ("kosmos-orca-p0", 1203), ("kosmos-orca-dev", 1204),
        )]
        worker = load_firewall()
        self.assertEqual(worker.orca_uids(accounts), [1200, 1201])
        with self.assertRaises(ValueError):
            worker.orca_uids(accounts[1:])

    def test_rejects_an_uid_shared_with_an_unrelated_account(self):
        accounts = [SimpleNamespace(pw_name=name, pw_uid=1200) for name in ("orca", "kosmos-portal")]
        with self.assertRaises(ValueError):
            load_firewall().orca_uids(accounts)

    def test_project_ports_allow_only_their_owner_and_portal(self):
        rules = load_firewall().rules_for([1200, 1201, 1202],
                                           upstreams={18681: 1201, 18682: 1202}, portal_uid=1300)
        self.assertIn("fib daddr type local tcp dport 18681 meta skuid != { 0, 1201, 1300 } reject", rules)
        self.assertIn("fib daddr type local tcp dport 18682 meta skuid != { 0, 1202, 1300 } reject", rules)
        self.assertIn('iifname != "lo" tcp dport 18000-18999 drop', rules)
        self.assertIn("fib daddr type local tcp dport 6768 meta skuid { 1201, 1202 } reject", rules)

    def test_rejects_invalid_or_shared_project_port_policy(self):
        firewall = load_firewall()
        for upstreams, portal_uid in (({6768: 1201}, 1300), ({18681: 1205}, 1300),
                                       ({18681: 1201}, 1200), ({18681: 1201, 18682: 1201}, 1300)):
            with self.subTest(upstreams=upstreams, portal_uid=portal_uid), self.assertRaises(ValueError):
                firewall.rules_for([1200, 1201], upstreams=upstreams, portal_uid=portal_uid)
