"""fallbackchain —— 自检测试。

描述多级回退策略，验证每级的触发条件、输出契约与终止条件。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fallbackchain  # noqa: E402


class TestFallbackChain(unittest.TestCase):
    def test_valid_policy_passes(self):
        policy = {"levels": [
            {"name": "primary", "model": "gpt-4o",
             "trigger": {"on": ["timeout"]},
             "output_contract": {"type": "json", "required": ["answer"]},
             "terminal": False},
            {"name": "fallback", "model": "claude",
             "trigger": {"on": ["timeout"]},
             "output_contract": {"type": "json", "required": ["answer"]},
             "terminal": True},
        ]}
        r = fallbackchain.validate(policy)
        self.assertEqual(r["findings"], [])
        self.assertTrue(r["summary"]["contracts_consistent"])

    def test_missing_terminal_is_caught(self):
        policy = {"levels": [
            {"name": "primary", "model": "gpt-4o",
             "trigger": {"on": ["timeout"]},
             "output_contract": {"type": "json", "required": ["a"]},
             "terminal": False},
        ]}
        r = fallbackchain.validate(policy)
        kinds = [f["kind"] for f in r["findings"]]
        self.assertIn("no_terminal", kinds)

    def test_contract_mismatch_is_caught(self):
        policy = {"levels": [
            {"name": "primary", "model": "gpt-4o",
             "trigger": {"on": ["timeout"]},
             "output_contract": {"type": "json", "required": ["answer"]},
             "terminal": False},
            {"name": "fallback", "model": "claude",
             "trigger": {"on": ["timeout"]},
             "output_contract": {"type": "text", "required": ["body"]},
             "terminal": True},
        ]}
        r = fallbackchain.validate(policy)
        kinds = [f["kind"] for f in r["findings"]]
        self.assertIn("contract_mismatch", kinds)

    def test_duplicate_model_is_caught(self):
        policy = {"levels": [
            {"name": "a", "model": "same", "trigger": {"on": ["timeout"]},
             "output_contract": {"type": "json", "required": ["a"]}, "terminal": False},
            {"name": "b", "model": "same", "trigger": {"on": ["timeout"]},
             "output_contract": {"type": "json", "required": ["a"]}, "terminal": True},
        ]}
        r = fallbackchain.validate(policy)
        kinds = [f["kind"] for f in r["findings"]]
        self.assertIn("duplicate_model", kinds)

    def test_empty_policy(self):
        r = fallbackchain.validate({"levels": []})
        self.assertTrue(r["findings"])
