# -*- coding: utf-8 -*-
"""new_round.py のテスト。データはすべて架空のもの。"""
import contextlib
import errno
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# python3 -m unittest tests.<モジュール名> でリポジトリのルートから実行しても helpers を読めるようにする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402
# helpers が scripts を sys.path に入れたあとで import する。new_round.py が import するものと同じモジュールになる
import ai_search_common as common  # noqa: E402

new_round = helpers.load_script("new_round")

TEMPLATE = os.path.join(helpers.SKILL_DIR, "templates", "answer.md")

# 仕様 6.3 の回答ファイルの先頭の欄（仕様の順番どおり）。実装の定数ではなく、仕様の文をそのまま写す
SPEC_FIELDS = [
    "round", "prompt_id", "prompt", "observed_at", "service", "surface", "mode", "login", "region",
    "repeat", "language", "status", "sources_status", "accuracy", "accuracy_note", "reviewed_by",
]
# 実装計画（Task 6）にある templates/answer.md の全文
PLAN_TEMPLATE = (
    "---\n"
    "round:\n"
    "prompt_id:\n"
    "prompt:\n"
    "observed_at:\n"
    "service:\n"
    "surface: web\n"
    "mode:\n"
    "login: なし\n"
    "region: JP\n"
    "repeat:\n"
    "language: ja\n"
    "status:\n"
    "sources_status:\n"
    "accuracy: 未確認\n"
    "accuracy_note:\n"
    "reviewed_by:\n"
    "---\n"
    "## 回答\n"
    "\n"
    "## 出典\n"
)
# 仕様 7.2 と実装計画の既定値（--repeats 3、--surface web、--login なし、--region JP、--language ja）
SPEC_DEFAULTS = {"surface": "web", "login": "なし", "region": "JP", "language": "ja"}
SPEC_DEFAULT_REPEATS = 3

PROMPTS_HEADER = "prompt_id,prompt,stage,branded,intent_group,source,active,added_on\n"
PROMPTS_ROWS = (
    "P001,架空珈琲の豆はどこで買えますか,購入,指名,購入先,問い合わせ,yes,2026-09-26\n"
    "P002,浅煎りのコーヒー豆のおすすめを教えてください,比較,非指名,浅煎り,GSC,yes,2026-09-26\n"
    "P003,コーヒー豆の焙煎度合いの違いは何ですか,認知,非指名,焙煎,サジェスト,yes,2026-09-26\n"
    "P004,架空珈琲とサンプル焙煎の違いは,比較,指名,比較,営業,no,2026-09-26\n"
)
PROMPT_TEXT = {
    "P001": "架空珈琲の豆はどこで買えますか",
    "P002": "浅煎りのコーヒー豆のおすすめを教えてください",
    "P003": "コーヒー豆の焙煎度合いの違いは何ですか",
    "P004": "架空珈琲とサンプル焙煎の違いは",
}


class WorkspaceCase(unittest.TestCase):
    """一時フォルダの下に ai-search/prompts.csv を置いて使う。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ai-search")
        os.makedirs(self.ws)
        self.write_prompts(PROMPTS_HEADER + PROMPTS_ROWS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_prompts(self, text, encoding="utf-8"):
        with open(os.path.join(self.ws, "prompts.csv"), "wb") as f:
            f.write(text.encode(encoding))

    def load_prompts(self):
        return common.load_prompts(os.path.join(self.ws, "prompts.csv"))

    def answer_path(self, rel):
        return os.path.join(self.ws, *rel.split("/"))

    def read_answer(self, rel):
        with open(self.answer_path(rel), "rb") as f:
            return f.read().decode("utf-8")

    def list_answers(self):
        """answers/ の下のファイルを、ワークスペースからの相対パス（/ 区切り）の集合で返す。"""
        found = set()
        root = os.path.join(self.ws, "answers")
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                rel = os.path.relpath(os.path.join(dirpath, name), self.ws)
                found.add(rel.replace(os.sep, "/"))
        return found

    def main_in_process(self, args):
        """main をこのプロセスで呼び、(終了コード, 標準エラーの文字列) を返す。"""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = new_round.main(list(args) + ["--workspace", self.ws])
        return code, err.getvalue()


def expected_paths(round_name, prompt_ids, services, repeats):
    return set("answers/{}/{}/{}-{}.md".format(round_name, s, p, r)
               for p in prompt_ids for s in services for r in range(1, repeats + 1))


class BuildAnswerTest(unittest.TestCase):
    def test_matches_template(self):
        # 手で作る人のためのテンプレートと、new_round.py が組み立てる形が一致する
        with open(TEMPLATE, "rb") as f:
            data = f.read()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"), "テンプレートに BOM を付けない")
        self.assertNotIn(b"\r", data, "テンプレートの改行は LF にする")
        self.assertEqual(new_round.build_answer({}), data.decode("utf-8"))

    def test_template_matches_plan(self):
        # 実装どうしの一致だけでは、両方を同じように間違えても通る。実装計画の全文と比べる
        with open(TEMPLATE, "rb") as f:
            self.assertEqual(f.read().decode("utf-8"), PLAN_TEMPLATE)
        self.assertEqual(new_round.build_answer({}), PLAN_TEMPLATE)

    def test_fields_follow_spec_order(self):
        # 仕様 6.3 の欄の集合と順番
        meta, _body, errors = common.parse_front_matter(new_round.build_answer({}))
        self.assertEqual(errors, [])
        self.assertEqual(list(meta.keys()), SPEC_FIELDS)
        with open(TEMPLATE, "rb") as f:
            meta, _body, errors = common.parse_front_matter(f.read().decode("utf-8"))
        self.assertEqual(errors, [])
        self.assertEqual(list(meta.keys()), SPEC_FIELDS)

    def test_template_parses_without_errors(self):
        meta, body, errors = common.parse_front_matter(new_round.build_answer({}))
        self.assertEqual(errors, [])
        self.assertEqual(list(meta.keys()), SPEC_FIELDS)
        self.assertEqual(meta["surface"], "web")
        self.assertEqual(meta["login"], "なし")
        self.assertEqual(meta["region"], "JP")
        self.assertEqual(meta["language"], "ja")
        self.assertEqual(meta["accuracy"], "未確認")
        self.assertEqual(meta["status"], "")
        self.assertEqual(meta["sources_status"], "")
        self.assertLess(body.index("## 回答"), body.index("## 出典"))

    def test_values_round_trip(self):
        meta = {"round": "2026-10-01", "prompt_id": "P001", "prompt": PROMPT_TEXT["P001"],
                "observed_at": "2026-10-01 ", "service": "chatgpt", "repeat": "2"}
        text = new_round.build_answer(meta)
        self.assertIn("\nobserved_at: 2026-10-01 \n", text)  # 時刻を書く場所を残す
        self.assertIn("\nstatus:\n", text)  # 空の欄の後ろに空白を付けない
        parsed, _body, errors = common.parse_front_matter(text)
        self.assertEqual(errors, [])
        self.assertEqual(parsed["prompt"], PROMPT_TEXT["P001"])
        self.assertEqual(parsed["observed_at"], "2026-10-01")
        self.assertEqual(parsed["repeat"], "2")
        self.assertEqual(parsed["surface"], "web")

    def test_newline_in_value_is_flattened(self):
        text = new_round.build_answer({"prompt": "一行目\r\n二行目\n三行目"})
        self.assertIn("\nprompt: 一行目 二行目 三行目\n", text)
        _meta, _body, errors = common.parse_front_matter(text)
        self.assertEqual(errors, [])


class PlanRoundTest(WorkspaceCase):
    def test_active_prompts_times_services_times_repeats(self):
        plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt", "google-ai-mode"], 2, None)
        self.assertEqual(len(plan), 12)
        self.assertEqual(set(rel for rel, _meta in plan),
                         expected_paths("2026-10-01", ["P001", "P002", "P003"], ["chatgpt", "google-ai-mode"], 2))

    def test_meta_values(self):
        plan = dict(new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt", "google-ai-mode"], 2, None))
        meta = plan["answers/2026-10-01/google-ai-mode/P002-2.md"]
        self.assertEqual(meta, {
            "round": "2026-10-01", "prompt_id": "P002", "prompt": PROMPT_TEXT["P002"],
            "observed_at": "2026-10-01 ", "service": "google-ai-mode", "surface": "web", "mode": "",
            "login": "なし", "region": "JP", "repeat": "2", "language": "ja", "status": "",
            "sources_status": "", "accuracy": "未確認", "accuracy_note": "", "reviewed_by": "",
        })

    def test_condition_options(self):
        plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["gemini"], 1, ["P001"],
                                    surface="app", login="あり（記憶オフ）", region="US", language="en")
        self.assertEqual(len(plan), 1)
        meta = plan[0][1]
        self.assertEqual((meta["surface"], meta["login"], meta["region"], meta["language"]),
                         ("app", "あり（記憶オフ）", "US", "en"))

    def test_observed_at_empty_when_round_is_not_a_date(self):
        for round_name in ("R1", "2026-13-01", "2026-10-01b"):
            plan = new_round.plan_round(self.load_prompts(), round_name, ["chatgpt"], 1, ["P001"])
            self.assertEqual(plan[0][1]["observed_at"], "", round_name)

    def test_explicit_prompt_ids(self):
        plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, ["P003", "P001"])
        self.assertEqual([rel for rel, _meta in plan],
                         ["answers/2026-10-01/chatgpt/P003-1.md", "answers/2026-10-01/chatgpt/P001-1.md"])

    def test_unknown_prompt_id(self):
        with self.assertRaises(new_round.InputError) as ctx:
            new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, ["P001", "P999"])
        self.assertIn("P999", str(ctx.exception))

    def test_inactive_prompt_used_with_warning_when_explicit(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, ["P004"])
        self.assertEqual([rel for rel, _meta in plan], ["answers/2026-10-01/chatgpt/P004-1.md"])
        self.assertIn("P004", err.getvalue())
        self.assertIn("警告", err.getvalue())

    def test_active_value_case_insensitive(self):
        self.write_prompts(PROMPTS_HEADER + PROMPTS_ROWS.replace(",yes,", ",YES,").replace(",no,", ",No,"))
        plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)
        self.assertEqual(len(plan), 3)

    def test_active_invalid_value(self):
        self.write_prompts(PROMPTS_HEADER + PROMPTS_ROWS.replace("GSC,yes,", "GSC,はい,").replace(
            "サジェスト,yes,", "サジェスト,,"))
        with self.assertRaises(new_round.InputError) as ctx:
            new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)
        self.assertIn("P002", str(ctx.exception))
        self.assertIn("P003", str(ctx.exception))

    def test_active_column_missing_uses_all_with_warning(self):
        text = "prompt_id,prompt,stage,branded\nP001,{},購入,指名\nP002,{},比較,非指名\n".format(
            PROMPT_TEXT["P001"], PROMPT_TEXT["P002"])
        self.write_prompts(text)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)
        self.assertEqual(len(plan), 2)
        self.assertIn("active", err.getvalue())

    def test_no_active_prompts(self):
        self.write_prompts(PROMPTS_HEADER + PROMPTS_ROWS.replace(",yes,", ",no,"))
        with self.assertRaises(new_round.InputError):
            new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)

    def test_invalid_arguments(self):
        prompts = self.load_prompts()
        cases = [
            dict(round_name="../x", services=["chatgpt"], repeats=1),
            dict(round_name="2026-10-01\n", services=["chatgpt"], repeats=1),
            dict(round_name="", services=["chatgpt"], repeats=1),
            dict(round_name="2026-10-01", services=["bard"], repeats=1),
            dict(round_name="2026-10-01", services=[], repeats=1),
            dict(round_name="2026-10-01", services=["chatgpt"], repeats=0),
            dict(round_name="2026-10-01", services=["chatgpt"], repeats=21),
        ]
        for case in cases:
            with self.assertRaises(new_round.InputError, msg=repr(case)):
                new_round.plan_round(prompts, case["round_name"], case["services"], case["repeats"], None)
        for kwargs in (dict(surface="browser"), dict(login="はい"), dict(region="J P"), dict(language="ja #x")):
            with self.assertRaises(new_round.InputError, msg=repr(kwargs)):
                new_round.plan_round(prompts, "2026-10-01", ["chatgpt"], 1, None, **kwargs)

    def test_empty_prompt(self):
        self.write_prompts(PROMPTS_HEADER + "P001,,購入,指名,,,yes,\n")
        with self.assertRaises(new_round.InputError) as ctx:
            new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)
        self.assertIn("P001", str(ctx.exception))

    def test_prompt_with_newline_is_flattened(self):
        self.write_prompts(PROMPTS_HEADER + 'P001,"架空珈琲の豆は\nどこで買えますか",購入,指名,,,yes,\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)
        self.assertEqual(plan[0][1]["prompt"], "架空珈琲の豆は どこで買えますか")
        self.assertIn("改行", err.getvalue())

    def test_prompt_with_hash_warns(self):
        # 「空白 + #」以降は先頭の欄でコメントとして読み飛ばされるので、先に知らせる
        self.write_prompts(PROMPTS_HEADER + "P001,架空珈琲の #1 の商品は,購入,指名,,,yes,\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)
        self.assertEqual(plan[0][1]["prompt"], "架空珈琲の #1 の商品は")
        self.assertIn("P001", err.getvalue())
        self.assertIn("#", err.getvalue())

    def test_ids_differing_only_in_case(self):
        # Windows と macOS の既定のファイルシステムでは P001-1.md と p001-1.md が同じファイルになる
        self.write_prompts(PROMPTS_HEADER
                           + "P001,架空珈琲の豆はどこで買えますか,購入,指名,,,yes,\n"
                           + "p001,サンプル焙煎の豆はどこで買えますか,購入,指名,,,yes,\n"
                           + "P002,浅煎りのコーヒー豆のおすすめを教えてください,比較,非指名,,,yes,\n")
        for prompt_ids in (None, ["p001", "P001"]):
            with self.assertRaises(new_round.InputError, msg=repr(prompt_ids)) as ctx:
                new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 2, prompt_ids)
            message = str(ctx.exception)
            self.assertIn("P001", message)
            self.assertIn("p001", message)
            self.assertIn("大文字・小文字", message)
            self.assertNotIn("P002", message)
        # 片方だけを選べば作れる
        plan = new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, ["p001", "P002"])
        self.assertEqual(len(plan), 2)

    def test_round_name_length_limit(self):
        # 長すぎるラウンド名は、ファイル名が長すぎるという OSError（終了コード 1）になる前に入力エラーにする
        prompts = self.load_prompts()
        plan = new_round.plan_round(prompts, "R" * new_round.MAX_NAME_LENGTH, ["chatgpt"], 1, ["P001"])
        self.assertEqual(len(plan), 1)
        with self.assertRaises(new_round.InputError) as ctx:
            new_round.plan_round(prompts, "R" * (new_round.MAX_NAME_LENGTH + 1), ["chatgpt"], 1, ["P001"])
        self.assertIn(str(new_round.MAX_NAME_LENGTH), str(ctx.exception))

    def test_prompt_id_length_limit(self):
        long_id = "P" * (new_round.MAX_NAME_LENGTH + 1)
        self.write_prompts(PROMPTS_HEADER + "{},架空珈琲の豆はどこで買えますか,購入,指名,,,yes,\n".format(long_id))
        with self.assertRaises(new_round.InputError) as ctx:
            new_round.plan_round(self.load_prompts(), "2026-10-01", ["chatgpt"], 1, None)
        self.assertIn(long_id, str(ctx.exception))

    def test_control_character_in_prompt(self):
        # NUL などの制御文字は回答ファイルにそのまま書かず、入力エラーにする（改行とタブは除く）
        for ch in ("\x00", "\x01", "\x1b", "\x7f"):
            prompts = {"P001": {"prompt_id": "P001", "prompt": "架空珈琲の{}豆".format(ch), "stage": "購入",
                                "branded": "指名", "active": "yes"}}
            with self.assertRaises(new_round.InputError, msg=repr(ch)) as ctx:
                new_round.plan_round(prompts, "2026-10-01", ["chatgpt"], 1, None)
            self.assertIn("P001", str(ctx.exception))
            self.assertIn("制御文字", str(ctx.exception))
        prompts = {"P001": {"prompt_id": "P001", "prompt": "架空珈琲の\t豆", "stage": "購入",
                            "branded": "指名", "active": "yes"}}
        self.assertEqual(len(new_round.plan_round(prompts, "2026-10-01", ["chatgpt"], 1, None)), 1)

    def test_region_and_language_reject_control_characters(self):
        prompts = self.load_prompts()
        for kwargs in (dict(region="J\x01P"), dict(language="ja\x7f"), dict(region="JP\n")):
            with self.assertRaises(new_round.InputError, msg=repr(kwargs)):
                new_round.plan_round(prompts, "2026-10-01", ["chatgpt"], 1, None, **kwargs)

    def test_mode_option(self):
        prompts = self.load_prompts()
        for mode in ("検索あり", "検索あり・Think", "GPT-5 Thinking", "C#"):
            plan = new_round.plan_round(prompts, "2026-10-01", ["chatgpt"], 1, ["P001"], mode=mode)
            self.assertEqual(plan[0][1]["mode"], mode)
        plan = new_round.plan_round(prompts, "2026-10-01", ["chatgpt"], 1, ["P001"], mode="  検索あり ")
        self.assertEqual(plan[0][1]["mode"], "検索あり")

    def test_mode_rejects_slash_hash_and_control_characters(self):
        prompts = self.load_prompts()
        for mode in ("GPT-5 Thinking/検索あり", "検索あり #メモ", "#検索あり", "検索\x00あり", "検索\nあり"):
            with self.assertRaises(new_round.InputError, msg=repr(mode)) as ctx:
                new_round.plan_round(prompts, "2026-10-01", ["chatgpt"], 1, None, mode=mode)
            self.assertIn("--mode", str(ctx.exception))


class WriteRoundTest(WorkspaceCase):
    """ファイルを書くときの OS のエラーを、traceback ではなく入力エラー（終了コード 2）にする。"""

    def plan(self, services=("claude", "chatgpt")):
        return new_round.plan_round(self.load_prompts(), "2026-10-01", list(services), 1, ["P001", "P002"])

    def test_makedirs_error_becomes_input_error_without_partial_files(self):
        # answers/<round>/<service> が普通のファイルのとき
        blocker = self.answer_path("answers/2026-10-01/chatgpt")
        os.makedirs(os.path.dirname(blocker))
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("")
        with self.assertRaises(new_round.InputError) as ctx:
            new_round.write_round(self.ws, self.plan())
        self.assertIn(os.path.join("2026-10-01", "chatgpt"), str(ctx.exception))
        # 先に処理する claude の分も作らない（途中まで書いたファイルを残さない）
        self.assertEqual(self.list_answers(), {"answers/2026-10-01/chatgpt"})

    def test_permission_error_becomes_input_error(self):
        with mock.patch.object(new_round.os, "makedirs", side_effect=PermissionError(errno.EACCES, "Permission denied")):
            with self.assertRaises(new_round.InputError):
                new_round.write_round(self.ws, self.plan())

    def test_open_error_becomes_input_error(self):
        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            if "x" in mode:
                raise OSError(errno.ENAMETOOLONG, "File name too long")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=fake_open):
            with self.assertRaises(new_round.InputError) as ctx:
                new_round.write_round(self.ws, self.plan())
        self.assertIn("P001-1.md", str(ctx.exception))

    def test_write_error_removes_the_partial_file(self):
        real_open = open

        class BrokenFile(object):
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()
                return False

            def write(self, text):
                self.f.write(text[:5])
                raise OSError(errno.ENOSPC, "No space left on device")

        calls = []

        def fake_open(path, mode="r", *args, **kwargs):
            f = real_open(path, mode, *args, **kwargs)
            if "x" in mode:
                calls.append(path)
                if len(calls) == 2:  # 1件目は書け、2件目で失敗する
                    return BrokenFile(f)
            return f

        with mock.patch("builtins.open", side_effect=fake_open):
            with self.assertRaises(new_round.InputError) as ctx:
                new_round.write_round(self.ws, self.plan(services=("chatgpt",)))
        self.assertIn("1 件", str(ctx.exception))  # それまでに作った件数を知らせる
        self.assertTrue(os.path.isfile(calls[0]))
        self.assertFalse(os.path.exists(calls[1]), "書きかけのファイルを残さない")


class MainTest(WorkspaceCase):
    ARGS = ["--round", "2026-10-01", "--services", "chatgpt,google-ai-mode", "--repeats", "2"]

    def test_creates_files_with_default_workspace(self):
        # 既定の --workspace（ai-search）を、実行したフォルダから見て使う
        proc = helpers.run_script("new_round", self.ARGS, cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.list_answers(),
                         expected_paths("2026-10-01", ["P001", "P002", "P003"], ["chatgpt", "google-ai-mode"], 2))
        self.assertIn("12 件作りました", proc.stderr)
        self.assertIn("3 プロンプト × 2 サービス × 2 回 = 12 件", proc.stderr)
        self.assertIn("normalize_observations.py", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_generated_files_parse(self):
        code, err = self.main_in_process(self.ARGS)
        self.assertEqual(code, 0, err)
        for rel in self.list_answers():
            text = self.read_answer(rel)
            self.assertFalse(text.startswith("﻿"))
            self.assertNotIn("\r", text)
            meta, body, errors = common.parse_front_matter(text)
            self.assertEqual(errors, [], rel)
            parts = rel.split("/")
            self.assertEqual(meta["round"], parts[1])
            self.assertEqual(meta["service"], parts[2])
            pid, repeat = parts[3][:-3].rsplit("-", 1)
            self.assertEqual(meta["prompt_id"], pid)
            self.assertEqual(meta["repeat"], repeat)
            self.assertEqual(meta["prompt"], PROMPT_TEXT[pid])
            self.assertEqual(meta["observed_at"], "2026-10-01")
            self.assertEqual(meta["status"], "")
            self.assertEqual(meta["sources_status"], "")
            self.assertEqual(body, "## 回答\n\n## 出典\n")

    def test_does_not_overwrite(self):
        rel = "answers/2026-10-01/chatgpt/P001-1.md"
        os.makedirs(os.path.dirname(self.answer_path(rel)))
        with open(self.answer_path(rel), "w", encoding="utf-8") as f:
            f.write("貼り付け済みの回答")
        code, err = self.main_in_process(self.ARGS)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read_answer(rel), "貼り付け済みの回答")
        self.assertIn("11 件作りました", err)
        self.assertIn("作らなかったファイル: 1 件", err)
        # 2回目はすべて既にある
        code, err = self.main_in_process(self.ARGS)
        self.assertEqual(code, 0, err)
        self.assertIn("0 件作りました", err)
        self.assertIn("作らなかったファイル: 12 件", err)
        self.assertEqual(self.read_answer(rel), "貼り付け済みの回答")

    def test_prompts_option(self):
        code, err = self.main_in_process(["--round", "2026-10-01", "--services", "claude", "--repeats", "1",
                                          "--prompts", "P002 P004"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.list_answers(), expected_paths("2026-10-01", ["P002", "P004"], ["claude"], 1))
        self.assertIn("P004", err)

    def test_unknown_prompt_id_exit_2(self):
        proc = helpers.run_script("new_round", self.ARGS + ["--prompts", "P001,P999", "--workspace", self.ws],
                                  cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("P999", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))

    def test_missing_prompts_csv_exit_2(self):
        os.remove(os.path.join(self.ws, "prompts.csv"))
        proc = helpers.run_script("new_round", self.ARGS, cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("prompts.csv", proc.stderr)

    def test_invalid_arguments_exit_2(self):
        bad = [
            ["--round", "../x", "--services", "chatgpt"],
            ["--round", "2026-10-01", "--services", "chatgpt,bard"],
            ["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "0"],
            ["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "三"],
            ["--round", "2026-10-01", "--services", "chatgpt", "--login", "はい"],
            ["--services", "chatgpt"],
        ]
        for args in bad:
            proc = helpers.run_script("new_round", args, cwd=self.tmp)
            self.assertEqual(proc.returncode, 2, "{}: {}".format(args, proc.stderr))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))

    def test_cp932_prompts_csv(self):
        # Excel で保存した Shift_JIS（cp932）の prompts.csv も読める
        self.write_prompts(PROMPTS_HEADER + PROMPTS_ROWS, encoding="cp932")
        code, err = self.main_in_process(["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "1"])
        self.assertEqual(code, 0, err)
        meta, _body, _errors = common.parse_front_matter(self.read_answer("answers/2026-10-01/chatgpt/P001-1.md"))
        self.assertEqual(meta["prompt"], PROMPT_TEXT["P001"])

    def read_meta(self, rel):
        meta, _body, errors = common.parse_front_matter(self.read_answer(rel))
        self.assertEqual(errors, [], rel)
        return meta

    def test_condition_options_reach_files(self):
        # コマンドラインの条件が plan_round を通って回答ファイルに届く
        code, err = self.main_in_process([
            "--round", "2026-10-01", "--services", "gemini", "--repeats", "1", "--prompts", "P001",
            "--surface", "app", "--login", "あり（記憶オフ）", "--region", "US", "--language", "en"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.list_answers(), {"answers/2026-10-01/gemini/P001-1.md"})
        meta = self.read_meta("answers/2026-10-01/gemini/P001-1.md")
        self.assertEqual((meta["service"], meta["surface"], meta["login"], meta["region"], meta["language"]),
                         ("gemini", "app", "あり（記憶オフ）", "US", "en"))

    def test_defaults_follow_spec(self):
        # --repeats、--surface、--login、--region、--language を省いたときの値（仕様 7.2 と実装計画の既定値）
        proc = helpers.run_script("new_round", ["--round", "2026-10-01", "--services", "chatgpt"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.list_answers(),
                         expected_paths("2026-10-01", ["P001", "P002", "P003"], ["chatgpt"], SPEC_DEFAULT_REPEATS))
        for rel in self.list_answers():
            meta = self.read_meta(rel)
            for key, value in SPEC_DEFAULTS.items():
                self.assertEqual(meta[key], value, "{} の {}".format(rel, key))
            self.assertEqual(meta["mode"], "", rel)
            self.assertEqual(meta["accuracy"], "未確認", rel)
            self.assertEqual(meta["reviewed_by"], "", rel)

    def test_ids_differing_only_in_case_exit_2(self):
        self.write_prompts(PROMPTS_HEADER
                           + "P001,架空珈琲の豆はどこで買えますか,購入,指名,,,yes,\n"
                           + "p001,サンプル焙煎の豆はどこで買えますか,購入,指名,,,yes,\n")
        proc = helpers.run_script("new_round", ["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "2"],
                                  cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("大文字・小文字", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))

    def test_existing_file_with_other_prompt_id_case_warns(self):
        # 前の実行で P001 を作ったフォルダに、あとから p001 を作ろうとした場合（大文字・小文字を区別しない
        # ファイルシステムでは同じファイルになる）。区別するファイルシステムでも同じ状況を再現するため、
        # p001-1.md の中身を P001 にしておく
        self.write_prompts(PROMPTS_HEADER + "p001,サンプル焙煎の豆はどこで買えますか,購入,指名,,,yes,\n")
        rel = "answers/2026-10-01/chatgpt/p001-1.md"
        os.makedirs(os.path.dirname(self.answer_path(rel)))
        with open(self.answer_path(rel), "w", encoding="utf-8") as f:
            f.write(new_round.build_answer({"round": "2026-10-01", "prompt_id": "P001", "service": "chatgpt",
                                            "repeat": "1"}))
        code, err = self.main_in_process(["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "1"])
        self.assertEqual(code, 0, err)
        self.assertIn("作らなかったファイル: 1 件", err)
        self.assertIn("p001-1.md", err)
        self.assertIn("prompt_id=P001", err)
        self.assertIn("大文字・小文字", err)

    def test_existing_files_with_other_conditions_warn(self):
        base = ["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "2", "--prompts", "P001"]
        code, err = self.main_in_process(base)
        self.assertEqual(code, 0, err)
        # 同じ条件でもう一度実行しても、条件の違いの警告は出ない
        code, err = self.main_in_process(base)
        self.assertEqual(code, 0, err)
        self.assertIn("作らなかったファイル: 2 件", err)
        self.assertNotIn("違います", err)
        # 条件を変えて同じラウンドで実行すると、既存のファイルの条件と違うことを知らせる
        code, err = self.main_in_process(base + ["--surface", "app", "--login", "あり"])
        self.assertEqual(code, 0, err)
        self.assertIn("0 件作りました", err)
        self.assertIn("answers/2026-10-01/chatgpt/P001-1.md", err)
        self.assertIn("surface=web", err)
        self.assertIn("app", err)
        self.assertIn("login=なし", err)
        self.assertIn("別のラウンド名", err)
        # 既存のファイルはそのまま
        meta = self.read_meta("answers/2026-10-01/chatgpt/P001-1.md")
        self.assertEqual((meta["surface"], meta["login"]), ("web", "なし"))

    def test_existing_directory_in_place_of_file_warns(self):
        os.makedirs(self.answer_path("answers/2026-10-01/chatgpt/P001-1.md"))
        code, err = self.main_in_process(["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "1",
                                          "--prompts", "P001,P002"])
        self.assertEqual(code, 0, err)
        self.assertIn("1 件作りました", err)
        self.assertIn("P001-1.md", err)
        self.assertIn("読めません", err)

    def test_workspace_errors_exit_2_without_traceback(self):
        # answers/<round>/<service> が普通のファイル
        blocker = self.answer_path("answers/2026-10-01/google-ai-mode")
        os.makedirs(os.path.dirname(blocker))
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("")
        proc = helpers.run_script("new_round", self.ARGS, cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("google-ai-mode", proc.stderr)
        self.assertEqual(self.list_answers(), {"answers/2026-10-01/google-ai-mode"})

    def test_too_long_round_exit_2(self):
        proc = helpers.run_script("new_round", ["--round", "R" * 300, "--services", "chatgpt"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("--round", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))

    def test_nul_in_prompts_csv_exit_2(self):
        # Python 3.9 の csv は NUL で csv.Error を出し、3.13 は通す。どちらの版でも入力エラーにする
        with open(os.path.join(self.ws, "prompts.csv"), "wb") as f:
            f.write((PROMPTS_HEADER + "P001,架空珈琲の\x00豆,購入,指名,,,yes,\n").encode("utf-8"))
        proc = helpers.run_script("new_round", ["--round", "2026-10-01", "--services", "chatgpt"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("prompts.csv", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))

    def test_observed_at_guidance_mentions_date(self):
        # 1ラウンドを複数の日に分けるので、時刻だけでなく日付も直すよう案内する
        guidance = "別の日に尋ねたら日付も直す"
        proc = helpers.run_script("new_round", self.ARGS, cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(guidance, proc.stderr)
        self.assertNotIn("observed_at に時刻", proc.stderr)
        proc = helpers.run_script("new_round", ["--help"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(guidance, proc.stdout)
        self.assertNotIn("observed_at に時刻", proc.stdout)

    def test_mode_option_reaches_files(self):
        code, err = self.main_in_process(self.ARGS + ["--mode", "検索あり"])
        self.assertEqual(code, 0, err)
        for rel in self.list_answers():
            self.assertEqual(self.read_meta(rel)["mode"], "検索あり", rel)
        proc = helpers.run_script("new_round", ["--help"], cwd=self.tmp)
        self.assertIn("--mode", proc.stdout)

    def test_bad_mode_exit_2_without_files(self):
        proc = helpers.run_script("new_round", self.ARGS + ["--mode", "GPT-5 Thinking/検索あり"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("--mode", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))

    def test_existing_files_with_other_mode_warn(self):
        base = ["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "1", "--prompts", "P001"]
        code, err = self.main_in_process(base)
        self.assertEqual(code, 0, err)
        # --mode を付け忘れて作ったあとで、--mode を付けて作り直そうとした（既存のファイルは上書きしない）
        code, err = self.main_in_process(base + ["--mode", "検索あり"])
        self.assertEqual(code, 0, err)
        self.assertIn("作らなかったファイル: 1 件", err)
        self.assertIn("mode=空（今回の指定は 検索あり）", err)
        # --mode を付けなければ、mode の違いは知らせない（記入済みの mode と比べない）
        code, err = self.main_in_process(base)
        self.assertEqual(code, 0, err)
        self.assertNotIn("mode=", err)

    def test_running_inside_the_workspace_hints_workspace_dot(self):
        proc = helpers.run_script("new_round", self.ARGS, cwd=self.ws)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("--workspace .", proc.stderr)
        self.assertNotIn("先に prompts.csv を作ってください", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))

    def test_missing_prompts_csv_without_hint(self):
        os.remove(os.path.join(self.ws, "prompts.csv"))
        proc = helpers.run_script("new_round", self.ARGS, cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertNotIn("--workspace .", proc.stderr)

    def test_argument_errors_in_japanese(self):
        cases = [
            (["--round", "2026-10-01"], "--services"),
            (["--round", "2026-10-01", "--services", "chatgpt", "--repeats", "三"], "--repeats"),
            (["--round", "2026-10-01", "--services", "chatgpt", "--no-such-option"], "--no-such-option"),
            (["--round", "2026-10-01", "--services"], "--services"),
        ]
        for args, option in cases:
            proc = helpers.run_script("new_round", args, cwd=self.tmp)
            self.assertEqual(proc.returncode, 2, "{}: {}".format(args, proc.stderr))
            self.assertIn("エラー", proc.stderr, args)
            self.assertIn(option, proc.stderr, args)
            self.assertIn("--help", proc.stderr, args)
            for english in ("error:", "required", "invalid", "unrecognized", "expected"):
                self.assertNotIn(english, proc.stderr, args)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "answers")))


if __name__ == "__main__":
    unittest.main()
