# -*- coding: utf-8 -*-
"""ai_search_common.py のテスト。"""
import codecs
import os
import shutil
import tempfile
import unittest

import helpers  # noqa: F401  （scripts を import できるようにする）

common = helpers.load_script("ai_search_common")


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_bytes(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path


class NormalizeTextTest(unittest.TestCase):
    def test_fullwidth_and_case(self):
        self.assertEqual(common.normalize_text("ＫＡＫＵＵ　Coffee"), "kakuu coffee")

    def test_halfwidth_kana(self):
        self.assertEqual(common.normalize_text("ｶｸｳ"), "カクウ")

    def test_whitespace_collapsed(self):
        self.assertEqual(common.normalize_text("a \t\n  b　　c"), "a b c")

    def test_dashes_unified_but_long_vowel_kept(self):
        self.assertEqual(common.normalize_text("Kakuu‐Coffee−x—y"), "kakuu-coffee-x-y")
        self.assertEqual(common.normalize_text("コーヒー"), "コーヒー")


class SanitizeTest(unittest.TestCase):
    def test_formula_prefixed_and_restored(self):
        self.assertEqual(common.sanitize_cell("=1+1"), "'=1+1")
        self.assertEqual(common.unsanitize_cell("'=1+1"), "=1+1")

    def test_numbers_untouched(self):
        self.assertEqual(common.sanitize_cell("-3"), "-3")
        self.assertEqual(common.sanitize_cell("-2.5"), "-2.5")

    def test_text_starting_with_minus(self):
        self.assertEqual(common.sanitize_cell("-20度"), "'-20度")

    def test_other_dangerous_heads(self):
        for head in ("+", "@", "\t", "\r"):
            self.assertEqual(common.sanitize_cell(head + "x"), "'" + head + "x")

    def test_unsanitize_leaves_plain_quote(self):
        self.assertEqual(common.unsanitize_cell("'abc"), "'abc")

    def test_non_string(self):
        self.assertEqual(common.sanitize_cell(12), "12")
        self.assertEqual(common.sanitize_cell(None), "")


class ReadTextTest(TempDirCase):
    def test_utf8_bom(self):
        p = self.write_bytes("a.txt", codecs.BOM_UTF8 + "架空珈琲".encode("utf-8"))
        self.assertEqual(common.read_text(p), "架空珈琲")

    def test_utf16_bom(self):
        p = self.write_bytes("b.txt", codecs.BOM_UTF16_LE + "架空珈琲".encode("utf-16-le"))
        self.assertEqual(common.read_text(p), "架空珈琲")

    def test_cp932(self):
        p = self.write_bytes("c.txt", "架空珈琲".encode("cp932"))
        self.assertEqual(common.read_text(p), "架空珈琲")

    def test_crlf_and_cr(self):
        p = self.write_bytes("d.txt", b"a\r\nb\rc\n")
        self.assertEqual(common.read_text(p), "a\nb\nc\n")


class CsvTest(TempDirCase):
    def test_read_cp932_csv(self):
        data = "prompt_id,prompt\r\nP001,架空珈琲の豆はどこで買えますか\r\n".encode("cp932")
        p = self.write_bytes("p.csv", data)
        fields, rows = common.read_csv(p)
        self.assertEqual(fields, ["prompt_id", "prompt"])
        self.assertEqual(rows[0]["prompt"], "架空珈琲の豆はどこで買えますか")

    def test_blank_rows_dropped_and_cells_stripped(self):
        p = self.write_bytes("q.csv", " a , b \n 1 , '=x \n,\n\n".encode("utf-8"))
        fields, rows = common.read_csv(p)
        self.assertEqual(fields, ["a", "b"])
        self.assertEqual(rows, [{"a": "1", "b": "=x"}])

    def test_write_csv_bom_and_sanitize(self):
        p = os.path.join(self.tmp, "out.csv")
        common.write_csv(p, ["a", "b", "c"], [{"a": "=cmd", "b": -1, "c": 2.5}])
        with open(p, "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(codecs.BOM_UTF8))
        text = raw.decode("utf-8-sig")
        self.assertIn("'=cmd,-1,2.5", text)
        _, rows = common.read_csv(p)
        self.assertEqual(rows[0]["a"], "=cmd")

    def test_write_csv_missing_keys_are_blank(self):
        p = os.path.join(self.tmp, "out2.csv")
        common.write_csv(p, ["a", "b"], [{"a": "x"}])
        _, rows = common.read_csv(p)
        self.assertEqual(rows[0]["b"], "")


class FrontMatterTest(unittest.TestCase):
    def test_basic(self):
        text = "---\nround: R1\nsurface: web   # 画面\nmode: C# モード\nempty:\nKey: v\n---\n## 回答\n本文\n"
        meta, body, errors = common.parse_front_matter(text)
        self.assertEqual(meta["round"], "R1")
        self.assertEqual(meta["surface"], "web")
        self.assertEqual(meta["mode"], "C# モード")
        self.assertEqual(meta["empty"], "")
        self.assertEqual(meta["key"], "v")
        self.assertEqual(body, "## 回答\n本文\n")
        self.assertEqual(errors, [])

    def test_value_with_colon(self):
        meta, _, errors = common.parse_front_matter("---\nobserved_at: 2026-10-01 14:05\n---\n")
        self.assertEqual(meta["observed_at"], "2026-10-01 14:05")
        self.assertEqual(errors, [])

    def test_line_without_colon(self):
        meta, _, errors = common.parse_front_matter("---\nround R1\nservice: chatgpt\n---\nx")
        self.assertEqual(meta, {"service": "chatgpt"})
        self.assertEqual(len(errors), 1)
        self.assertIn("round R1", errors[0])

    def test_no_front_matter(self):
        meta, body, errors = common.parse_front_matter("## 回答\nx\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "## 回答\nx\n")
        self.assertEqual(len(errors), 1)

    def test_unclosed(self):
        meta, body, errors = common.parse_front_matter("---\nround: R1\n## 回答\n")
        self.assertEqual(body, "")
        self.assertTrue(any("終わりの ---" in e for e in errors), errors)

    def test_crlf_and_bom(self):
        text = "﻿---\r\nround: R1\r\nservice: chatgpt\r\n---\r\n## 回答\r\nx\r\n"
        meta, body, errors = common.parse_front_matter(text)
        self.assertEqual(meta["round"], "R1")
        self.assertEqual(meta["service"], "chatgpt")
        self.assertEqual(body, "## 回答\nx\n")
        self.assertEqual(errors, [])


class EntitiesTest(TempDirCase):
    HEAD = "entity_id,kind,name,terms,exclude_terms,domains\n"

    def write(self, body):
        return self.write_bytes("entities.csv", (self.HEAD + body).encode("utf-8"))

    def test_ok(self):
        p = self.write("own-company,own,架空珈琲,架空珈琲|kakuu coffee,,www.Kakuu-Coffee.example.\n"
                       "comp-a,competitor,サンプル焙煎,サンプル焙煎,,sample-roast.example\n")
        ents = common.load_entities(p)
        self.assertEqual(len(ents), 2)
        self.assertEqual(ents[0]["terms"], ["架空珈琲", "kakuu coffee"])
        self.assertEqual(ents[0]["domains"], ["kakuu-coffee.example"])
        self.assertEqual(ents[0]["exclude_terms"], [])
        self.assertEqual(ents[1]["kind"], "competitor")

    def test_errors(self):
        bad = [
            "comp-a,competitor,サンプル焙煎,サンプル焙煎,,sample-roast.example\n",  # own がない
            "own-company,owner,架空珈琲,架空珈琲,,\n",  # kind の誤り
            "own-company,own,架空珈琲,架空珈琲,,\nown-company,own,別名,別名,,\n",  # 重複
            "own-company,own,架空珈琲,架空珈琲,,https://kakuu-coffee.example\n",  # スキーム付き
            "own company,own,架空珈琲,架空珈琲,,\n",  # ID の誤り
            "own-company,own,架空珈琲,,,\n",  # terms も domains も空
            "own-company,own,架空珈琲,架空珈琲,,kakuu-coffee.example\n"
            "comp-a,competitor,他社,他社,,www.kakuu-coffee.example\n",  # 自社と競合でドメインが重複
        ]
        for body in bad:
            p = self.write(body)
            with self.assertRaises(common.InputError, msg=body):
                common.load_entities(p)


class PromptsTest(TempDirCase):
    HEAD = "prompt_id,prompt,stage,branded,intent_group,source,active,added_on\n"

    def write(self, body):
        return self.write_bytes("prompts.csv", (self.HEAD + body).encode("utf-8"))

    def test_ok(self):
        p = self.write("P001,架空珈琲の評判は,購入,指名,,問い合わせ,yes,2026-09-26\n")
        prompts = common.load_prompts(p)
        self.assertEqual(prompts["P001"]["stage"], "購入")

    def test_errors(self):
        for body in ("P001,x,検討,指名,,,yes,\n", "P 1,x,購入,指名,,,yes,\n",
                     "P001,x,購入,指名,,,yes,\nP001,y,購入,指名,,,yes,\n", "P001,x,購入,自社,,,yes,\n"):
            p = self.write(body)
            with self.assertRaises(common.InputError, msg=body):
                common.load_prompts(p)


class Sha256Test(TempDirCase):
    def test_sha256(self):
        p = self.write_bytes("h.txt", b"abc")
        self.assertEqual(common.sha256_file(p),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class ConstantsTest(unittest.TestCase):
    def test_status_values(self):
        self.assertIn("", common.STATUS_VALUES)
        self.assertIn("AI の回答なし", common.STATUS_VALUES)
        self.assertEqual(common.SOURCES_STATUS_VALUES, ("", "記録済み", "なし", "不明"))


class MiscTest(unittest.TestCase):
    def test_split_list(self):
        self.assertEqual(common.split_list(" a | b ||c "), ["a", "b", "c"])
        self.assertEqual(common.split_list(""), [])

    def test_parse_id_list(self):
        self.assertEqual(common.parse_id_list("P1, P2 P1"), ["P1", "P2"])
        self.assertEqual(common.parse_id_list(""), [])


if __name__ == "__main__":
    unittest.main()
