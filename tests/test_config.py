#!/usr/bin/env python3
"""Guards for config/litellm.yaml — the rules that make the gateway safe to share.

    python3 tests/test_config.py
"""
import re
import unittest
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "litellm.yaml").read_text())
CAPABILITIES = {"fast-json", "general", "reasoning", "long-context", "embed"}   # public contract
NVIDIA_RPM_BUDGET = 30          # of the ~40/min free-tier account limit (headroom)


def groups():
    g = defaultdict(list)
    for m in CFG["model_list"]:
        g[m["model_name"]].append(m)
    return g


def chain(cap):
    fb = {k: v for d in CFG["litellm_settings"]["fallbacks"] for k, v in d.items()}
    return [cap] + fb.get(cap, [])


class Config(unittest.TestCase):
    def test_public_capabilities_exist(self):
        self.assertTrue(CAPABILITIES <= set(groups()))

    def test_every_fallback_target_is_defined(self):
        g = groups()
        for d in CFG["litellm_settings"]["fallbacks"]:
            for src, targets in d.items():
                self.assertIn(src, g)
                for t in targets:
                    self.assertIn(t, g, f"fallback {src} -> {t} undefined")

    def test_each_capability_has_failover_across_families(self):
        g = groups()
        for cap in CAPABILITIES:
            fams = {m["model_info"]["gw_family"] for name in chain(cap) for m in g[name]}
            self.assertGreaterEqual(len(chain(cap)), 2, f"{cap}: no fallback")
            self.assertGreaterEqual(len(fams), 2, f"{cap}: all fallbacks in one model family")

    def test_secrets_are_env_references_only(self):
        for m in CFG["model_list"]:
            key = m["litellm_params"].get("api_key")
            if key and m["model_info"].get("gw_cost") != "test":
                self.assertTrue(str(key).startswith("os.environ/"), f"{m['model_name']}: literal api_key")
        for k in ("master_key", "database_url"):
            self.assertTrue(CFG["general_settings"][k].startswith("os.environ/"))

    def test_nvidia_rpm_fits_the_free_tier(self):
        total = 0
        for m in CFG["model_list"]:
            if m["litellm_params"]["model"].startswith("nvidia_nim/"):
                self.assertIn("rpm", m["litellm_params"], f"{m['model_name']}: NVIDIA deployment without rpm")
                total += m["litellm_params"]["rpm"]
        self.assertLessEqual(total, NVIDIA_RPM_BUDGET)

    def test_model_ids_are_pinned_not_aliases(self):
        for m in CFG["model_list"]:
            self.assertFalse(re.search(r"latest|~", m["litellm_params"]["model"]), m["model_name"])

    def test_routing_lives_in_git(self):
        self.assertFalse(CFG["general_settings"]["store_model_in_db"])

    def test_selftest_chain_needs_no_provider(self):
        g = groups()
        self.assertEqual(chain("selftest"), ["selftest", "selftest.2"])
        self.assertIn("mock_response", g["selftest.2"][0]["litellm_params"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
