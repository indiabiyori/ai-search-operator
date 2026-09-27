# -*- coding: utf-8 -*-
"""ai_search_common.py のテスト。"""
import codecs
import contextlib
import csv
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

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


class CsvNulTest(TempDirCase):
    """
    NUL（\\x00）の扱いを csv モジュールの版に任せない。Python 3.9 の csv.reader は NUL を含む行で csv.Error を
    出し、3.11 以降は読む。書くときも読むときも NUL を除き、どちらの版でも同じ結果にする。
    """

    def test_write_csv_strips_nul(self):
        p = os.path.join(self.tmp, "nul.csv")
        common.write_csv(p, ["a\x00", "b"], [{"a\x00": "架空\x00珈琲", "b": "\x00=1+1"}])
        with open(p, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"\x00", raw)
        fields, rows = common.read_csv(p)
        self.assertEqual(fields, ["a", "b"])
        self.assertEqual(rows, [{"a": "架空珈琲", "b": "=1+1"}])

    def test_write_csv_stream_strips_nul_without_sanitize(self):
        stream = io.StringIO()
        common.write_csv_stream(stream, ["a"], [{"a": "x\x00y"}], sanitize=False)
        self.assertEqual(stream.getvalue(), "a\r\nxy\r\n")

    def test_read_csv_strips_nul_on_every_version(self):
        data = "prompt_id,prompt,intent_group\r\nP001,架空珈琲の\x00豆,浅煎り\x00\r\n\x00\r\n".encode("utf-8")
        p = self.write_bytes("p.csv", data)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            fields, rows = common.read_csv(p)
        self.assertEqual(fields, ["prompt_id", "prompt", "intent_group"])
        self.assertEqual(rows, [{"prompt_id": "P001", "prompt": "架空珈琲の豆", "intent_group": "浅煎り"}])
        self.assertIn("NUL", err.getvalue())

    def test_read_csv_without_nul_does_not_warn(self):
        p = self.write_bytes("ok.csv", b"a,b\r\n1,2\r\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            common.read_csv(p)
        self.assertEqual(err.getvalue(), "")


class CsvFieldSizeTest(TempDirCase):
    """write_csv が書けた長いセルを、read_csv が csv の既定の上限（131072 文字）で拒まない。"""

    def setUp(self):
        TempDirCase.setUp(self)
        self.saved = csv.field_size_limit()
        csv.field_size_limit(131072)  # ほかのテストが上げていても、既定の上限から始める

    def tearDown(self):
        csv.field_size_limit(self.saved)
        TempDirCase.tearDown(self)

    def test_long_cell_round_trip(self):
        long_value = "|".join("https://kakuu-coffee.example/page/{:05d}".format(i) for i in range(5000))
        self.assertGreater(len(long_value), 131072)
        p = os.path.join(self.tmp, "long.csv")
        common.write_csv(p, ["own_cited_urls"], [{"own_cited_urls": long_value}])
        _, rows = common.read_csv(p)
        self.assertEqual(rows[0]["own_cited_urls"], long_value)

    def test_field_size_limit_falls_back_when_sys_maxsize_overflows(self):
        # Windows では C の long が 32 ビットなので、sys.maxsize を渡すと OverflowError になる
        real = csv.field_size_limit
        tried = []

        def fake(*args):
            if args:
                tried.append(args[0])
                if args[0] > 2 ** 31 - 1:
                    raise OverflowError("Python int too large to convert to C long")
            return real(*args)

        with mock.patch.object(common.csv, "field_size_limit", side_effect=fake):
            common.raise_csv_field_size_limit()
        self.assertEqual(tried[0], sys.maxsize)
        limit = csv.field_size_limit()
        self.assertLessEqual(limit, 2 ** 31 - 1)
        self.assertGreaterEqual(limit, 16 * 1024 * 1024)


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

    def test_idn_domains_in_either_form_collide(self):
        # 日本語ドメインの Unicode 表記と Punycode 表記は同じドメイン。自社と競合に分けて書けば入力の誤り
        p = self.write("own-company,own,架空珈琲,架空珈琲,,架空珈琲.jp\n"
                       "comp-a,competitor,他社,他社,,xn--6tvq2ydjak8s.jp\n")
        with self.assertRaises(common.InputError) as cm:
            common.load_entities(p)
        self.assertIn("xn--6tvq2ydjak8s.jp", str(cm.exception))

    def test_domains_are_stored_in_ascii(self):
        p = self.write("own-company,own,架空珈琲,架空珈琲,,ｗｗｗ．架空珈琲．ｊｐ|ＫＡＫＵＵ-coffee.example\n")
        self.assertEqual(common.load_entities(p)[0]["domains"], ["xn--6tvq2ydjak8s.jp", "kakuu-coffee.example"])


class NormalizeDomainTest(unittest.TestCase):
    """entities.csv のドメイン。NFKC と小文字にそろえ、ラベルごとに IDNA（ASCII）に変換してから形を確かめる。"""

    def norm(self, value):
        return common.normalize_domain(value, "entities.csv の 2 行目")

    def test_normalized_forms(self):
        cases = (
            ("kakuu-coffee.example", "kakuu-coffee.example"),
            ("www.Kakuu-Coffee.example.", "kakuu-coffee.example"),
            ("ｋａｋｕｕ-coffee．example", "kakuu-coffee.example"),  # 全角の英字と点
            ("　kakuu-coffee.example　", "kakuu-coffee.example"),  # 全角の空白
            ("架空珈琲.jp", "xn--6tvq2ydjak8s.jp"),
            ("www.架空珈琲.jp", "xn--6tvq2ydjak8s.jp"),
            ("架空珈琲。jp", "xn--6tvq2ydjak8s.jp"),  # 日本語入力の句点
            ("kakuu-coffee.example。", "kakuu-coffee.example"),
            ("XN--6TVQ2YDJAK8S.JP", "xn--6tvq2ydjak8s.jp"),
            ("shop.架空珈琲.jp", "shop.xn--6tvq2ydjak8s.jp"),
            ("www.example", "www.example"),  # 外すと1つのラベルだけになる www. は残す
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(self.norm(value), expected)

    def test_invalid_forms_raise_with_reason(self):
        cases = (
            ("*.indiabiyori.jp", "ワイルドカード"),
            (".indiabiyori.jp", "先頭の ."),
            ("indiabiyori.jp:443", "ポート"),
            ("indiabiyori..jp", "空のラベル"),
            ("indiabiyori.jp,shop.indiabiyori.jp", "| で区切って"),
            ("indiabiyori.jp、shop.indiabiyori.jp", "| で区切って"),
            ("indiabiyori jp", "空白"),
            ("https://indiabiyori.jp", "スキームやパス"),
            ("indiabiyori.jp/menu", "スキームやパス"),
            ("localhost", "ドメインの形"),
            ("-indiabiyori.jp", "ドメインの形"),
            ("a" * 64 + ".jp", "63 文字"),
            (".", "ドメインの形"),
        )
        for value, reason in cases:
            with self.subTest(value=value):
                with self.assertRaises(common.InputError) as cm:
                    self.norm(value)
                message = str(cm.exception)
                self.assertIn(reason, message)
                self.assertIn("entities.csv の 2 行目", message)
                self.assertIn(value, message)


class AsciiHostTest(unittest.TestCase):
    """URL のホストを、entities.csv のドメインと同じ ASCII（Punycode）の形にそろえる。"""

    def test_ascii_host(self):
        self.assertEqual(common.ascii_host("架空珈琲.jp"), "xn--6tvq2ydjak8s.jp")
        self.assertEqual(common.ascii_host("WWW.架空珈琲.JP."), "www.xn--6tvq2ydjak8s.jp")
        self.assertEqual(common.ascii_host("xn--6tvq2ydjak8s.jp"), "xn--6tvq2ydjak8s.jp")
        self.assertEqual(common.ascii_host("Kakuu-Coffee.example"), "kakuu-coffee.example")
        self.assertEqual(common.ascii_host("::1"), "::1")

    def test_unconvertible_host_is_returned_lowercased(self):
        self.assertEqual(common.ascii_host("A..b"), "a..b")
        self.assertEqual(common.ascii_host("a" * 64 + ".example"), "a" * 64 + ".example")
        self.assertEqual(common.ascii_host(""), "")


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


class FormatRateTest(unittest.TestCase):
    def test_rounds_half_up(self):
        # 6.25% は四捨五入で 6.3%（float の書式の偶数丸めでは 6.2% になる）
        self.assertEqual(common.format_rate(5, 80), "5/80（6.3%）")
        self.assertEqual(common.format_rate(1, 16), "1/16（6.3%）")
        self.assertEqual(common.format_rate(3, 16), "3/16（18.8%）")
        self.assertEqual(common.format_rate(12, 88), "12/88（13.6%）")

    def test_edges(self):
        self.assertEqual(common.format_rate(0, 5), "0/5（0.0%）")
        self.assertEqual(common.format_rate(5, 5), "5/5（100.0%）")
        self.assertEqual(common.format_rate(1, 3), "1/3（33.3%）")
        self.assertEqual(common.format_rate(2, 3), "2/3（66.7%）")
        self.assertEqual(common.format_rate(0, 0), "0/0（分母なし）")

    def test_same_as_compare_runs_for_many_values(self):
        from decimal import Decimal, ROUND_HALF_UP
        for n in range(1, 121):
            for k in range(n + 1):
                pct = (Decimal(k * 100) / Decimal(n)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                self.assertEqual(common.format_rate(k, n), "{}/{}（{}%）".format(k, n, pct), (k, n))


class WorkspaceHintTest(TempDirCase):
    def test_hint_when_current_folder_has_the_file(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            self.assertEqual(common.workspace_hint(os.path.join("ai-search", "entities.csv"), "entities.csv"), "")
            self.write_bytes("entities.csv", b"")
            hint = common.workspace_hint(os.path.join("ai-search", "entities.csv"), "entities.csv")
            self.assertIn("--workspace .", hint)
            self.assertIn("entities.csv", hint)
            # 既定の場所が今のフォルダそのもの（--workspace .）なら案内しない
            self.assertEqual(common.workspace_hint("entities.csv", "entities.csv"), "")
        finally:
            os.chdir(cwd)


class ArgumentParserTest(unittest.TestCase):
    def test_help_in_japanese(self):
        parser = common.ArgumentParser(prog="x.py", description="説明")
        parser.add_argument("--round", required=True)
        text = parser.format_help()
        self.assertIn("この使い方を表示して終わる", text)
        self.assertNotIn("show this help message", text)

    def test_error_in_japanese_exit_2(self):
        import contextlib
        import io
        parser = common.ArgumentParser(prog="x.py")
        parser.add_argument("--round", required=True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                parser.parse_args([])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("次の引数が必要です: --round", err.getvalue())

    def test_translate_unknown_message(self):
        self.assertEqual(common.translate_argparse("something else"), "something else")
        self.assertEqual(common.translate_argparse("unrecognized arguments: --x"), "使えない引数があります: --x")


if __name__ == "__main__":
    unittest.main()
