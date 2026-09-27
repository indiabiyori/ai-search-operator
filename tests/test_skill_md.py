# -*- coding: utf-8 -*-
"""SKILL.md の先頭の欄と相対リンクのテスト。claude plugin validate は SKILL.md の中身を見ないため。"""
import os
import re
import unittest

import helpers  # noqa: F401

common = helpers.load_script("ai_search_common")
SKILL_MD = os.path.join(helpers.SKILL_DIR, "SKILL.md")
LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


class SkillMdTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SKILL_MD, encoding="utf-8") as f:
            cls.text = f.read()
        cls.meta, cls.body, cls.errors = common.parse_front_matter(cls.text)

    def test_front_matter_keys(self):
        self.assertEqual(self.errors, [])
        self.assertEqual(set(self.meta), {"name", "description"})
        self.assertEqual(self.meta["name"], "ai-search-operator")

    def test_description_length(self):
        # Claude Code の上限は description と when_to_use を合わせて 1,536 字
        description = self.meta["description"].strip('"')
        self.assertGreater(len(description), 100)
        self.assertLessEqual(len(description), 1536)

    def test_description_does_not_offer_perplexity(self):
        # 一般向けの画面での Perplexity の手動の観測は非対応（2026-09-27 の決定）
        self.assertNotIn("Perplexity", self.meta["description"])

    def test_relative_links_exist(self):
        base = os.path.dirname(SKILL_MD)
        for target in LINK_RE.findall(self.body):
            if "://" in target:
                continue
            self.assertTrue(os.path.exists(os.path.join(base, target)), target)


if __name__ == "__main__":
    unittest.main()
