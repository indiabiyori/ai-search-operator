# -*- coding: utf-8 -*-
"""compare_runs.py のテスト。データはすべて架空のもの（架空珈琲、サンプル焙煎など）。"""
import codecs
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from unittest import mock

# python3 -m unittest tests.test_compare の形（リポジトリのルートから）でも helpers を読めるようにする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

common = helpers.load_script("ai_search_common")
compare = helpers.load_script("compare_runs")

# 仕様 6.4 の observations.csv の列（normalize_observations.py が出す形）
OBS_FIELDS = [
    "round", "answer_file", "answer_sha256", "prompt_id", "stage", "branded", "intent_group", "observed_at",
    "service", "surface", "mode", "login", "region", "language", "repeat", "status", "sources_status",
    "valid_mention", "valid_citation", "exclusion_reason", "own_mentioned", "own_entities_mentioned",
    "own_mention_snippet", "own_cited", "own_first_source_order", "own_cited_urls", "source_count",
    "unresolved_sources", "competitors_mentioned", "competitors_cited", "accuracy", "reviewed_by", "warnings",
]
CIT_FIELDS = ["round", "answer_file", "prompt_id", "service", "surface", "login", "mode", "location",
              "source_order", "url", "host", "entity_id", "entity_kind"]

CHATGPT = {"service": "chatgpt", "surface": "web", "login": "なし", "mode": "検索あり", "region": "JP",
           "language": "ja"}
GEMINI = {"service": "gemini", "surface": "web", "login": "なし", "mode": "", "region": "JP", "language": "ja"}

ENTITIES_SHA = "1a2b3c4d5e6f" + "0" * 52
TARGETS = ["P001", "P002", "P003", "P004", "P005", "P006", "P007", "P008"]
CONTROLS = ["P101", "P102", "P103"]

EXPERIMENT_EXAMPLE = """---
id: E001
status: 計画中          # 計画中 / 実施中 / 判定済み
hypothesis: 料金ページに税込の料金表を載せると、料金を尋ねるプロンプトで自社の引用が増える
change_category: コンテンツ   # コンテンツ / エンティティ / クローラー / 外部の言及 / 技術
change_summary: /pricing/ に税込の料金表と改定日を追加
changed_on: 2026-10-15   # 本番に反映した日
primary_metric: citation # mention / citation
primary_group: chatgpt/web/なし/検索あり/JP/ja   # 確認的に判定する1組（service/surface/login/mode/region/language）
alpha: 0.05
min_effect: 0.10         # 実務上の最小効果（プロンプトごとの率の差の平均）。空なら使わない
entities_sha256:         # 変更前のラウンドを記録した時点の entities.csv の SHA-256（observations.run.json から写す）
target_prompts: P003, P004, P007, P011, P012, P015, P018, P021, P022, P024
control_prompts: P001, P002, P005, P009, P010, P013
baseline_rounds: 2026-10-01, 2026-10-08
after_rounds: 2026-10-29, 2026-11-12
verdict:
---
## 仮説と変更の中身

架空珈琲の料金ページを直す。
"""


def section(text, heading):
    """Markdown の見出し heading の節（次の「## 」の見出しの前まで）を返す。"""
    parts = text.split(heading + "\n", 1)
    if len(parts) < 2:
        return ""
    return re.split(r"\n## ", parts[1], maxsplit=1)[0]


def obs_row(**kw):
    """observations.csv の1行（既定は有効な回答、言及・引用なし）。"""
    row = {name: "" for name in OBS_FIELDS}
    row.update({
        "stage": "認知", "branded": "非指名", "status": "記録済み", "sources_status": "記録済み",
        "valid_mention": "1", "valid_citation": "1", "own_mentioned": "0", "own_cited": "0",
        "accuracy": "未確認", "language": "ja",
    })
    row.update(kw)
    if not row["answer_file"]:
        row["answer_file"] = "answers/{}/{}/{}-{}.md".format(
            row["round"], row["service"], row["prompt_id"], row["repeat"])
    return row


def make_rows(round_name, dates, pid, cited, mentioned, group=None, repeats=3, **extra):
    """1プロンプト分の回答（repeats 件）。先頭の cited 件を引用あり、mentioned 件を言及ありにする。"""
    rows = []
    for i in range(repeats):
        values = dict(group or CHATGPT)
        values.update({
            "round": round_name, "prompt_id": pid, "repeat": str(i + 1),
            "observed_at": dates[i % len(dates)] + " 10:00",
            "own_cited": "1" if i < cited else "0",
            "own_first_source_order": "1" if i < cited else "",
            "own_mentioned": "1" if i < mentioned else "0",
        })
        values.update(extra)
        rows.append(obs_row(**values))
    return rows


def standard_rows(after_dates=("2026-10-29", "2026-10-30"), after_mode="検索あり"):
    """
    架空の観測データ。
    - chatgpt の組: 対象 P001〜P006 は引用が 0/3 → 2/3（上がる）、P007・P008 は 1/3 のまま。
      対照 P101〜P103 は 1/3 のまま。P009 は 3/3 → 0/3（下がる）。言及はすべて 1/3 のまま。
    - gemini の組: P001 だけ（0/3 → 3/3）。観測はどちらの期間も1日だけ。
    - 変更前のラウンドには、未記入・AI の回答なし・出典が不明の回答を1件ずつ混ぜる。
    """
    before_dates = ("2026-10-01", "2026-10-02")
    after_group = dict(CHATGPT, mode=after_mode)
    rows = []
    for pid in TARGETS[:6]:
        rows += make_rows("2026-10-01", before_dates, pid, cited=0, mentioned=1)
        rows += make_rows("2026-10-29", after_dates, pid, cited=2, mentioned=1, group=after_group)
    for pid in TARGETS[6:] + CONTROLS:
        rows += make_rows("2026-10-01", before_dates, pid, cited=1, mentioned=1)
        rows += make_rows("2026-10-29", after_dates, pid, cited=1, mentioned=1, group=after_group)
    rows += make_rows("2026-10-01", before_dates, "P009", cited=3, mentioned=1,
                      competitors_mentioned="comp-a", competitors_cited="comp-a")
    rows += make_rows("2026-10-29", after_dates, "P009", cited=0, mentioned=1, group=after_group)
    # 誤った説明の判定: 人が確認した 誤りあり・誤りなし と、Claude の下書きだけのもの
    for row in rows:
        if row["round"] == "2026-10-01" and row["service"] == "chatgpt":
            if row["prompt_id"] == "P007" and row["repeat"] == "1":
                row.update(accuracy="誤りあり", reviewed_by="human")
            elif row["prompt_id"] == "P007" and row["repeat"] == "2":
                row.update(accuracy="誤りなし", reviewed_by="human")
            elif row["prompt_id"] == "P008" and row["repeat"] == "1":
                row.update(accuracy="誤りあり", reviewed_by="claude-draft")
    # 分母に入れない回答
    rows.append(obs_row(round="2026-10-01", prompt_id="P001", repeat="4", observed_at="2026-10-02 ",
                        status="未記入", sources_status="不明", valid_mention="0", valid_citation="0",
                        exclusion_reason="status が 未記入", **CHATGPT))
    rows.append(obs_row(round="2026-10-01", prompt_id="P202", repeat="1", observed_at="2026-10-01 11:00",
                        status="AI の回答なし", valid_mention="0", valid_citation="0",
                        exclusion_reason="status が AI の回答なし", **CHATGPT))
    rows.append(obs_row(round="2026-10-01", prompt_id="P201", repeat="1", observed_at="2026-10-01 12:00",
                        sources_status="不明", valid_citation="0", exclusion_reason="出典が不明", **CHATGPT))
    # 別の組（gemini）
    rows += make_rows("2026-10-01", ("2026-10-01",), "P001", cited=0, mentioned=0, group=GEMINI)
    rows += make_rows("2026-10-29", ("2026-10-29",), "P001", cited=3, mentioned=3, group=GEMINI)
    return rows


class SignTestTest(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(compare.sign_test_p(6, 0), 0.03125)
        self.assertAlmostEqual(compare.sign_test_p(0, 6), 0.03125)
        self.assertAlmostEqual(compare.sign_test_p(5, 0), 0.0625)
        self.assertEqual(compare.sign_test_p(0, 0), 1.0)
        self.assertEqual(compare.sign_test_p(3, 3), 1.0)
        self.assertAlmostEqual(compare.sign_test_p(8, 1), 0.0390625)
        expected = 2 * sum(math.comb(12, i) for i in range(3)) / 4096.0
        self.assertAlmostEqual(compare.sign_test_p(10, 2), expected)

    def test_large_m_does_not_overflow(self):
        # m が 1024 以上でも float への変換で落ちない
        p = compare.sign_test_p(600, 500)
        self.assertTrue(0.0 < p < 1.0)
        self.assertGreaterEqual(compare.sign_test_p(1100, 0), 0.0)
        self.assertEqual(compare.sign_test_p(550, 550), 1.0)


def up(n, start=1):
    """n 件のプロンプトが 0/3 → 1/3 に上がる (before, after)。"""
    before = {"P{:03d}".format(i): (0, 3) for i in range(start, start + n)}
    after = {"P{:03d}".format(i): (1, 3) for i in range(start, start + n)}
    return before, after


class JudgeTest(unittest.TestCase):
    def test_m5_all_up_is_undecidable(self):
        before, after = up(5)
        result = compare.judge(before, after)
        self.assertEqual(result["verdict"], "判定不能")
        self.assertEqual(result["m"], 5)
        self.assertIn("6 件以上", result["reason"])

    def test_m6_all_up_is_improvement(self):
        before, after = up(6)
        result = compare.judge(before, after)
        self.assertEqual(result["verdict"], "改善シグナル")
        self.assertAlmostEqual(result["p"], 0.03125)
        self.assertEqual((result["improved"], result["worsened"], result["tied"]), (6, 0, 0))

    def test_m6_all_down_is_worsening(self):
        after, before = up(6)
        result = compare.judge(before, after)
        self.assertEqual(result["verdict"], "悪化シグナル")
        self.assertEqual(result["worsened"], 6)

    def test_mixed_directions(self):
        before, after = up(4)
        before.update({"P101": (1, 3), "P102": (2, 3)})
        after.update({"P101": (0, 3), "P102": (1, 3)})
        result = compare.judge(before, after)
        self.assertEqual(result["verdict"], "明確な変化を検出せず")
        self.assertEqual((result["improved"], result["worsened"]), (4, 2))
        self.assertIn("変化がないという意味ではない", result["reason"])

    def test_ties_are_not_counted_in_m(self):
        before, after = up(6)
        for pid in ("P101", "P102", "P103"):
            before[pid] = (1, 3)
            after[pid] = (1, 3)
        result = compare.judge(before, after)
        self.assertEqual(result["m"], 6)
        self.assertEqual(result["tied"], 3)
        self.assertEqual(len(result["eligible"]), 9)

    def test_different_n_is_excluded(self):
        before, after = up(6)
        before["P101"] = (1, 3)
        after["P101"] = (1, 2)
        result = compare.judge(before, after)
        self.assertNotIn("P101", result["eligible"])
        reasons = dict(result["excluded"])
        self.assertIn("前後で有効な回答の数が違う", reasons["P101"])
        self.assertIn("前 3 件、後 2 件", reasons["P101"])

    def test_below_min_repeats_is_excluded(self):
        before, after = up(6)
        before["P101"] = (0, 2)
        after["P101"] = (1, 2)
        result = compare.judge(before, after, min_repeats=3)
        self.assertIn("件未満", dict(result["excluded"])["P101"])
        self.assertEqual(result["m"], 6)

    def test_one_side_only_is_excluded(self):
        before, after = up(6)
        before["P101"] = (0, 3)
        after["P102"] = (1, 3)
        reasons = dict(compare.judge(before, after)["excluded"])
        self.assertEqual(reasons["P101"], "片方の期間にしかない")
        self.assertEqual(reasons["P102"], "片方の期間にしかない")

    def test_zero_valid_answers_are_excluded(self):
        before, after = up(6)
        before["P101"] = (0, 0)
        after["P101"] = (0, 0)
        result = compare.judge(before, after, min_repeats=3)
        self.assertIn("P101", dict(result["excluded"]))

    def test_min_effect_not_reached(self):
        before, after = up(6)  # 差はどれも 1/3
        result = compare.judge(before, after, min_effect=0.5)
        self.assertEqual(result["verdict"], "明確な変化を検出せず")
        self.assertIn("最小効果", result["reason"])

    def test_mean_and_median(self):
        before, after = up(6)
        after["P003"] = (2, 3)
        after["P004"] = (3, 3)
        before["P101"] = (1, 3)
        after["P101"] = (1, 3)
        result = compare.judge(before, after)
        # 差: 1/3 ×4、2/3、1、0
        self.assertAlmostEqual(result["mean_diff"], 3.0 / 7)
        self.assertAlmostEqual(result["median_diff"], 1.0 / 3)
        self.assertAlmostEqual(result["diffs"]["P004"], 1.0)

    def test_median_of_even_count(self):
        before = {"P1": (0, 3), "P2": (0, 3), "P3": (0, 3), "P4": (0, 3)}
        after = {"P1": (0, 3), "P2": (1, 3), "P3": (2, 3), "P4": (3, 3)}
        self.assertAlmostEqual(compare.judge(before, after)["median_diff"], 0.5)

    def test_no_eligible_prompts(self):
        result = compare.judge({}, {})
        self.assertEqual(result["verdict"], "判定不能")
        self.assertIsNone(result["mean_diff"])
        self.assertIsNone(result["median_diff"])


class ApplyControlTest(unittest.TestCase):
    def signal(self):
        before, after = up(6)
        for pid in before:
            after[pid] = (2, 3)
        return compare.judge(before, after)  # 差の平均 2/3

    def test_control_moved_the_same(self):
        before, after = up(3, start=101)
        for pid in before:
            after[pid] = (2, 3)
        control = compare.judge(before, after)
        out = compare.apply_control(self.signal(), control)
        self.assertEqual(out["verdict"], "判定不能")
        self.assertAlmostEqual(out["adjusted_diff"], 0.0)
        self.assertIn("対照も同じ程度に動いた", out["reason"])

    def test_control_flat_keeps_signal(self):
        control = compare.judge({"P101": (1, 3), "P102": (1, 3)}, {"P101": (1, 3), "P102": (1, 3)})
        out = compare.apply_control(self.signal(), control)
        self.assertEqual(out["verdict"], "改善シグナル")
        self.assertIn("調整しても同じ向き", out["reason"])
        self.assertAlmostEqual(out["control_mean_diff"], 0.0)
        self.assertAlmostEqual(out["adjusted_diff"], 2.0 / 3)

    def test_no_control_keeps_signal_with_note(self):
        out = compare.apply_control(self.signal(), None)
        self.assertEqual(out["verdict"], "改善シグナル")
        self.assertIn("対照がない", out["reason"])
        self.assertIsNone(out["adjusted_diff"])

    def test_control_without_eligible_prompts(self):
        control = compare.judge({"P101": (1, 3)}, {})
        out = compare.apply_control(self.signal(), control)
        self.assertEqual(out["verdict"], "改善シグナル")
        self.assertIn("対照がない", out["reason"])

    def test_adjusted_below_min_effect(self):
        control = compare.judge({"P101": (0, 6), "P102": (0, 6)}, {"P101": (3, 6), "P102": (3, 6)})
        out = compare.apply_control(self.signal(), control, min_effect=0.3)
        self.assertEqual(out["verdict"], "判定不能")

    def test_no_signal_is_unchanged(self):
        target = compare.judge(*up(4))
        control = compare.judge({"P101": (1, 3)}, {"P101": (2, 3)})
        out = compare.apply_control(target, control)
        self.assertEqual(out["verdict"], target["verdict"])
        self.assertEqual(out["reason"], target["reason"])
        self.assertAlmostEqual(out["control_mean_diff"], 1.0 / 3)


def boundary_target_and_control():
    """
    対象と対照がちょうど同じだけ動く例（レビューの再現手順）。
    対象: P001〜P004 が 0/3 → 1/3、P005・P006 が 1/3 → 3/3（差の平均 4/9）。
    対照: P101・P102 が 0/3 → 1/3、P103 が 0/3 → 2/3（差の平均 4/9）。
    """
    before = {"P001": (0, 3), "P002": (0, 3), "P003": (0, 3), "P004": (0, 3), "P005": (1, 3), "P006": (1, 3)}
    after = {"P001": (1, 3), "P002": (1, 3), "P003": (1, 3), "P004": (1, 3), "P005": (3, 3), "P006": (3, 3)}
    c_before = {"P101": (0, 3), "P102": (0, 3), "P103": (0, 3)}
    c_after = {"P101": (1, 3), "P102": (1, 3), "P103": (2, 3)}
    return compare.judge(before, after), compare.judge(c_before, c_after)


class ExactBoundaryTest(unittest.TestCase):
    """率の差を厳密に計算し、判定の境界で浮動小数点の誤差に左右されないこと。"""

    def test_adjusted_diff_exactly_zero_is_undecidable(self):
        target, control = boundary_target_and_control()
        self.assertEqual(target["verdict"], "改善シグナル")
        self.assertEqual(target["mean_diff"], control["mean_diff"])
        out = compare.apply_control(target, control)
        self.assertEqual(out["adjusted_diff"], 0)
        self.assertEqual(out["verdict"], "判定不能")
        self.assertIn("+0.000", out["reason"])

    def test_mean_diff_exactly_min_effect_is_signal(self):
        before = {"P{:03d}".format(i): (2, 10) for i in range(1, 7)}
        after = {"P{:03d}".format(i): (3, 10) for i in range(1, 7)}
        result = compare.judge(before, after, min_effect=0.10)
        self.assertEqual(result["mean_diff"], Fraction(1, 10))
        self.assertEqual(result["verdict"], "改善シグナル")
        before = {"P{:03d}".format(i): (2, 5) for i in range(1, 7)}
        after = {"P{:03d}".format(i): (3, 5) for i in range(1, 7)}
        self.assertEqual(compare.judge(before, after, min_effect=0.2)["verdict"], "改善シグナル")

    def test_mean_diff_below_min_effect_reason(self):
        before = {"P{:03d}".format(i): (2, 10) for i in range(1, 8)}
        after = {"P{:03d}".format(i): (3, 10) for i in range(1, 7)}
        after["P007"] = (2, 10)  # 同じ率のプロンプトが1件あり、差の平均は 6/70
        result = compare.judge(before, after, min_effect=0.10)
        self.assertEqual(result["verdict"], "明確な変化を検出せず")
        self.assertIn("+0.086", result["reason"])
        self.assertIn("0.100", result["reason"])

    def test_close_values_are_shown_with_more_digits(self):
        # 差の平均 0.09995 は小数第3位では 0.100 と同じに見えるので、桁を増やして示す
        before = {"P{:03d}".format(i): (0, 2000) for i in range(1, 7)}
        after = {"P001": (200, 2000), "P002": (200, 2000), "P003": (200, 2000),
                 "P004": (199, 2000), "P005": (199, 2000), "P006": (199, 2000)}
        result = compare.judge(before, after, min_effect=0.10)
        self.assertEqual(result["mean_diff"], Fraction(399, 4000))  # 0.09975
        self.assertEqual(result["verdict"], "明確な変化を検出せず")
        self.assertNotIn("+0.100 が最小効果 0.100", result["reason"])
        self.assertIn("+0.0998 が最小効果 0.1000 に届かない", result["reason"])

    def test_adjusted_exactly_min_effect_keeps_signal(self):
        before, after = up(6)
        for pid in before:
            after[pid] = (2, 3)
        target = compare.judge(before, after)  # 差の平均 2/3
        control = compare.judge({"P101": (0, 6)}, {"P101": (1, 6)})  # 差の平均 1/6
        out = compare.apply_control(target, control, min_effect=0.5)
        self.assertEqual(out["adjusted_diff"], Fraction(1, 2))
        self.assertEqual(out["verdict"], "改善シグナル")

    def test_adjusted_below_min_effect_reason(self):
        before, after = up(6)
        for pid in before:
            after[pid] = (2, 3)
        target = compare.judge(before, after)  # 差の平均 2/3
        control = compare.judge({"P101": (0, 3)}, {"P101": (1, 3)})  # 差の平均 1/3
        out = compare.apply_control(target, control, min_effect=0.5)
        self.assertEqual(out["verdict"], "判定不能")
        self.assertIn("最小効果", out["reason"])
        self.assertIn("+0.333", out["reason"])

    def test_formatting_of_exact_values(self):
        self.assertEqual(compare._fmt_diff(Fraction(2, 3)), "+0.667")
        self.assertEqual(compare._fmt_diff(Fraction(-1, 1)), "-1.000")
        self.assertEqual(compare._fmt_diff(Fraction(0)), "+0.000")
        # 0 でない値が小数第3位で 0 に丸まるときは、桁を増やして 0 と区別する
        self.assertEqual(compare._fmt_diff(Fraction(-1, 3000)), "-0.0003")
        self.assertEqual(compare._fmt_plain(Fraction(-2, 3)), "-0.667")
        self.assertEqual(compare._fmt_diff(0.0005), "+0.001")  # 四捨五入（銀行丸めではない）


class PValueFormatTest(unittest.TestCase):
    """
    p を α と並べて読めるように示す。小数第3位に丸めると α と同じに見えるのに厳密には違う p は、違いが見える
    まで桁を増やす（_fmt_against と同じ考え方）。p < α でシグナルになった行に「p 0.050」と出さない。
    """

    def test_p_close_to_alpha_gets_more_digits(self):
        self.assertEqual(compare._fmt_p(compare._sign_test_exact(42, 25), 0.05), "0.0498")  # 0.049800…
        self.assertEqual(compare._fmt_p(compare._sign_test_exact(22, 10), 0.05), "0.0501")  # 0.050102…
        self.assertEqual(compare._fmt_p(compare._sign_test_exact(31, 13), 0.01), "0.0096")  # 0.009560…
        # 0.04996 は小数第4位でも 0.0500 に見えるので、第5位まで出す
        self.assertEqual(compare._fmt_p(Fraction(4996, 100000), 0.05), "0.04996")

    def test_p_far_from_alpha_keeps_three_places(self):
        self.assertEqual(compare._fmt_p(Fraction(1, 32), 0.05), "0.031")
        self.assertEqual(compare._fmt_p(Fraction(1), 0.05), "1.000")
        self.assertEqual(compare._fmt_p(Fraction(1, 32)), "0.031")  # α を渡さなければ小数第3位
        self.assertEqual(compare._fmt_p(1.0), "1.000")

    def test_p_equal_to_alpha_is_shown_exactly(self):
        # α が 1/32 のとき、p = 1/32 は α 未満ではないのでシグナルにならない。「0.031」と出すと α 0.03125 より
        # 小さく見えるので、α と同じ値に見える桁まで出す
        self.assertEqual(compare._fmt_p(Fraction(1, 32), 0.03125), "0.03125")
        before, after = up(6)
        result = compare.judge(before, after, alpha=0.03125)
        self.assertEqual(result["verdict"], "明確な変化を検出せず")
        self.assertIn("（p=0.03125）", result["reason"])

    def test_reason_uses_more_digits(self):
        # 22 件が上がり 10 件が下がる: p = 0.050102… は α 0.05 未満ではない
        pids = ["P{:03d}".format(i) for i in range(1, 33)]
        before = dict((pid, (1, 3)) for pid in pids)
        after = dict((pid, (2, 3) if i < 22 else (0, 3)) for i, pid in enumerate(pids))
        result = compare.judge(before, after)
        self.assertEqual((result["improved"], result["worsened"]), (22, 10))
        self.assertEqual(result["verdict"], "明確な変化を検出せず")
        self.assertIn("（p=0.0501）", result["reason"])
        self.assertNotIn("p=0.050）", result["reason"])


class SourceOrderTest(unittest.TestCase):
    """
    own_first_source_order は ASCII の数字だけを読む。str.isdigit は ① や ² も数字とみなすが int() は読めない
    （ValueError で終了コード 1 になっていた）。7 桁以上は読まない（3.11 以降の int() は 4300 桁を超えると読まない）。
    """

    def test_values(self):
        cases = (
            ("", 0), ("1", 1), (" 3 ", 3), ("12", 12), ("999999", 999999),
            ("①", None), ("²", None), ("１", None), ("٣", None), ("0", None), ("-1", None), ("1.0", None),
            ("+1", None), ("一", None), ("9" * 7, None), ("9" * 5000, None),
        )
        for value, expected in cases:
            with self.subTest(value=value[:10]):
                self.assertEqual(compare._source_order(value), expected)

    def test_distribution_skips_unreadable_values(self):
        rows = [obs_row(own_cited="1", own_first_source_order=value)
                for value in ("1", "2", "3", "4", "", "①", "１")]
        self.assertEqual(compare._source_order_text(rows),
                         "1番目 1 / 2〜3番目 2 / 4番目以降 1 / 本文のリンクだけ 1 / 読めない値 2")
        # 読めない値がなければ、その項目は出さない
        self.assertEqual(compare._source_order_text(rows[:5]),
                         "1番目 1 / 2〜3番目 2 / 4番目以降 1 / 本文のリンクだけ 1")


class MetricValueTest(unittest.TestCase):
    def test_mention(self):
        self.assertEqual(compare.metric_value(obs_row(own_mentioned="1"), "mention"), 1)
        self.assertEqual(compare.metric_value(obs_row(own_mentioned="0"), "mention"), 0)
        self.assertIsNone(compare.metric_value(obs_row(valid_mention="0", own_mentioned="1"), "mention"))

    def test_citation_uses_valid_citation_only(self):
        row = obs_row(valid_citation="0", own_cited="1", own_mentioned="1")
        self.assertIsNone(compare.metric_value(row, "citation"))
        self.assertEqual(compare.metric_value(row, "mention"), 1)
        self.assertEqual(compare.metric_value(obs_row(own_cited="1"), "citation"), 1)

    def test_error_needs_human_review(self):
        self.assertEqual(compare.metric_value(obs_row(accuracy="誤りあり", reviewed_by="human"), "error"), 1)
        self.assertEqual(compare.metric_value(obs_row(accuracy="誤りなし", reviewed_by="human"), "error"), 0)
        self.assertIsNone(compare.metric_value(obs_row(accuracy="誤りあり", reviewed_by="claude-draft"), "error"))
        self.assertIsNone(compare.metric_value(obs_row(accuracy="誤りあり", reviewed_by=""), "error"))
        self.assertIsNone(compare.metric_value(obs_row(accuracy="未確認", reviewed_by="human"), "error"))
        self.assertIsNone(compare.metric_value(
            obs_row(accuracy="誤りあり", reviewed_by="human", valid_mention="0"), "error"))

    def test_display(self):
        self.assertEqual(compare.metric_value(obs_row(status="記録済み"), "display"), 1)
        self.assertEqual(compare.metric_value(obs_row(status="AI の回答なし", valid_mention="0"), "display"), 0)
        self.assertIsNone(compare.metric_value(obs_row(status="未記入", valid_mention="0"), "display"))
        self.assertIsNone(compare.metric_value(obs_row(status="エラー", valid_mention="0"), "display"))


class PerPromptTest(unittest.TestCase):
    def test_counts_valid_rows_only(self):
        rows = [
            obs_row(prompt_id="P001", own_cited="1"),
            obs_row(prompt_id="P001", own_cited="0"),
            obs_row(prompt_id="P001", own_cited="1", valid_citation="0"),
            obs_row(prompt_id="P002", own_cited="0", valid_citation="0"),
        ]
        result = compare.per_prompt(rows, "citation")
        self.assertEqual(result["P001"], (1, 2))
        # 有効な回答がないプロンプトは (0, 0)。外した理由を「件数が違う」「件数不足」で示せるように残す
        self.assertEqual(result["P002"], (0, 0))


class FormatTest(unittest.TestCase):
    def test_rate_rounds_half_up(self):
        self.assertEqual(compare.format_rate(5, 80), "5/80（6.3%）")
        self.assertEqual(compare.format_rate(12, 88), "12/88（13.6%）")

    def test_rate_without_denominator(self):
        self.assertEqual(compare.format_rate(0, 0), "0/0（分母なし）")


class ParseExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, name="E001.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_spec_example(self):
        exp = compare.parse_experiment(self.write(EXPERIMENT_EXAMPLE))
        self.assertEqual(exp["id"], "E001")
        self.assertEqual(exp["primary_metric"], "citation")
        self.assertEqual(exp["primary_group"], ("chatgpt", "web", "なし", "検索あり", "JP", "ja"))
        self.assertIsInstance(exp["alpha"], float)
        self.assertAlmostEqual(exp["alpha"], 0.05)
        self.assertIsInstance(exp["min_effect"], float)
        self.assertAlmostEqual(exp["min_effect"], 0.10)
        self.assertEqual(exp["targets"][:3], ["P003", "P004", "P007"])
        self.assertEqual(len(exp["targets"]), 10)
        self.assertEqual(len(exp["controls"]), 6)
        self.assertEqual(exp["baseline_rounds"], ["2026-10-01", "2026-10-08"])
        self.assertEqual(exp["after_rounds"], ["2026-10-29", "2026-11-12"])
        self.assertEqual(exp["entities_sha256"], "")
        self.assertEqual(exp["changed_on"], "2026-10-15")

    def test_empty_min_effect_is_none(self):
        text = EXPERIMENT_EXAMPLE.replace("min_effect: 0.10 ", "min_effect: ")
        self.assertIsNone(compare.parse_experiment(self.write(text))["min_effect"])

    def test_bad_primary_group(self):
        text = EXPERIMENT_EXAMPLE.replace("chatgpt/web/なし/検索あり/JP/ja", "chatgpt/web/なし/JP/ja")
        with self.assertRaises(compare.InputError):
            compare.parse_experiment(self.write(text))

    def test_bad_primary_metric(self):
        text = EXPERIMENT_EXAMPLE.replace("primary_metric: citation", "primary_metric: error")
        with self.assertRaises(compare.InputError):
            compare.parse_experiment(self.write(text))

    def test_bad_alpha(self):
        text = EXPERIMENT_EXAMPLE.replace("alpha: 0.05", "alpha: 五分")
        with self.assertRaises(compare.InputError):
            compare.parse_experiment(self.write(text))

    def test_missing_file_and_front_matter(self):
        with self.assertRaises(compare.InputError):
            compare.parse_experiment(os.path.join(self.tmp, "none.md"))
        with self.assertRaises(compare.InputError):
            compare.parse_experiment(self.write("# 実験\n", "E002.md"))

    def write_bytes(self, data, name="E001.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_notepad_bom_and_crlf(self):
        # Windows のメモ帳で保存した実験の記録（BOM 付き UTF-8、改行は CRLF）
        data = codecs.BOM_UTF8 + EXPERIMENT_EXAMPLE.replace("\n", "\r\n").encode("utf-8")
        exp = compare.parse_experiment(self.write_bytes(data))
        self.assertEqual(exp["id"], "E001")
        self.assertEqual(exp["primary_group"], ("chatgpt", "web", "なし", "検索あり", "JP", "ja"))
        self.assertEqual(exp["after_rounds"], ["2026-10-29", "2026-11-12"])

    def test_cp932_record(self):
        exp = compare.parse_experiment(self.write_bytes(EXPERIMENT_EXAMPLE.encode("cp932")))
        self.assertEqual(exp["primary_group"], ("chatgpt", "web", "なし", "検索あり", "JP", "ja"))
        self.assertIn("税込の料金表", exp["hypothesis"])

    def test_ids_separated_by_japanese_comma(self):
        text = EXPERIMENT_EXAMPLE.replace("P003, P004, P007", "P003、P004、P007")
        with self.assertRaises(compare.InputError) as ctx:
            compare.parse_experiment(self.write(text))
        self.assertIn("、", str(ctx.exception))
        text = EXPERIMENT_EXAMPLE.replace("P001, P002, P005", "P001，P002，P005")
        with self.assertRaises(compare.InputError):
            compare.parse_experiment(self.write(text))

    def test_mode_with_slash_in_primary_group(self):
        # 表示モデル名を mode に書くと / を含むことがある。service〜login と region・language には / がない
        text = EXPERIMENT_EXAMPLE.replace("chatgpt/web/なし/検索あり/JP/ja", "chatgpt/web/なし/GPT-5 Thinking/検索あり/JP/ja")
        exp = compare.parse_experiment(self.write(text))
        self.assertEqual(exp["primary_group"], ("chatgpt", "web", "なし", "GPT-5 Thinking/検索あり", "JP", "ja"))


class LoaderTest(unittest.TestCase):
    """入力ファイルの読み込みの誤りを、終了コード 2 になる InputError にすること。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "any.csv")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("round\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_csv_error_becomes_input_error(self):
        # csv.Error は ValueError の下位クラスではないので、個別に捕まえて終了コード 2 にする
        # （NUL は read_csv が除いてから読むので、ここでは csv.Error を直接起こす）
        with mock.patch.object(compare, "read_csv", side_effect=csv.Error("field larger than field limit")):
            with self.assertRaises(compare.InputError) as ctx:
                compare.load_observations(self.path)
            self.assertIn("CSV として読めません", str(ctx.exception))
            with self.assertRaises(compare.InputError):
                compare.load_citations(self.path)
            warnings = []
            self.assertEqual(compare.load_competitor_names(self.path, warnings), [])
            self.assertTrue(any("entities.csv" in w or "any.csv" in w for w in warnings))

    def test_os_error_becomes_input_error(self):
        with mock.patch.object(compare, "read_csv", side_effect=PermissionError("読めない")):
            with self.assertRaises(compare.InputError):
                compare.load_observations(self.path)


class MainTest(unittest.TestCase):
    """別プロセスで実行する。一時フォルダに observations.csv などを作る。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ai-search")
        os.makedirs(os.path.join(self.ws, "experiments"))
        self.write_workspace(standard_rows())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_workspace(self, rows, run_info=True):
        common.write_csv(os.path.join(self.ws, "observations.csv"), OBS_FIELDS, rows)
        if run_info:
            info = {"script": "normalize_observations.py", "version": "1.0.0",
                    "generated_at": "2026-10-30T21:00:00+09:00", "entities_sha256": ENTITIES_SHA,
                    "prompts_sha256": None, "answer_files": len(rows), "valid_mention": 0, "valid_citation": 0}
            with open(os.path.join(self.ws, "observations.run.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
        common.write_csv(os.path.join(self.ws, "entities.csv"),
                         ["entity_id", "kind", "name", "terms", "exclude_terms", "domains"], [
                             {"entity_id": "own-company", "kind": "own", "name": "架空珈琲",
                              "terms": "架空珈琲|kakuu coffee", "domains": "kakuu-coffee.example"},
                             {"entity_id": "comp-a", "kind": "competitor", "name": "サンプル焙煎",
                              "terms": "サンプル焙煎", "domains": "sample-roast.example"},
                         ])
        citations = []
        for pid, host in (("P001", "review.example"), ("P002", "review.example"), ("P003", "blog.example")):
            citations.append({"round": "2026-10-01", "answer_file": "answers/2026-10-01/chatgpt/{}-1.md".format(pid),
                              "prompt_id": pid, "service": "chatgpt", "surface": "web", "login": "なし",
                              "mode": "検索あり", "location": "sources", "source_order": "1",
                              "url": "https://{}/kakuu".format(host), "host": host, "entity_id": "",
                              "entity_kind": "other"})
        common.write_csv(os.path.join(self.ws, "citations.csv"), CIT_FIELDS, citations)

    def test_output_same_as_input_exit_2(self):
        # -o や --details-csv に入力のファイルを指定すると、入力（作り直せない実験の記録を含む）を上書きしてしまう
        obs = os.path.join(self.ws, "observations.csv")
        with open(obs, "rb") as f:
            before = f.read()
        for target in (obs, os.path.join(self.ws, "citations.csv"), os.path.join(self.ws, "observations.run.json")):
            proc = helpers.run_script("compare_runs", ["--workspace", self.ws, "--period", "2026-10-01",
                                                       "-o", target], cwd=self.tmp)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("入力", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
        with open(obs, "rb") as f:
            self.assertEqual(f.read(), before)
        exp = self.write_experiment()
        with open(exp, "rb") as f:
            exp_before = f.read()
        for flag in ("-o", "--details-csv"):
            proc = helpers.run_script("compare_runs", ["--workspace", self.ws, "--experiment", exp, flag, exp],
                                      cwd=self.tmp)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("入力", proc.stderr)
        with open(exp, "rb") as f:
            self.assertEqual(f.read(), exp_before)
        # 相対パスで同じファイルを指しても止める
        rel = os.path.relpath(obs, self.tmp)
        proc = helpers.run_script("compare_runs", ["--workspace", self.ws, "--period", "2026-10-01", "-o", rel],
                                  cwd=self.tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)

    def write_experiment(self, _encoding="utf-8", _newline="\n", **overrides):
        values = {
            "id": "E001", "status": "実施中", "hypothesis": "料金表を載せると架空珈琲の引用が増える",
            "change_category": "コンテンツ", "change_summary": "/pricing/ に税込の料金表を追加",
            "changed_on": "2026-10-15", "primary_metric": "citation",
            "primary_group": "chatgpt/web/なし/検索あり/JP/ja", "alpha": "0.05", "min_effect": "0.10",
            "entities_sha256": ENTITIES_SHA, "target_prompts": ", ".join(TARGETS),
            "control_prompts": ", ".join(CONTROLS), "baseline_rounds": "2026-10-01", "after_rounds": "2026-10-29",
            "verdict": "",
        }
        values.update(overrides)
        text = "---\n" + "".join("{}: {}\n".format(k, v) for k, v in values.items()) + "---\n## 仮説\n"
        path = os.path.join(self.ws, "experiments", "E001.md")
        with open(path, "w", encoding=_encoding, newline=_newline) as f:
            f.write(text)
        return path

    def run_compare(self, *args):
        return helpers.run_script("compare_runs", ["--workspace", self.ws] + list(args), cwd=self.tmp)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    # --- 集計（--period） ---

    def test_period_summary(self):
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.assertIn("# AI 検索の観測の集計", out)
        self.assertRegex(out, r"\d+/\d+（\d+\.\d%）")
        self.assertIn("## chatgpt / web / なし / 検索あり / JP / ja", out)
        self.assertIn("## gemini / web / なし", out)
        # chatgpt の組: 有効な回答 37 件のうち言及 12 件、引用の分母 36 件のうち 8 件
        self.assertIn("12/37（32.4%）", out)
        self.assertIn("8/36（22.2%）", out)
        self.assertIn("分母に入れなかった回答", out)
        self.assertIn("status が 未記入 1 件", out)
        self.assertIn("出典が不明 1 件", out)
        self.assertIn("37/38（97.4%）", out)  # AI の回答の表示
        self.assertIn("1a2b3c4d5e6f", out)  # entities.csv の SHA-256 の先頭12桁

    def test_period_error_excludes_claude_draft(self):
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.assertIn("1/2（50.0%）", out)
        self.assertIn("Claude の下書きのみ 1 件", out)
        # 未確認は、自社の言及がある有効な回答のうち、人も Claude もまだ判定していないもの
        self.assertIn("未確認 10 件", out)
        self.assertIn("「未確認」は、自社の言及がある有効な回答のうち", out)

    def test_period_groups_are_not_merged(self):
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        gemini = out.split("## gemini")[1]
        self.assertIn("0/3（0.0%）", gemini)
        self.assertNotIn("12/37", gemini)

    def test_period_details(self):
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.assertIn("comp-a（サンプル焙煎）", out)
        self.assertIn("3/37（8.1%）", out)  # comp-a の言及は P009 の 3 件
        self.assertIn("段階: 認知", out)
        self.assertIn("非指名", out)
        self.assertIn("1番目 8", out)
        self.assertIn("review.example", out)
        self.assertIn("2/36（5.6%）", out)

    def test_period_same_day_warning(self):
        result = self.run_compare("--period", "2026-10-01")
        out = self.assert_ok(result)
        self.assertIn("すべて同じ日", out)  # gemini の組は 2026-10-01 だけ
        self.assertIn("すべて同じ日", result.stderr)

    # --- 比較（--before / --after） ---

    def test_compare_is_exploratory(self):
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        self.assertIn("## 結論", out)
        self.assertIn("探索的", out)
        self.assertNotIn("確認的な判定（", out)
        self.assertIn("原因を示すものではない", out)
        self.assertIn("偶然の差をシグナルと判定しやすくなる", out)
        # 対象を指定しなければ、P009（下がった）も入るので方向がそろわない
        self.assertIn("明確な変化を検出せず（探索的）", out)
        self.assertIn("片方の期間にしかない", out)

    def test_compare_with_targets_and_controls(self):
        out = self.assert_ok(self.run_compare(
            "--before", "2026-10-01", "--after", "2026-10-29",
            "--targets", ",".join(TARGETS), "--controls", ",".join(CONTROLS), "--metric", "citation"))
        self.assertIn("改善シグナル（探索的）", out)
        self.assertIn("対照で調整しても同じ向き", out)
        self.assertNotIn("| 自社の言及 |", out)

    def test_experiment_is_confirmatory(self):
        exp = self.write_experiment()
        details = os.path.join(self.tmp, "details.csv")
        out = self.assert_ok(self.run_compare("--experiment", exp, "--details-csv", details))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", out)
        self.assertIn("対照で調整しても同じ向き", out)
        self.assertIn("原因を示すものではない", out)
        self.assertIn("探索的", out)  # ほかの組・指標
        _fields, rows = common.read_csv(details)
        chatgpt = [r for r in rows if r["group"].startswith("chatgpt") and r["metric"] == "citation"]
        self.assertEqual(sorted(r["prompt_id"] for r in chatgpt if r["set"] == "control"), CONTROLS)
        self.assertEqual(sorted(r["prompt_id"] for r in chatgpt if r["set"] == "target"), TARGETS)
        self.assertFalse([r for r in rows if r["prompt_id"] == "P009"])

    def test_cli_override_makes_it_exploratory(self):
        exp = self.write_experiment()
        out = self.assert_ok(self.run_compare("--experiment", exp, "--alpha", "0.1"))
        self.assertIn("--alpha", out)
        self.assertIn("確認的な判定: 出さない", out)

    def test_details_csv(self):
        details = os.path.join(self.tmp, "details.csv")
        self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29",
                                        "--details-csv", details))
        with open(details, "rb") as f:
            self.assertTrue(f.read(3) == codecs.BOM_UTF8)
        fields, rows = common.read_csv(details)
        self.assertEqual(fields, ["group", "metric", "set", "prompt_id", "before_k", "before_n", "after_k",
                                  "after_n", "diff", "status"])
        p001 = [r for r in rows if r["prompt_id"] == "P001" and r["metric"] == "citation"
                and r["group"].startswith("chatgpt")][0]
        self.assertEqual((p001["before_k"], p001["before_n"], p001["after_k"], p001["after_n"]),
                         ("0", "3", "2", "3"))
        self.assertEqual(p001["diff"], "0.667")
        self.assertEqual(p001["status"], "比較した")
        p009 = [r for r in rows if r["prompt_id"] == "P009" and r["metric"] == "citation"][0]
        self.assertEqual(p009["diff"], "-1.000")

    def test_output_file(self):
        out_path = os.path.join(self.tmp, "reports", "compare.md")
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29", "-o", out_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out_path, encoding="utf-8") as f:
            self.assertIn("## 結論", f.read())

    # --- 警告 ---

    def test_warning_days_differ(self):
        self.write_workspace(standard_rows(after_dates=("2026-10-29",)))
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        self.assertIn("観測した日数が違う", out)
        self.assertIn("すべて同じ日", out)

    def test_no_day_warning_for_chatgpt_when_days_match(self):
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        warnings = section(out, "## 警告")
        self.assertNotRegex(warnings, r"chatgpt[^\n]*観測した日数が違う")

    def test_warning_mode_differs(self):
        self.write_workspace(standard_rows(after_mode="深い調査"))
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        self.assertIn("モードの種類が違う", out)

    def test_warning_entities_sha_differs(self):
        exp = self.write_experiment(entities_sha256="f" * 64)
        result = self.run_compare("--experiment", exp)
        out = self.assert_ok(result)
        self.assertIn("entities_sha256", section(out, "## 警告"))
        self.assertIn("entities_sha256", result.stderr)

    def test_no_warning_when_entities_sha_prefix_matches(self):
        exp = self.write_experiment(entities_sha256=ENTITIES_SHA[:12])
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertNotIn("entities_sha256", section(out, "## 警告"))

    def test_warning_after_round_before_change(self):
        exp = self.write_experiment(changed_on="2026-10-30")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("changed_on", section(out, "## 警告"))

    def test_changed_on_ignores_unrecorded_answers(self):
        rows = standard_rows()
        rows.append(obs_row(round="2026-10-29", prompt_id="P001", repeat="9", observed_at="2026-10-01 ",
                            status="未記入", valid_mention="0", valid_citation="0",
                            exclusion_reason="status が 未記入", **CHATGPT))
        self.write_workspace(rows)
        exp = self.write_experiment()
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertNotIn("changed_on", section(out, "## 警告"))

    def test_primary_group_without_answers(self):
        exp = self.write_experiment(primary_group="claude/web/なし/検索あり/JP/ja")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（claude / web / なし / 検索あり / JP / ja、自社の引用）: 判定不能", out)

    def test_primary_metric_is_kept_when_metric_option_differs(self):
        exp = self.write_experiment()
        out = self.assert_ok(self.run_compare("--experiment", exp, "--metric", "mention"))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", out)
        self.assertIn("| 自社の言及 |", out)

    def test_no_changed_on_warning_when_rounds_are_in_order(self):
        exp = self.write_experiment()
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("## 警告", out)
        self.assertNotIn("changed_on", section(out, "## 警告"))

    def test_warning_without_run_json(self):
        os.remove(os.path.join(self.ws, "observations.run.json"))
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.assertIn("observations.run.json がない", out)

    def test_warning_baseline_round_after_change(self):
        # changed_on より後の日に観測した回答が、変更前のラウンドに入っている
        exp = self.write_experiment(changed_on="2026-09-30")
        warnings = section(self.assert_ok(self.run_compare("--experiment", exp)), "## 警告")
        self.assertIn("変更前のラウンド 2026-10-01 に、changed_on（2026-09-30）より後の回答が", warnings)

    def test_prompts_with_different_n_are_in_warning_section(self):
        rows = standard_rows()
        for row in rows:
            if row["round"] == "2026-10-29" and row["prompt_id"] == "P002" and row["repeat"] == "3":
                row.update(status="エラー", valid_mention="0", valid_citation="0", exclusion_reason="status が エラー")
        self.write_workspace(rows)
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29",
                                              "--targets", ",".join(TARGETS), "--metric", "citation"))
        warnings = section(out, "## 警告")
        self.assertRegex(warnings, r"chatgpt[^\n]*自社の引用 / 対象: [^\n]*前後で有効な回答の数が違うプロンプト 1 件")

    def test_slash_dates_in_observed_at(self):
        # Excel で開いて保存すると 2026/10/29 の形になる。normalize_observations.py と同じく日付として読む
        self.write_workspace(standard_rows(after_dates=("2026/10/29", "2026/10/30")))
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        self.assertNotIn("observed_at に日付がない", out)
        self.assertNotRegex(section(out, "## 警告"), r"chatgpt[^\n]*観測した日数が違う")
        self.write_workspace(standard_rows(after_dates=("2026/10/29",)))
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        self.assertRegex(section(out, "## 警告"), r"chatgpt[^\n]*観測した日数が違う（前 2 日、後 1 日）")

    def test_single_digit_month_and_day(self):
        self.write_workspace(standard_rows(after_dates=("2026-10-9", "2026-10-10")))
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        self.assertNotIn("observed_at に日付がない", out)

    # --- 確認的な判定の条件（事前に決めた条件を後から変えない） ---

    def two_repeat_rows(self):
        """対象 P001〜P008 は 0/2 → 2/2、対照 P101〜P103 は 1/2 のまま（各期間2回ずつ）。"""
        rows = []
        dates_b, dates_a = ("2026-10-01", "2026-10-02"), ("2026-10-29", "2026-10-30")
        for pid in TARGETS:
            rows += make_rows("2026-10-01", dates_b, pid, cited=0, mentioned=0, repeats=2)
            rows += make_rows("2026-10-29", dates_a, pid, cited=2, mentioned=0, repeats=2)
        for pid in CONTROLS:
            rows += make_rows("2026-10-01", dates_b, pid, cited=1, mentioned=0, repeats=2)
            rows += make_rows("2026-10-29", dates_a, pid, cited=1, mentioned=0, repeats=2)
        return rows

    def test_changing_min_repeats_is_not_confirmatory(self):
        self.write_workspace(self.two_repeat_rows())
        exp = self.write_experiment()
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 判定不能", out)
        out = self.assert_ok(self.run_compare("--experiment", exp, "--min-repeats", "2"))
        self.assertNotIn("確認的な判定（", out)
        self.assertIn("確認的な判定: 出さない", out)
        self.assertIn("--min-repeats", section(out, "## 結論"))
        self.assertIn("改善シグナル（探索的）", out)

    def test_default_min_repeats_given_explicitly_is_confirmatory(self):
        exp = self.write_experiment()
        out = self.assert_ok(self.run_compare("--experiment", exp, "--min-repeats", "3"))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", out)

    def test_empty_target_prompts_is_not_confirmatory(self):
        exp = self.write_experiment(target_prompts="", control_prompts="")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定: 出さない", out)
        self.assertIn("target_prompts", section(out, "## 結論"))

    def test_filling_empty_targets_from_cli_is_not_confirmatory(self):
        exp = self.write_experiment(target_prompts="", control_prompts="")
        out = self.assert_ok(self.run_compare("--experiment", exp, "--targets", ",".join(TARGETS[:6])))
        self.assertNotIn("確認的な判定（", out)
        self.assertIn("確認的な判定: 出さない", out)
        self.assertIn("改善シグナル（探索的）", out)

    def test_filling_empty_controls_from_cli_is_not_confirmatory(self):
        exp = self.write_experiment(control_prompts="")
        out = self.assert_ok(self.run_compare("--experiment", exp, "--controls", ",".join(CONTROLS)))
        self.assertIn("確認的な判定: 出さない", out)
        self.assertIn("--controls", section(out, "## 結論"))

    def test_filling_empty_after_rounds_from_cli_is_not_confirmatory(self):
        exp = self.write_experiment(after_rounds="")
        out = self.assert_ok(self.run_compare("--experiment", exp, "--after", "2026-10-29"))
        self.assertIn("確認的な判定: 出さない", out)
        self.assertIn("--after", section(out, "## 結論"))

    def test_empty_controls_without_cli_is_confirmatory(self):
        # 対照を置かない実験は事前に決めた条件どおりなので、確認的な判定を出す（対照がない旨を添える）
        exp = self.write_experiment(control_prompts="")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", out)
        self.assertIn("対照がないため", out)

    def test_adjusted_diff_exactly_zero_end_to_end(self):
        rows = []
        dates_b, dates_a = ("2026-10-01", "2026-10-02"), ("2026-10-29", "2026-10-30")
        for pid, b, a in (("P001", 0, 1), ("P002", 0, 1), ("P003", 0, 1), ("P004", 0, 1), ("P005", 1, 3),
                          ("P006", 1, 3), ("P101", 0, 1), ("P102", 0, 1), ("P103", 0, 2)):
            rows += make_rows("2026-10-01", dates_b, pid, cited=b, mentioned=0)
            rows += make_rows("2026-10-29", dates_a, pid, cited=a, mentioned=0)
        self.write_workspace(rows)
        exp = self.write_experiment(target_prompts=", ".join(TARGETS[:6]), min_effect="")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 判定不能。"
                      "対照も同じ程度に動いた（対照で調整した差 +0.000）", out)

    def test_primary_group_with_slash_in_mode(self):
        rows = standard_rows()
        for row in rows:
            if row["service"] == "chatgpt":
                row["mode"] = "GPT-5 Thinking/検索あり"
        self.write_workspace(rows)
        exp = self.write_experiment(primary_group="chatgpt/web/なし/GPT-5 Thinking/検索あり/JP/ja")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（chatgpt / web / なし / GPT-5 Thinking/検索あり / JP / ja、自社の引用）: 改善シグナル",
                      out)

    # --- Windows で作った入力と、Windows の標準出力 ---

    def test_experiment_record_from_notepad(self):
        exp = self.write_experiment(_encoding="utf-8-sig", _newline="\r\n")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", out)

    def test_experiment_record_in_cp932(self):
        exp = self.write_experiment(_encoding="cp932")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", out)
        self.assertIn("料金表を載せると架空珈琲の引用が増える", out)

    def test_entities_in_cp932(self):
        text = ("entity_id,kind,name,terms,exclude_terms,domains\r\n"
                "own-company,own,架空珈琲,架空珈琲,,kakuu-coffee.example\r\n"
                "comp-a,competitor,サンプル焙煎,サンプル焙煎,,sample-roast.example\r\n")
        with open(os.path.join(self.ws, "entities.csv"), "wb") as f:
            f.write(text.encode("cp932"))
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.assertIn("comp-a（サンプル焙煎）", out)

    def test_stdout_in_cp932_does_not_crash(self):
        # Windows でパイプやファイルにつないだ標準出力（cp932）でも、cp932 にない文字（—）で落ちない
        exp = self.write_experiment(hypothesis="料金表 — 税込の表記を足すと引用が増える")
        cmd = [sys.executable, "-B", os.path.join(helpers.SCRIPTS, "compare_runs.py"),
               "--workspace", self.ws, "--experiment", exp]
        env = dict(os.environ, PYTHONIOENCODING="cp932")
        env.pop("PYTHONUTF8", None)
        result = subprocess.run(cmd, cwd=self.tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode("cp932", errors="replace"))
        out = result.stdout.decode("utf-8")
        self.assertIn("料金表 — 税込", out)
        self.assertIn("## 結論", out)

    # --- 有効な回答がない組（未記入のひな形など） ---

    def rows_with_blank_template(self):
        """変更前のラウンドに、mode が空の未記入のひな形を1件混ぜる。"""
        rows = standard_rows()
        blank = dict(CHATGPT, mode="")
        rows.append(obs_row(round="2026-10-01", prompt_id="P003", repeat="5", observed_at="2026-10-01 ",
                            status="未記入", sources_status="不明", valid_mention="0", valid_citation="0",
                            exclusion_reason="status が 未記入", **blank))
        return rows

    def test_mode_warning_ignores_invalid_answers(self):
        self.write_workspace(self.rows_with_blank_template())
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29"))
        warnings = section(out, "## 警告")
        self.assertNotIn("モードの種類が違う", warnings)
        self.assertNotIn("（空） / JP / ja: この組は", warnings)
        self.assertNotIn("### chatgpt / web / なし / （空） / JP / ja", out)
        self.assertIn("## 有効な回答がない組", out)
        self.assertIn("chatgpt / web / なし / （空） / JP / ja", section(out, "## 有効な回答がない組"))

    def test_period_group_without_valid_answers(self):
        self.write_workspace(self.rows_with_blank_template())
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.assertNotIn("## chatgpt / web / なし / （空） / JP / ja\n", out)
        empty = section(out, "## 有効な回答がない組")
        self.assertIn("chatgpt / web / なし / （空） / JP / ja", empty)
        self.assertIn("status が 未記入 1 件", empty)

    def test_group_with_only_no_ai_answer_is_kept(self):
        # AI の回答なしだけの組は、表示率を示すので「有効な回答がない組」にしない
        rows = standard_rows()
        aio = {"service": "google-aio", "surface": "web", "login": "なし", "mode": "", "region": "JP",
               "language": "ja"}
        for i in range(3):
            rows.append(obs_row(round="2026-10-01", prompt_id="P001", repeat=str(i + 1),
                                observed_at="2026-10-01 10:00", status="AI の回答なし", valid_mention="0",
                                valid_citation="0", exclusion_reason="status が AI の回答なし", **aio))
        self.write_workspace(rows)
        out = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.assertIn("## google-aio / web / なし / （空） / JP / ja\n", out)
        self.assertIn("0/3（0.0%）", out.split("## google-aio")[1])

    # --- 壊れた入力と出力先 ---

    def insert_nul(self, name, replacements):
        """<workspace>/name のバイト列の中で、(元, 置き換え) の最初の出現を置き換える（NUL を入れる）。"""
        path = os.path.join(self.ws, name)
        with open(path, "rb") as f:
            data = f.read()
        for old, new in replacements:
            self.assertIn(old, data)
            data = data.replace(old, new, 1)
        with open(path, "wb") as f:
            f.write(data)

    def test_nul_in_citations_is_removed(self):
        # NUL は read_csv が除いてから読む。Python 3.9（csv が NUL を読めない）でも 3.11 以降（NUL ごと読む）でも、
        # NUL がないときと同じ報告を終了コード 0 で出す。3.13 で NUL ごと読むと P002 の answer_file が回答と
        # 結び付かず、review.example が 2/36 から 1/36 に黙って下がっていた
        base = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        self.insert_nul("citations.csv", [(b"chatgpt/P002-1.md", b"chatgpt/P0\x0002-1.md"),
                                          (b",review.example,", b",review.exa\x00mple,")])
        result = self.run_compare("--period", "2026-10-01")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("NUL", result.stderr)
        self.assertIn("| review.example | 2/36（5.6%） |", result.stdout)
        self.assertEqual(result.stdout, base)

    def test_nul_in_observations_is_removed(self):
        # observations.csv の NUL も同じ。組の値・プロンプトの ID・行末に入った NUL を除き、集計も比較も
        # NUL がないときと同じ報告を終了コード 0 で出す（3.9 では csv.Error で終了コード 2 になっていた）
        exp = self.write_experiment()
        base_period = self.assert_ok(self.run_compare("--period", "2026-10-01"))
        base_compare = self.assert_ok(self.run_compare("--experiment", exp))
        self.insert_nul("observations.csv", [(b",P002,", b",P0\x0002,"), (b",chatgpt,", b",chat\x00gpt,"),
                                             (b"\r\n2026-10-29,", b"\x00\r\n2026-10-29,")])
        for args, base in ((("--period", "2026-10-01"), base_period), (("--experiment", exp), base_compare)):
            result = self.run_compare(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("NUL", result.stderr)
            self.assertEqual(result.stdout, base)
        self.assertIn("12/37（32.4%）", base_period)
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", base_compare)

    def test_output_to_existing_folder_is_error(self):
        result = self.run_compare("--period", "2026-10-01", "-o", self.tmp)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_details_csv_to_existing_folder_is_error_before_writing(self):
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29", "--details-csv", self.tmp)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")  # 報告を書き始める前に止める
        self.assertNotIn("Traceback", result.stderr)

    def test_output_under_a_file_is_error(self):
        afile = os.path.join(self.tmp, "afile")
        with open(afile, "w", encoding="utf-8") as f:
            f.write("x")
        result = self.run_compare("--period", "2026-10-01", "-o", os.path.join(afile, "x.md"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29",
                                  "--details-csv", os.path.join(afile, "sub", "d.csv"))
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_same_path_for_report_and_details_is_error(self):
        path = os.path.join(self.tmp, "same.md")
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29", "-o", path,
                                  "--details-csv", path)
        self.assertEqual(result.returncode, 2, result.stderr)

    # --- プロンプトの ID ---

    def test_targets_separated_by_japanese_comma(self):
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29", "--targets", "P001、P002")
        self.assertEqual(result.returncode, 2)
        self.assertIn("、", result.stderr)

    def test_experiment_ids_separated_by_japanese_comma(self):
        exp = self.write_experiment(target_prompts="P001、P002、P003、P004、P005、P006")
        result = self.run_compare("--experiment", exp)
        self.assertEqual(result.returncode, 2)
        self.assertIn("target_prompts", result.stderr)

    def test_unknown_prompt_id_is_warned(self):
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29",
                                              "--targets", ",".join(TARGETS) + ",P0O1",
                                              "--controls", ",".join(CONTROLS) + ",P1O1"))
        warnings = section(out, "## 警告")
        self.assertRegex(warnings, r"対象[^\n]*P0O1")
        self.assertRegex(warnings, r"対照[^\n]*P1O1")

    # --- entities_sha256 の形式 ---

    def test_too_short_entities_sha_is_warned(self):
        for value in ("1", "1a2b", "1a2b3c4d5e6", "要確認"):
            exp = self.write_experiment(entities_sha256=value)
            warnings = section(self.assert_ok(self.run_compare("--experiment", exp)), "## 警告")
            self.assertIn("entities_sha256", warnings, value)
            self.assertIn("形式", warnings, value)

    def test_full_entities_sha_matches(self):
        exp = self.write_experiment(entities_sha256=ENTITIES_SHA.upper())
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertNotIn("entities_sha256", section(out, "## 警告"))

    # --- 引数と入力の誤り（終了コード 2） ---

    def test_period_and_before_together(self):
        result = self.run_compare("--period", "2026-10-01", "--before", "2026-10-01", "--after", "2026-10-29")
        self.assertEqual(result.returncode, 2)

    def test_neither_period_nor_before(self):
        self.assertEqual(self.run_compare().returncode, 2)

    def test_before_without_after(self):
        self.assertEqual(self.run_compare("--before", "2026-10-01").returncode, 2)

    def test_unknown_round(self):
        result = self.run_compare("--period", "2026-10-01,2099-01-01")
        self.assertEqual(result.returncode, 2)
        self.assertIn("2099-01-01", result.stderr)

    def test_same_round_in_both_periods(self):
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-01,2026-10-29")
        self.assertEqual(result.returncode, 2)

    def test_targets_and_controls_overlap(self):
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29",
                                  "--targets", "P001,P002", "--controls", "P002")
        self.assertEqual(result.returncode, 2)

    def test_bad_group_by(self):
        result = self.run_compare("--period", "2026-10-01", "--group-by", "service,stage")
        self.assertEqual(result.returncode, 2)

    def test_group_by_service_only(self):
        out = self.assert_ok(self.run_compare("--period", "2026-10-01", "--group-by", "service"))
        self.assertIn("## chatgpt", out)
        self.assertNotIn("## chatgpt / web", out)

    def test_missing_observations(self):
        os.remove(os.path.join(self.ws, "observations.csv"))
        result = self.run_compare("--period", "2026-10-01")
        self.assertEqual(result.returncode, 2)
        self.assertIn("normalize_observations.py", result.stderr)

    def test_missing_columns(self):
        with open(os.path.join(self.ws, "observations.csv"), "w", encoding="utf-8") as f:
            f.write("round,prompt_id\n2026-10-01,P001\n")
        self.assertEqual(self.run_compare("--period", "2026-10-01").returncode, 2)

    def test_bad_alpha(self):
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29", "--alpha", "1.5")
        self.assertEqual(result.returncode, 2)

    def test_period_with_details_csv(self):
        result = self.run_compare("--period", "2026-10-01", "--details-csv", os.path.join(self.tmp, "d.csv"))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "d.csv")))

    def test_min_repeats_zero(self):
        result = self.run_compare("--before", "2026-10-01", "--after", "2026-10-29", "--min-repeats", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--min-repeats", result.stderr)

    def test_help(self):
        result = helpers.run_script("compare_runs", ["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout)

    def test_missing_observations_without_hint(self):
        os.remove(os.path.join(self.ws, "observations.csv"))
        result = self.run_compare("--period", "2026-10-01")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("--workspace .", result.stderr)

    def test_running_inside_the_workspace_hints_workspace_dot(self):
        # ai-search/ の中で --workspace を付けずに実行した。normalize_observations.py の実行を促さない
        result = helpers.run_script("compare_runs", ["--period", "2026-10-01"], cwd=self.ws)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--workspace .", result.stderr)
        self.assertNotIn("先に normalize_observations.py を実行してください", result.stderr)
        result = helpers.run_script("compare_runs", ["--period", "2026-10-01", "--workspace", "."], cwd=self.ws)
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- primary_group の書き誤り ---

    def test_primary_group_typo_is_warned(self):
        exp = self.write_experiment(primary_group="chatgpt/web/なし/検索/JP/ja")
        result = self.run_compare("--experiment", exp)
        out = self.assert_ok(result)
        conclusion = section(out, "## 結論")
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索 / JP / ja、自社の引用）: 判定不能", conclusion)
        self.assertIn("書き誤り", conclusion)
        warnings = section(out, "## 警告")
        self.assertIn("primary_group（chatgpt/web/なし/検索/JP/ja）", warnings)
        self.assertIn("chatgpt/web/なし/検索あり/JP/ja", warnings)  # 観測した組の一覧
        # 標準エラーの要約も、報告と同じく判定不能とする（「すべて探索的」としない）
        self.assertIn("確認的な判定: 判定不能（primary_group の組が見つからない）", result.stderr)
        self.assertNotIn("すべて探索的", result.stderr)

    # --- 片方の期間にしか有効な回答がない組 ---

    def rows_with_before_only_group(self):
        """変更後のラウンドを chatgpt だけで作った（google-ai-mode の組は変更前にしかない）。"""
        rows = standard_rows()
        aim = dict(CHATGPT, service="google-ai-mode")
        for pid in TARGETS + CONTROLS:
            rows += make_rows("2026-10-01", ("2026-10-01", "2026-10-02"), pid, cited=1, mentioned=1, group=aim)
        return rows

    def test_group_only_in_one_period_is_not_comparable(self):
        exp = self.write_experiment()
        base = self.assert_ok(self.run_compare("--experiment", exp))
        self.write_workspace(self.rows_with_before_only_group())
        details = os.path.join(self.tmp, "details.csv")
        result = self.run_compare("--experiment", exp, "--details-csv", details)
        out = self.assert_ok(result)
        self.assertNotIn("### google-ai-mode", out)
        not_comparable = section(out, "## 比較できない組")
        self.assertIn("google-ai-mode / web / なし / 検索あり / JP / ja", not_comparable)
        self.assertIn("変更後の期間にこの組の有効な回答がない", not_comparable)
        self.assertNotIn("google-ai-mode", section(out, "## 外したプロンプト"))
        warnings = [line for line in section(out, "## 警告").splitlines() if "google-ai-mode" in line]
        self.assertEqual(len(warnings), 1, warnings)
        # 探索的な判定の内訳に数えない（google-ai-mode の組がないときと同じ）
        def breakdown(text):
            return [line for line in text.splitlines() if line.startswith("- 探索的な判定の内訳")]
        self.assertEqual(breakdown(out), breakdown(base))
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / JP / ja、自社の引用）: 改善シグナル", out)
        _fields, rows = common.read_csv(details)
        self.assertFalse([r for r in rows if r["group"].startswith("google-ai-mode")])

    def test_primary_group_only_in_one_period(self):
        self.write_workspace(self.rows_with_before_only_group())
        exp = self.write_experiment(primary_group="google-ai-mode/web/なし/検索あり/JP/ja")
        result = self.run_compare("--experiment", exp)
        out = self.assert_ok(result)
        self.assertIn("確認的な判定（google-ai-mode / web / なし / 検索あり / JP / ja、自社の引用）: 判定不能。"
                      "変更後の期間にこの組の有効な回答がない", out)
        self.assertNotIn("書き誤り", out)
        self.assertIn("確認的な判定: 判定不能（変更後の期間にこの組の有効な回答がない）", result.stderr)

    # --- 表記だけが違う組（region の JP と jp など） ---

    SPLIT_TARGETS = ", ".join("P{:03d}".format(i) for i in range(1, 13))

    def rows_split_by_region(self):
        """
        chatgpt の組が region の表記で2つに割れている。JP の P001〜P006 は引用が 0/3 → 2/3（上がる）、
        jp の P007〜P012 は 2/3 → 0/3（下がる）。
        """
        rows = []
        dates_b, dates_a = ("2026-10-01", "2026-10-02"), ("2026-10-29", "2026-10-30")
        for i in range(12):
            pid = "P{:03d}".format(i + 1)
            group = dict(CHATGPT, region="JP" if i < 6 else "jp")
            b, a = (0, 2) if i < 6 else (2, 0)
            rows += make_rows("2026-10-01", dates_b, pid, cited=b, mentioned=0, group=group)
            rows += make_rows("2026-10-29", dates_a, pid, cited=a, mentioned=0, group=group)
        return rows

    @staticmethod
    def subsection(text, heading):
        """「### heading」の節（次の ### か ## の見出しの前まで）。"""
        parts = text.split(heading + "\n", 1)
        if len(parts) < 2:
            return ""
        return re.split(r"\n##", parts[1], maxsplit=1)[0]

    def test_primary_group_prefers_exact_notation(self):
        # 表記が完全に一致する組（jp）を確認的な判定に使う。sorted 順で先に来る JP の組を黙って使わない
        self.write_workspace(self.rows_split_by_region())
        exp = self.write_experiment(primary_group="chatgpt/web/なし/検索あり/jp/ja", target_prompts=self.SPLIT_TARGETS,
                                    control_prompts="")
        result = self.run_compare("--experiment", exp)
        out = self.assert_ok(result)
        self.assertIn("確認的な判定（chatgpt / web / なし / 検索あり / jp / ja、自社の引用）: 悪化シグナル", out)
        self.assertIn("悪化シグナル（確認的）", self.subsection(out, "### chatgpt / web / なし / 検索あり / jp / ja"))
        upper = self.subsection(out, "### chatgpt / web / なし / 検索あり / JP / ja")
        self.assertIn("改善シグナル（探索的）", upper)
        self.assertNotIn("（確認的）", upper)
        self.assertIn("確認的な判定: 悪化シグナル", result.stderr)
        # 組が表記で割れていることは警告する
        self.assertRegex(section(out, "## 警告"),
                         r"だけが違う[^\n]*chatgpt / web / なし / 検索あり / JP / ja[^\n]*"
                         r"chatgpt / web / なし / 検索あり / jp / ja")

    def test_primary_group_split_by_notation_is_undecidable(self):
        # 正規化してはじめて一致する組が2つ（JP と jp）あれば、どちらも選ばずに判定不能にする
        self.write_workspace(self.rows_split_by_region())
        for primary in ("chatgpt/web/なし/検索あり/Jp/ja", "chatgpt/web/なし/検索あり/ＪＰ/ja"):
            with self.subTest(primary=primary):
                exp = self.write_experiment(primary_group=primary, target_prompts=self.SPLIT_TARGETS,
                                            control_prompts="")
                result = self.run_compare("--experiment", exp)
                out = self.assert_ok(result)
                conclusion = section(out, "## 結論")
                self.assertIn("確認的な判定（{}、自社の引用）: 判定不能".format(primary.replace("/", " / ")),
                              conclusion)
                self.assertIn("表記ゆれ", conclusion)
                self.assertNotIn("書き誤り", conclusion)
                self.assertNotIn("（確認的）", out)
                warnings = section(out, "## 警告")
                self.assertRegex(warnings, r"primary_group（{}）[^\n]*chatgpt/web/なし/検索あり/JP/ja、"
                                           r"chatgpt/web/なし/検索あり/jp/ja".format(re.escape(primary)))
                self.assertIn("確認的な判定: 判定不能（primary_group の組が表記ゆれで割れている）", result.stderr)
                # どちらの組の判定も探索的として内訳に数える
                self.assertIn("- 探索的な判定の内訳（組×指標）: 改善シグナル 1、悪化シグナル 1、", out)

    def test_primary_group_in_other_notation_matches_single_group(self):
        # 正規化して一致する組が1つだけなら、その組を使う（大文字・小文字の違いは書き誤りとみなさない）
        exp = self.write_experiment(primary_group="ChatGPT/web/なし/検索あり/jp/JA")
        out = self.assert_ok(self.run_compare("--experiment", exp))
        self.assertIn("確認的な判定（ChatGPT / web / なし / 検索あり / jp / JA、自社の引用）: 改善シグナル", out)
        self.assertNotIn("だけが違う", section(out, "## 警告"))

    def test_groups_split_by_notation_are_warned(self):
        self.write_workspace(self.rows_split_by_region())
        for args in (("--period", "2026-10-01"), ("--before", "2026-10-01", "--after", "2026-10-29")):
            with self.subTest(args=args):
                result = self.run_compare(*args)
                out = self.assert_ok(result)
                warnings = [line for line in section(out, "## 警告").splitlines() if "だけが違う" in line]
                self.assertEqual(len(warnings), 1, warnings)
                self.assertIn("chatgpt / web / なし / 検索あり / JP / ja、chatgpt / web / なし / 検索あり / jp / ja",
                              warnings[0])
                self.assertIn("だけが違う", result.stderr)

    def test_no_notation_warning_for_distinct_groups(self):
        # chatgpt と gemini、mode が空の未記入のひな形の組は、表記だけの違いではない
        self.write_workspace(self.rows_with_blank_template())
        for args in (("--period", "2026-10-01"), ("--before", "2026-10-01", "--after", "2026-10-29")):
            with self.subTest(args=args):
                out = self.assert_ok(self.run_compare(*args))
                self.assertNotIn("だけが違う", out)

    def test_split_only_in_rows_without_valid_answers_is_not_warned(self):
        # 表記の違う組が、有効な回答も AI の回答なしもない回答（未記入のひな形）だけなら、集計は割れていない
        rows = standard_rows()
        rows.append(obs_row(round="2026-10-01", prompt_id="P001", repeat="5", observed_at="2026-10-01 ",
                            status="未記入", sources_status="不明", valid_mention="0", valid_citation="0",
                            exclusion_reason="status が 未記入", **dict(CHATGPT, region="jp")))
        self.write_workspace(rows)
        self.assertNotIn("だけが違う", self.assert_ok(self.run_compare("--period", "2026-10-01")))

    # --- p の表示（α の境目） ---

    def test_p_near_alpha_in_table(self):
        # 42 件が上がり 25 件が下がる: p = 0.049800… < 0.05 で改善シグナル。表の p を「0.050」と出さない
        rows = []
        dates_b, dates_a = ("2026-10-01", "2026-10-02"), ("2026-10-29", "2026-10-30")
        for i in range(67):
            pid = "P{:03d}".format(i + 1)
            rows += make_rows("2026-10-01", dates_b, pid, cited=1, mentioned=0)
            rows += make_rows("2026-10-29", dates_a, pid, cited=2 if i < 42 else 0, mentioned=0)
        self.write_workspace(rows)
        out = self.assert_ok(self.run_compare("--before", "2026-10-01", "--after", "2026-10-29",
                                              "--metric", "citation"))
        line = [row for row in out.splitlines() if row.startswith("| 自社の引用 |")][0]
        self.assertIn("| 42 | 25 | 0 |", line)
        self.assertIn("| 67 | 0.0498 |", line)
        self.assertIn("改善シグナル（探索的）", line)

    # --- own_first_source_order の読めない値 ---

    def test_unreadable_source_order_is_not_an_unexpected_error(self):
        # 手で直した observations.csv の ①・²・全角の１・桁の多すぎる数字は、終了コード 1 と traceback に
        # せず、出典の並び順の分布から外して警告する
        rows = standard_rows()
        odd = {("P009", "1"): "①", ("P009", "2"): "²", ("P009", "3"): "１", ("P101", "1"): "9" * 5000}
        for row in rows:
            key = (row["prompt_id"], row["repeat"])
            if row["round"] == "2026-10-01" and row["service"] == "chatgpt" and key in odd:
                row["own_first_source_order"] = odd[key]
        self.write_workspace(rows)
        result = self.run_compare("--period", "2026-10-01")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        out = result.stdout
        self.assertIn("1番目 4 / 2〜3番目 0 / 4番目以降 0 / 本文のリンクだけ 0 / 読めない値 4", out)
        warnings = section(out, "## 警告")
        self.assertRegex(warnings, r"chatgpt / web / なし / 検索あり / JP / ja: own_first_source_order が読めない"
                                   r"[^\n]* 4 件")
        self.assertNotIn("9" * 100, warnings)  # 長い値はそのまま出さない
        self.assertIn("own_first_source_order", result.stderr)


if __name__ == "__main__":
    unittest.main()
