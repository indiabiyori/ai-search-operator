# -*- coding: utf-8 -*-
"""
ai_robots_check.py のテスト。

robots.txt の解釈のテストは、seo-operator v1.1.0 の tests/audit/verify_audit.py の case_robots_unit を
unittest に移植したもの。取得のテストは、ローカルのテスト用サーバー（http.server）をポートごとに立てて確かめる。
"""
import codecs
import csv
import datetime
import http.server
import io
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

# python3 -m unittest tests.test_robots（リポジトリのルートから）でも helpers を読めるようにする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

import ai_search_common as common  # noqa: E402  （helpers が scripts を sys.path に入れている）

robots = helpers.load_script("ai_robots_check")

CRAWLERS_CSV = os.path.join(helpers.FIXTURES, "ai-crawlers.csv")
LIMIT = 512000  # 500 KiB
HEADER = "operator,token,category,purpose,robots_control,block_effect,source_url,checked_on\n"


def canon(value):
    return robots.robots_canonical_path(value)


def crawler(token, category="training", operator="テスト運営"):
    return {"operator": operator, "token": token, "category": category}


def by_token(rows, token, path="/"):
    for row in rows:
        if row["token"] == token and row["path"] == path:
            return row
    raise AssertionError("{} {} の行がありません".format(token, path))


# ---------------------------------------------------------------------------
# robots.txt の解釈（verify_audit.py の case_robots_unit から移植）
# ---------------------------------------------------------------------------

class RobotsPatternTest(unittest.TestCase):
    def pm(self, path, pattern):
        return robots.robots_pattern_match(canon(path), canon(pattern))

    def test_google_matching_table(self):
        # Google の robots.txt 仕様の「パスの値に基づく URL の照合」の表
        fish = (["/fish", "/fish.html", "/fish/salmon.html", "/fishheads", "/fishheads/yummy.html",
                 "/fish.php?id=anything"], ["/Fish.asp", "/catfish", "/?id=fish", "/desert/fish"])
        table = [
            ("/", ["/", "/a", "/fish.html"], []),
            ("/*", ["/", "/a", "/fish.html"], []),
            ("/$", ["/"], ["/a", "/fish"]),
            ("/fish", fish[0], fish[1]),
            ("/fish*", fish[0], fish[1]),
            ("/fish/", ["/fish/", "/fish/?id=anything", "/fish/salmon.htm"],
             ["/fish", "/fish.html", "/animals/fish/", "/Fish/Salmon.asp"]),
            ("/*.php", ["/index.php", "/filename.php", "/folder/filename.php", "/folder/filename.php?parameters",
                        "/folder/any.php.file.html", "/filename.php/"], ["/", "/windows.PHP"]),
            ("/*.php$", ["/filename.php", "/folder/filename.php"],
             ["/filename.php?parameters", "/filename.php/", "/filename.php5", "/windows.PHP"]),
            ("/fish*.php", ["/fish.php", "/fishheads/catfish.php?parameters"], ["/Fish.PHP"]),
        ]
        for pattern, yes, no in table:
            for path in yes:
                with self.subTest(pattern=pattern, path=path):
                    self.assertTrue(self.pm(path, pattern))
            for path in no:
                with self.subTest(pattern=pattern, path=path):
                    self.assertFalse(self.pm(path, pattern))

    def test_many_wildcards_do_not_explode(self):
        # * の多いパターンでも暴走しない（正規表現の後戻りを使わない）
        t0 = time.monotonic()
        result = robots.robots_pattern_match("/" + "a" * 20000, "/" + "*a" * 40 + "*b")
        elapsed = time.monotonic() - t0
        self.assertFalse(result)
        self.assertLess(elapsed, 0.5)


class RobotsPrecedenceTest(unittest.TestCase):
    def test_longest_match_and_allow_on_tie(self):
        cases = [
            ("/page", [("/p", True), ("/", False)], True),
            ("/folder/page", [("/folder", True), ("/folder", False)], True),
            ("/page.htm", [("/page", True), ("/*.htm", False)], False),
            ("/page.php5", [("/page", True), ("/*.ph", False)], True),
            ("/", [("/$", True), ("/", False)], True),
            ("/page.htm", [("/$", True), ("/", False)], False),
        ]
        for path, rules, expected in cases:
            with self.subTest(path=path, rules=rules):
                got = robots.RobotsRules([(canon(p), a) for p, a in rules], "t").allowed_path(canon(path))
                self.assertEqual(got, expected)

    def test_decide_returns_deciding_rule(self):
        rules = robots.RobotsRules([("/private/", False), ("/private/open/", True)], "t")
        self.assertEqual(rules.decide("/private/x"), (False, ("/private/", False)))
        self.assertEqual(rules.decide("/private/open/a"), (True, ("/private/open/", True)))
        self.assertEqual(rules.decide("/public"), (True, None))

    def test_robots_txt_itself_always_allowed(self):
        rules = robots.RobotsRules([("/", False)], "t")
        self.assertEqual(rules.decide("/robots.txt"), (True, None))


class RobotsGroupsTest(unittest.TestCase):
    def blocked(self, text, tokens, path):
        return not robots.select_robots_rules(robots.parse_robots(text), tokens).allowed_path(canon(path))

    def test_user_agent_selection(self):
        text = ("user-agent: googlebot-news\ndisallow: /news\n\n"
                "user-agent: *\ndisallow: /star\n\n"
                "user-agent: googlebot\ndisallow: /gb\n")
        checks = [
            (["googlebot-news", "googlebot"], "/news", True), (["googlebot-news", "googlebot"], "/gb", False),
            (["googlebot-news", "googlebot"], "/star", False),
            (["googlebot"], "/gb", True), (["googlebot"], "/news", False), (["googlebot"], "/star", False),
            (["storebot-google"], "/star", True), (["storebot-google"], "/gb", False),
            (["otherbot"], "/star", True),
        ]
        for tokens, path, expected in checks:
            with self.subTest(tokens=tokens, path=path):
                self.assertEqual(self.blocked(text, tokens, path), expected)

    def test_misc_cases(self):
        misc = [
            # 同じ UA の複数グループは結合、* とは結合しない
            ("user-agent: a\ndisallow: /c\n\nuser-agent: b\ndisallow: /d\n\nuser-agent: A\ndisallow: /e\n\n"
             "user-agent: *\ndisallow: /f\n", ["a"], [("/c", True), ("/e", True), ("/d", False), ("/f", False)]),
            # sitemap 行はグループを区切らない（a と b の両方に disallow: / が効く）
            ("user-agent: a\nsitemap: https://kakuu-coffee.example/sitemap.xml\n\nuser-agent: b\ndisallow: /\n",
             ["a"], [("/x", True)]),
            ("user-agent: a\nsitemap: https://kakuu-coffee.example/sitemap.xml\n\nuser-agent: b\ndisallow: /\n",
             ["b"], [("/x", True)]),
            # 最初の User-agent より前のルールは無視
            ("disallow: /x\nuser-agent: *\nallow: /\n", ["zzz"], [("/x", False)]),
            # 空の Disallow は無視（全許可）
            ("user-agent: *\ndisallow:\n", ["zzz"], [("/anything", False)]),
            # googlebot/1.2 と googlebot* は googlebot と同じ
            ("User-agent: googlebot/1.2\nDisallow: /v\n", ["googlebot"], [("/v", True)]),
            ("user-agent: googlebot*\ndisallow: /w\n", ["googlebot"], [("/w", True)]),
            # 「* 」で始まる値は全体向け、*bot はどれにも一致しない
            ("user-agent: * extra\ndisallow: /g\n", ["zzz"], [("/g", True)]),
            ("user-agent: *bot\ndisallow: /g\n", ["zzz"], [("/g", False)]),
            # フィールド名と UA の値の大文字小文字、コメント、コロンのない行
            ("USER-AGENT: ZZZ\nDISALLOW: /u # コメント\nDisallow /nocolon\n", ["zzz"],
             [("/u", True), ("/u#", True), ("/nocolon", False)]),
            # パーセントエンコードの正規化
            ("user-agent: *\ndisallow: /foo/bar/ツ\n", ["zzz"], [("/foo/bar/%E3%83%84", True)]),
            ("user-agent: *\ndisallow: /foo/bar/%E3%83%84\n", ["zzz"], [("/foo/bar/ツ", True)]),
            ("user-agent: *\ndisallow: /foo/bar/%e3%83%84\n", ["zzz"], [("/foo/bar/%E3%83%84", True)]),
            ("user-agent: *\ndisallow: /foo/bar/%62%61%7A\n", ["zzz"], [("/foo/bar/baz", True)]),
            ("user-agent: *\ndisallow: /a%2Fb\n", ["zzz"], [("/a/b", False), ("/a%2fb", True)]),
            ("user-agent: *\ndisallow: /a b\n", ["zzz"], [("/a%20b", True)]),
            # 途中の $ はただの文字、クエリも照合対象
            ("user-agent: *\ndisallow: /a$b\n", ["zzz"], [("/a$bc", True), ("/ab", False)]),
            ("user-agent: *\ndisallow: /*?\n", ["zzz"], [("/p?x=1", True), ("/p", False)]),
            # /robots.txt は常に許可、グループがなければ全許可
            ("user-agent: *\ndisallow: /\n", ["zzz"], [("/robots.txt", False), ("/", True)]),
            ("", ["zzz"], [("/x", False)]),
            # CR だけの改行、CRLF
            ("user-agent: *\rdisallow: /cr\r", ["zzz"], [("/cr", True)]),
            ("user-agent: *\r\ndisallow: /crlf\r\n", ["zzz"], [("/crlf", True)]),
        ]
        for text, tokens, checks in misc:
            for path, expected in checks:
                with self.subTest(text=text[:60], tokens=tokens, path=path):
                    self.assertEqual(self.blocked(text, tokens, path), expected)

    def test_selected_group_is_recorded(self):
        groups = robots.parse_robots("user-agent: gptbot\ndisallow: /\n\nuser-agent: *\ndisallow: /x\n")
        self.assertEqual(robots.select_robots_rules(groups, ["gptbot"]).agent, "gptbot")
        self.assertEqual(robots.select_robots_rules(groups, ["ccbot"]).agent, "*")
        self.assertIsNone(robots.select_robots_rules(robots.parse_robots(""), ["ccbot"]).agent)


class RobotsTargetTest(unittest.TestCase):
    def test_targets(self):
        cases = [
            ("http://h:80/a/b?x=1#frag", "/a/b?x=1"), ("http://h", "/"), ("http://h?q=1", "/?q=1"),
            ("https://h/日本?q=あ", "/%E6%97%A5%E6%9C%AC?q=%E3%81%82"), ("https://h/%7euser", "/~user"),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(robots.robots_target(url), expected)

    def test_product_token(self):
        # 移植元は seo-operator の UA で確かめていた。ここではこのスクリプトの UA で確かめる
        cases = [(robots.USER_AGENT, "ai-search-operator"), ("Mozilla/5.0 (x)", "mozilla"), ("(x)", ""),
                 ("GPTBot", "gptbot"), ("Google-Extended", "google-extended")]
        for ua, expected in cases:
            with self.subTest(ua=ua):
                self.assertEqual(robots.product_token(ua), expected)


class InternalAddressTest(unittest.TestCase):
    def test_internal(self):
        for address in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "100.64.0.1", "169.254.1.1",
                        "0.0.0.0", "::1", "fe80::1%en0", "fc00::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1",
                        "not-an-address"):
            with self.subTest(address=address):
                self.assertTrue(robots.internal_address(address))

    def test_public(self):
        # 公開アドレスの例（接続はしない）。6to4 は中の IPv4 アドレス（ここでは公開の 93.184.215.14）で判定する
        for address in ("93.184.215.14", "2606:4700::1", "2002:5db8:d70e::1"):
            with self.subTest(address=address):
                self.assertFalse(robots.internal_address(address))

    # IANA の特別用途のアドレスのうち、Python のパッチ版で is_private の判定が変わったもの（CVE-2024-4032 の修正）。
    # macOS の /usr/bin/python3（3.9.6）では、以前はどれも内部と判定されなかった
    SPECIAL_PURPOSE = (
        "192.0.0.8", "192.0.0.9", "192.0.0.100", "192.0.0.255",  # IETF のプロトコルの割り当て（192.0.0.0/24）
        "2002:7f00:1::1", "2002:a00:1::1", "2002:a9fe:a9fe::1", "2002:c0a8:101::1",  # 6to4 に内部の IPv4 を埋め込む
        "2002:6440:1::1",  # 6to4 に共有アドレス（100.64.0.1）を埋め込む
        "3fff::1", "2001:db8::1", "64:ff9b:1::1", "2001::1", "100::1", "5f00::1",
        "198.18.0.1", "192.0.2.1", "198.51.100.1", "203.0.113.1", "192.88.99.1",
        "224.0.0.1", "240.0.0.1", "255.255.255.255", "fec0::1", "ff02::1", "::7f00:1",
        "64:ff9b::c000:8",  # NAT64 に 192.0.0.8 を埋め込む
    )

    def test_special_purpose_addresses(self):
        for address in self.SPECIAL_PURPOSE:
            with self.subTest(address=address):
                self.assertTrue(robots.internal_address(address))

    def test_does_not_depend_on_is_private(self):
        # ipaddress の is_private が古い表でも（パッチ版の違いを模す）、自前の表で同じ判定になる
        with mock.patch.object(ipaddress.IPv4Address, "is_private", new_callable=mock.PropertyMock,
                               return_value=False), \
                mock.patch.object(ipaddress.IPv6Address, "is_private", new_callable=mock.PropertyMock,
                                  return_value=False):
            for address in self.SPECIAL_PURPOSE + ("10.1.2.3", "172.16.0.1", "192.168.1.1", "fc00::1",
                                                   "::ffff:10.0.0.1"):
                with self.subTest(address=address):
                    self.assertTrue(robots.internal_address(address))
            self.assertFalse(robots.internal_address("93.184.215.14"))
            self.assertFalse(robots.internal_address("2002:5db8:d70e::1"))


# ---------------------------------------------------------------------------
# クローラーの一覧
# ---------------------------------------------------------------------------

class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path


class LoadCrawlersTest(TempDirCase):
    HEADER = "operator,token,category,purpose,robots_control,block_effect,source_url,checked_on\n"

    def test_fixture(self):
        crawlers = robots.load_crawlers(CRAWLERS_CSV)
        self.assertEqual([c["token"] for c in crawlers],
                         ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "Google-Extended", "Googlebot", "CCBot"])
        self.assertEqual(crawlers[3]["category"], "control")

    def test_categories_include_other(self):
        self.assertEqual(robots.CATEGORIES["other"], "その他")
        self.assertEqual(list(robots.CATEGORIES),
                         ["general-search", "search", "training", "user", "control", "dataset", "other"])

    def load_capturing(self, path):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            crawlers = robots.load_crawlers(path)
        return crawlers, err.getvalue()

    def test_unknown_category_becomes_other(self):
        path = self.write("c.csv", self.HEADER + "架空運営,KakuuBot,mystery,,,,,2026-09-26\n")
        crawlers, err = self.load_capturing(path)
        self.assertEqual(crawlers[0]["category"], "other")
        self.assertIn("category mystery は決まった値", err)

    def test_token_not_product_token(self):
        # 数字を含むトークンは先頭の英字の部分で照合し、英字で始まらないトークンは飛ばす
        path = self.write("c.csv", self.HEADER + "架空運営,Kakuu2Bot,training,,,,,2026-09-26\n"
                                                 "架空運営,9KakuuBot,training,,,,,2026-09-26\n")
        crawlers, err = self.load_capturing(path)
        self.assertEqual([c["token"] for c in crawlers], ["Kakuu2Bot"])
        self.assertIn("先頭の kakuu で照合します", err)
        self.assertIn("この行を飛ばします", err)

    def test_missing_column(self):
        path = self.write("c.csv", "operator,token\n架空運営,KakuuBot\n")
        with self.assertRaises(robots.InputError):
            robots.load_crawlers(path)

    def test_empty_token(self):
        path = self.write("c.csv", self.HEADER + "架空運営,,training,,,,,2026-09-26\n")
        with self.assertRaises(robots.InputError):
            robots.load_crawlers(path)

    def test_empty_list(self):
        path = self.write("c.csv", self.HEADER)
        with self.assertRaises(robots.InputError):
            robots.load_crawlers(path)

    def test_duplicate_token_keeps_first(self):
        path = self.write("c.csv", self.HEADER + "架空運営,KakuuBot,training,,,,,2026-09-26\n"
                                                 "別の運営,kakuubot,search,,,,,2026-09-26\n")
        crawlers, err = self.load_capturing(path)
        self.assertEqual(len(crawlers), 1)
        self.assertEqual(crawlers[0]["operator"], "架空運営")
        self.assertIn("重複しています", err)

    def test_cp932_file(self):
        text = self.HEADER + "架空運営,KakuuBot,training,テスト,,,,2026-09-26\n"
        path = self.write("c.csv", text.encode("cp932"))
        self.assertEqual(robots.load_crawlers(path)[0]["operator"], "架空運営")

    def test_oldest_checked_on(self):
        crawlers = robots.load_crawlers(CRAWLERS_CSV)
        self.assertEqual(robots.oldest_checked_on(crawlers), "2026-08-01")
        self.assertIsNone(robots.oldest_checked_on([crawler("KakuuBot")]))

    def test_stale_warning(self):
        self.assertIsNone(robots.stale_warning("2026-09-26", datetime.date(2026, 12, 25)))
        self.assertIn("3か月以上", robots.stale_warning("2026-09-26", datetime.date(2026, 12, 26)))
        # 月末の日付は、3か月後の月の末日に寄せる
        self.assertIsNone(robots.stale_warning("2026-11-30", datetime.date(2027, 2, 27)))
        self.assertIsNotNone(robots.stale_warning("2026-11-30", datetime.date(2027, 2, 28)))
        self.assertIsNone(robots.stale_warning(None))


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------

def ok_state(text):
    return {"state": "ok", "code": 200, "text": text, "final_url": "https://kakuu-coffee.example/robots.txt",
            "detail": "", "truncated": False}


class EvaluateTest(unittest.TestCase):
    ROBOTS = ("User-agent: GPTBot\nDisallow: /\n\n"
              "User-agent: *\nDisallow: /private/\n")

    def setUp(self):
        self.crawlers = robots.load_crawlers(CRAWLERS_CSV)

    def test_gptbot_only_blocked(self):
        rows = robots.evaluate(ok_state(self.ROBOTS), self.crawlers, ["/"])
        self.assertEqual(len(rows), 6)
        gpt = by_token(rows, "GPTBot")
        self.assertEqual(gpt["verdict"], "拒否")
        self.assertEqual(gpt["matched_group"], "User-agent: GPTBot")
        self.assertEqual(gpt["matched_rule"], "Disallow: /")
        search = by_token(rows, "OAI-SearchBot")
        self.assertEqual(search["verdict"], "許可")
        self.assertEqual(search["matched_group"], "User-agent: *")
        self.assertEqual(search["matched_rule"], "")
        self.assertIn("学習などへの利用の可否を表す", by_token(rows, "Google-Extended")["note"])
        user_note = by_token(rows, "ChatGPT-User")["note"]
        self.assertIn("ユーザー操作に伴う取得", user_note)
        self.assertIn("robots.txt の扱い（運営の説明）: robots.txt", user_note)  # 一覧の robots_control を添える
        self.assertEqual(by_token(rows, "Googlebot")["note"], "")
        self.assertEqual(list(gpt), robots.OUTPUT_FIELDS)

    def test_multiple_paths_and_normalization(self):
        text = "User-agent: *\nDisallow: /private/\nDisallow: /日本\nAllow: /private/open/\n"
        rows = robots.evaluate(ok_state(text), [crawler("CCBot", "dataset")],
                               ["/", "private/x", "/private/open/a", "/日本/page",
                                "https://kakuu-coffee.example/private/y"])
        verdicts = [(r["path"], r["verdict"], r["matched_rule"]) for r in rows]
        self.assertEqual(verdicts, [
            ("/", "許可", ""),
            ("/private/x", "拒否", "Disallow: /private/"),
            ("/private/open/a", "許可", "Allow: /private/open/"),
            ("/日本/page", "拒否", "Disallow: /%E6%97%A5%E6%9C%AC"),
            ("/private/y", "拒否", "Disallow: /private/"),
        ])

    def test_no_group(self):
        rows = robots.evaluate(ok_state("User-agent: KakuuBot\nDisallow: /\n"), [crawler("CCBot", "dataset")], ["/"])
        self.assertEqual(rows[0]["verdict"], "許可")
        self.assertEqual(rows[0]["matched_group"], "なし")

    def test_missing_state(self):
        state = {"state": "missing", "code": 404, "text": "", "final_url": "", "detail": "ステータス 404",
                 "truncated": False}
        rows = robots.evaluate(state, [crawler("GPTBot")], ["/"])
        self.assertEqual(rows[0]["verdict"], "全許可（robots.txt なし）")
        self.assertEqual(rows[0]["matched_group"], "")
        self.assertIn("ステータス 404", rows[0]["note"])

    def test_unreachable_state(self):
        state = {"state": "unreachable", "code": 503, "text": "", "final_url": "", "detail": "ステータス 503",
                 "truncated": False}
        rows = robots.evaluate(state, [crawler("GPTBot")], ["/"])
        self.assertEqual(rows[0]["verdict"], "全拒否（取得できず）")
        self.assertIn("ステータス 503", rows[0]["note"])
        self.assertIn("各社の実際の扱いは異なりうる", rows[0]["note"])

    def test_rate_limited_state(self):
        state = {"state": "rate_limited", "code": 429, "text": "", "final_url": "", "detail": "ステータス 429",
                 "truncated": False}
        rows = robots.evaluate(state, [crawler("ChatGPT-User", "user")], ["/"])
        self.assertEqual(rows[0]["verdict"], "不定（429）")
        self.assertIn("RFC 9309 では全許可、Google はサーバーエラーとして扱いクロールを止める", rows[0]["note"])
        self.assertIn("ユーザー操作に伴う取得", rows[0]["note"])

    def test_user_note_uses_robots_control(self):
        # robots.txt の扱いは運営ごとに違うので、一律の文ではなく一覧の説明を添える
        state = {"state": "ok", "code": 200, "text": "User-agent: *\nAllow: /\n", "final_url": "", "detail": "",
                 "truncated": False}
        respects = dict(crawler("Claude-User", "user"), robots_control="制御できる（Anthropic は尊重すると説明）")
        ignores = dict(crawler("Perplexity-User", "user"), robots_control="一般に robots.txt を無視する（運営の説明）")
        blank = dict(crawler("X-User", "user"), robots_control="")
        rows = robots.evaluate(state, [respects, ignores, blank], ["/"])
        self.assertIn("Anthropic は尊重すると説明", rows[0]["note"])
        self.assertNotIn("無視", rows[0]["note"])
        self.assertIn("一般に robots.txt を無視する", rows[1]["note"])
        self.assertIn("運営ごとに違う", rows[2]["note"])

    def test_summary(self):
        rows = robots.evaluate(ok_state(self.ROBOTS), self.crawlers, ["/", "/private/"])
        lines = robots.summarize(rows, ["/", "/private/"])
        self.assertIn("学習: 1 件中 1 件が拒否", lines)
        self.assertIn("AI 検索・回答: 1 件中 0 件が拒否", lines)

    def test_summary_counts_rate_limited_as_unknown(self):
        state = {"state": "rate_limited", "code": 429, "text": "", "final_url": "", "detail": "ステータス 429",
                 "truncated": False}
        rows = robots.evaluate(state, self.crawlers, ["/"])
        lines = robots.summarize(rows, ["/"])
        self.assertIn("学習: 1 件中 0 件が拒否、1 件が不定", lines)
        self.assertIn("ユーザー操作に伴う取得: 1 件中 0 件が拒否、1 件が不定", lines)


class FallbackTokenTest(TempDirCase):
    """
    自分向けのグループがなければ、ほかのトークン（Googlebot）のグループに従うクローラー。
    Apple は「Applebot の記載がなく Googlebot の記載があれば Googlebot 向けの指示に従う」、
    Google は Google-CloudVertexBot のトークンを「Google-CloudVertexBot と Googlebot」と説明している。
    """
    GB_ONLY = "User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n"

    def load(self, text):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            crawlers = robots.load_crawlers(self.write("c.csv", text))
        return crawlers, err.getvalue()

    def test_builtin_fallback_when_column_absent(self):
        # 同梱の一覧（fallback_tokens の列がない）と同じ形
        crawlers, _ = self.load(HEADER + "Apple,Applebot,general-search,,,,,2026-09-26\n"
                                         "Google,Google-CloudVertexBot,other,,,,,2026-09-26\n"
                                         "Google,Googlebot,general-search,,,,,2026-09-26\n"
                                         "OpenAI,GPTBot,training,,,,,2026-09-26\n")
        rows = robots.evaluate(ok_state(self.GB_ONLY), crawlers, ["/"])
        for token in ("Applebot", "Google-CloudVertexBot"):
            with self.subTest(token=token):
                row = by_token(rows, token)
                self.assertEqual(row["verdict"], "許可")
                self.assertEqual(row["matched_group"], "User-agent: Googlebot")
                self.assertEqual(row["matched_rule"], "Allow: /")
                self.assertIn("{} 向けのグループがないため、Googlebot 向けのグループに従う（運営の説明）".format(token),
                              row["note"])
        gb = by_token(rows, "Googlebot")
        self.assertEqual((gb["verdict"], gb["matched_group"], gb["note"]), ("許可", "User-agent: Googlebot", ""))
        gpt = by_token(rows, "GPTBot")
        self.assertEqual((gpt["verdict"], gpt["matched_group"]), ("拒否", "User-agent: *"))

    def test_own_group_is_preferred(self):
        crawlers, _ = self.load(HEADER + "Apple,Applebot,general-search,,,,,2026-09-26\n")
        text = "User-agent: Applebot\nDisallow: /\n\n" + self.GB_ONLY
        row = robots.evaluate(ok_state(text), crawlers, ["/"])[0]
        self.assertEqual((row["verdict"], row["matched_group"], row["note"]), ("拒否", "User-agent: Applebot", ""))

    def test_star_when_no_fallback_group(self):
        crawlers, _ = self.load(HEADER + "Apple,Applebot,general-search,,,,,2026-09-26\n")
        row = robots.evaluate(ok_state("User-agent: *\nDisallow: /\n"), crawlers, ["/"])[0]
        self.assertEqual((row["verdict"], row["matched_group"], row["note"]), ("拒否", "User-agent: *", ""))

    def test_fallback_column_is_used_in_order(self):
        crawlers, _ = self.load(HEADER.rstrip("\n") + ",fallback_tokens\n"
                                "架空運営,KakuuBot,search,,,,,2026-09-26,SampleBot|Googlebot\n")
        row = robots.evaluate(ok_state(self.GB_ONLY), crawlers, ["/"])[0]
        self.assertEqual((row["verdict"], row["matched_group"]), ("許可", "User-agent: Googlebot"))
        text = "User-agent: SampleBot\nDisallow: /x\n\n" + self.GB_ONLY
        row = robots.evaluate(ok_state(text), crawlers, ["/x"])[0]
        self.assertEqual((row["verdict"], row["matched_group"]), ("拒否", "User-agent: SampleBot"))
        self.assertIn("KakuuBot 向けのグループがないため、SampleBot 向けのグループに従う", row["note"])

    def test_fallback_column_overrides_builtin(self):
        # 列があれば列の値が正本。Applebot の欄が空なら、Googlebot のグループには従わない
        crawlers, _ = self.load(HEADER.rstrip("\n") + ",fallback_tokens\n"
                                "Apple,Applebot,general-search,,,,,2026-09-26,\n")
        row = robots.evaluate(ok_state(self.GB_ONLY), crawlers, ["/"])[0]
        self.assertEqual((row["verdict"], row["matched_group"]), ("拒否", "User-agent: *"))

    def test_invalid_fallback_token_warns(self):
        crawlers, err = self.load(HEADER.rstrip("\n") + ",fallback_tokens\n"
                                  "架空運営,KakuuBot,search,,,,,2026-09-26,9Bot|kakuubot|Googlebot\n")
        self.assertIn("fallback_tokens の 9Bot", err)
        row = robots.evaluate(ok_state(self.GB_ONLY), crawlers, ["/"])[0]
        self.assertEqual(row["matched_group"], "User-agent: Googlebot")

    def test_star_inheritance_through_fallback(self):
        crawlers, _ = self.load(HEADER + "Apple,Applebot,general-search,,,,,2026-09-26\n"
                                         "Google,Googlebot,general-search,,,,,2026-09-26\n")
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: Googlebot\nAllow: /\n"
        self.assertEqual(robots.star_inheritance_warnings(robots.parse_robots(text), crawlers), [
            "Applebot が従う Googlebot 向けのグループがあるため、User-agent: * の Disallow: /admin/ は "
            "Applebot に適用されません",
            "Googlebot 向けのグループがあるため、User-agent: * の Disallow: /admin/ は Googlebot に適用されません",
        ])

    def test_bundled_list_cli(self):
        # レビューで報告された再現手順（同梱の data/ai-crawlers.csv を使う）
        path = self.write("gb.txt", self.GB_ONLY)
        result = helpers.run_script("ai_robots_check", ["--file", path, "--format", "csv"], cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {r["token"]: r for r in csv.DictReader(io.StringIO(result.stdout))}
        for token in ("Applebot", "Google-CloudVertexBot"):
            with self.subTest(token=token):
                self.assertEqual(rows[token]["verdict"], "許可")
                self.assertEqual(rows[token]["matched_group"], "User-agent: Googlebot")
                self.assertIn("Googlebot 向けのグループに従う", rows[token]["note"])
        self.assertEqual(rows["GPTBot"]["verdict"], "拒否")


class SearchBotFallbackNoteTest(TempDirCase):
    """
    Amazon は Amzn-SearchBot について「robots.txt に Amzn-SearchBot の記述がなく、ほかの検索ボットを許可している
    場合は、その指示に従う」と説明している。どのボットに従うかは説明がないので、判定は User-agent: * のまま
    にして、注記で知らせる。
    """
    CRAWLERS = (HEADER + "Google,Googlebot,general-search,,,,,2026-09-26\n"
                         "Amazon,Amzn-SearchBot,search,,,,,2026-09-26\n"
                         "OpenAI,GPTBot,training,,,,,2026-09-26\n")
    GB_ONLY = "User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n"

    def load(self, text=None):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            return robots.load_crawlers(self.write("c.csv", text or self.CRAWLERS))

    def test_note_when_another_search_bot_is_allowed(self):
        rows = robots.evaluate(ok_state(self.GB_ONLY), self.load(), ["/"])
        row = by_token(rows, "Amzn-SearchBot")
        self.assertEqual((row["verdict"], row["matched_group"]), ("拒否", "User-agent: *"))
        self.assertIn("ほかの検索ボットを許可していれば、その指示に従うことがある", row["note"])
        self.assertIn("Googlebot", row["note"])
        self.assertEqual(by_token(rows, "GPTBot")["note"], "")

    def test_no_note_with_own_group_or_without_allowed_search_bot(self):
        crawlers = self.load()
        text = "User-agent: Amzn-SearchBot\nDisallow: /\n\n" + self.GB_ONLY
        row = by_token(robots.evaluate(ok_state(text), crawlers, ["/"]), "Amzn-SearchBot")
        self.assertEqual((row["verdict"], row["note"]), ("拒否", ""))
        row = by_token(robots.evaluate(ok_state("User-agent: *\nDisallow: /\n"), crawlers, ["/"]), "Amzn-SearchBot")
        self.assertEqual((row["verdict"], row["note"]), ("拒否", ""))
        text = "User-agent: Googlebot\nDisallow: /\n\nUser-agent: *\nDisallow: /\n"
        row = by_token(robots.evaluate(ok_state(text), crawlers, ["/"]), "Amzn-SearchBot")
        self.assertEqual(row["note"], "")
        # 許可されているのが検索用でないボット（学習用）だけなら注記しない
        text = "User-agent: GPTBot\nAllow: /\n\nUser-agent: *\nDisallow: /\n"
        row = by_token(robots.evaluate(ok_state(text), crawlers, ["/"]), "Amzn-SearchBot")
        self.assertEqual(row["note"], "")

    def test_note_is_per_path(self):
        text = "User-agent: Googlebot\nDisallow: /private/\n\nUser-agent: *\nDisallow: /\n"
        rows = robots.evaluate(ok_state(text), self.load(), ["/", "/private/"])
        self.assertIn("Googlebot", by_token(rows, "Amzn-SearchBot", "/")["note"])
        self.assertEqual(by_token(rows, "Amzn-SearchBot", "/private/")["note"], "")

    def test_bundled_list_cli(self):
        path = self.write("gb.txt", self.GB_ONLY)
        result = helpers.run_script("ai_robots_check", ["--file", path, "--format", "csv"], cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {r["token"]: r for r in csv.DictReader(io.StringIO(result.stdout))}
        self.assertEqual(rows["Amzn-SearchBot"]["verdict"], "拒否")
        self.assertIn("ほかの検索ボット", rows["Amzn-SearchBot"]["note"])
        self.assertIn("Googlebot", rows["Amzn-SearchBot"]["note"])


class StarInheritanceTest(unittest.TestCase):
    def warnings(self, text, crawlers=None):
        return robots.star_inheritance_warnings(robots.parse_robots(text), crawlers or [crawler("GPTBot")])

    def test_warns_when_specific_group_lacks_star_disallow(self):
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nAllow: /\n"
        self.assertEqual(self.warnings(text), [
            "GPTBot 向けのグループがあるため、User-agent: * の Disallow: /admin/ は GPTBot に適用されません"])

    def test_no_warning_when_same_disallow_exists(self):
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nAllow: /\nDisallow: /admin/\n"
        self.assertEqual(self.warnings(text), [])

    def test_no_warning_without_specific_group(self):
        text = "User-agent: *\nDisallow: /admin/\n"
        self.assertEqual(self.warnings(text), [])

    def test_no_warning_when_crawler_blocked_everywhere(self):
        # GPTBot のグループの Disallow: / が /admin/ も覆っているので、警告しても意味がない
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nDisallow: /\n"
        self.assertEqual(self.warnings(text), [])

    def test_anchored_disallow_does_not_suppress(self):
        # GPTBot の Disallow: /admin/$ は /admin/ そのものにしか当たらない。/admin/x は GPTBot に開いているので警告する
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nDisallow: /admin/$\n"
        rows = robots.evaluate(ok_state(text), [crawler("GPTBot")], ["/admin/x"])
        self.assertEqual(rows[0]["verdict"], "許可")
        self.assertEqual(self.warnings(text), [
            "GPTBot 向けのグループがあるため、User-agent: * の Disallow: /admin/ は GPTBot に適用されません"])

    def test_longer_allow_does_not_suppress(self):
        # GPTBot は /admin/public/ だけ開いている。* では拒否される範囲が開くので警告する
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nDisallow: /admin/\nAllow: /admin/public/\n"
        self.assertEqual(len(self.warnings(text)), 1)

    def test_shorter_allow_does_not_matter(self):
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nAllow: /ad\nDisallow: /admin\n"
        self.assertEqual(self.warnings(text), [])

    def test_exact_allow_outside_range_does_not_matter(self):
        # トップページだけを許可する書き方。Allow: /$ は / にしか当たらないので、/admin/ の範囲は GPTBot でも拒否
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nDisallow: /\nAllow: /$\n"
        self.assertEqual(self.warnings(text), [])
        # * の側が / そのものを拒否しているなら、GPTBot には開いているので警告する
        text = "User-agent: *\nDisallow: /$\n\nUser-agent: GPTBot\nDisallow: /\nAllow: /$\n"
        self.assertEqual(len(self.warnings(text)), 1)
        # * を含む Allow は当たる範囲を絞れないので、重なりうるなら警告する（/admin/x.css は GPTBot に開いている）
        text = "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nDisallow: /\nAllow: /*.css$\n"
        self.assertEqual(len(self.warnings(text)), 1)

    def test_covered_patterns(self):
        cases = [
            # * の側が $ 付きでも、GPTBot の側の接頭辞で覆われていれば警告しない
            "User-agent: *\nDisallow: /*.php$\n\nUser-agent: GPTBot\nDisallow: /\n",
            "User-agent: *\nDisallow: /admin/$\n\nUser-agent: GPTBot\nDisallow: /admin/$\n",
            "User-agent: *\nDisallow: /admin*\n\nUser-agent: GPTBot\nDisallow: /admin\n",
            # GPTBot の側の * 付きのパターンでも、* の側の固定の接頭辞を覆っていれば警告しない
            "User-agent: *\nDisallow: /shop/cart/\n\nUser-agent: GPTBot\nDisallow: /*/cart/\n",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.warnings(text), [])

    def test_uncovered_patterns(self):
        cases = [
            # GPTBot の側が * の側より狭い
            "User-agent: *\nDisallow: /admin\n\nUser-agent: GPTBot\nDisallow: /admin/\n",
            "User-agent: *\nDisallow: /*.php\n\nUser-agent: GPTBot\nDisallow: /a\n",
            "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nDisallow: /admin/$\nDisallow: /other/\n",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(len(self.warnings(text)), 1)

    def test_multiple_disallows_joined(self):
        text = "User-agent: *\nDisallow: /admin/\nDisallow: /tmp/\n\nUser-agent: GPTBot\nDisallow: /tmp/\n\n" \
               "User-agent: CCBot\nAllow: /\n"
        got = self.warnings(text, [crawler("GPTBot"), crawler("CCBot", "dataset"), crawler("OAI-SearchBot")])
        self.assertEqual(got, [
            "GPTBot 向けのグループがあるため、User-agent: * の Disallow: /admin/ は GPTBot に適用されません",
            "CCBot 向けのグループがあるため、User-agent: * の Disallow: /admin/, /tmp/ は CCBot に適用されません",
        ])


class DecodeTest(TempDirCase):
    """Review Focus 5: BOM 付き、Shift_JIS のコメントを含む robots.txt。"""

    def test_bom(self):
        path = self.write("robots.txt", codecs.BOM_UTF8 + b"User-agent: GPTBot\r\nDisallow: /\r\n")
        state = robots.read_robots_file(path)
        self.assertEqual(state["state"], "ok")
        rows = robots.evaluate(state, [crawler("GPTBot")], ["/"])
        self.assertEqual(rows[0]["verdict"], "拒否")

    def test_shift_jis_comments(self):
        text = ("# 架空珈琲のロボットの設定（Shift_JIS で保存）\n"
                "User-agent: GPTBot\nDisallow: /private/ # 非公開のページ\n\n"
                "# 学習用のクロールは拒否する\nUser-agent: CCBot\nDisallow: /\n")
        path = self.write("robots.txt", text.encode("cp932"))
        state = robots.read_robots_file(path)
        self.assertTrue(state["replaced"])
        rows = robots.evaluate(state, [crawler("GPTBot"), crawler("CCBot", "dataset")], ["/", "/private/a"])
        self.assertEqual(by_token(rows, "GPTBot", "/")["verdict"], "許可")
        self.assertEqual(by_token(rows, "GPTBot", "/private/a")["verdict"], "拒否")
        self.assertEqual(by_token(rows, "CCBot", "/")["verdict"], "拒否")

    def plain_warnings(self, state):
        return robots.collect_warnings(state, [crawler("GPTBot")], None)[0]

    def test_utf16_file_warns(self):
        # Windows のメモ帳の「Unicode」（UTF-16 LE、BOM 付き）と、BOM のない UTF-16 LE・BE
        text = "User-agent: GPTBot\r\nDisallow: /\r\n"
        for name, data in (("bom", text.encode("utf-16")), ("le", text.encode("utf-16-le")),
                           ("be", text.encode("utf-16-be"))):
            with self.subTest(name=name):
                state = robots.read_robots_file(self.write(name + ".txt", data))
                self.assertTrue(state["utf16"])
                self.assertEqual(robots.robots_groups(state), [])
                warnings = self.plain_warnings(state)
                self.assertTrue(any("UTF-16 で保存されているため、どの行も読めませんでした" in w for w in warnings),
                                warnings)
                self.assertFalse(any("コメントの中だけなら" in w for w in warnings), warnings)

    def test_utf8_file_is_not_utf16(self):
        state = robots.read_robots_file(self.write("robots.txt", "User-agent: GPTBot\nDisallow: /\n"))
        self.assertFalse(state["utf16"])
        self.assertEqual(self.plain_warnings(state), [])

    def test_undecodable_without_groups(self):
        # UTF-8 として読めない文字があり、グループが1つもない。Shift_JIS のコメント向けの文は出さない
        path = self.write("robots.txt", "# 架空珈琲の設定\n# すべて許可\n".encode("cp932"))
        state = robots.read_robots_file(path)
        warnings = self.plain_warnings(state)
        self.assertTrue(any("グループが1つもありません" in w for w in warnings), warnings)
        self.assertFalse(any("コメントの中だけなら" in w for w in warnings), warnings)

    def test_decode_truncates_at_last_newline(self):
        data = b"User-agent: *\n" + b"Disallow: /abcdefghij\n" * 30000
        text, truncated, replaced = robots.decode_robots(data)
        self.assertTrue(truncated)
        self.assertFalse(replaced)
        self.assertLessEqual(len(text.encode("utf-8")), LIMIT)
        for line in text.split("\n"):
            self.assertIn(line, ("User-agent: *", "Disallow: /abcdefghij", ""))

    def test_missing_file(self):
        with self.assertRaises(robots.InputError):
            robots.read_robots_file(os.path.join(self.tmp, "nothing.txt"))


class OriginTest(unittest.TestCase):
    def test_origin(self):
        self.assertEqual(robots.origin_of("https://Kakuu-Coffee.example/blog/?x=1"), "https://kakuu-coffee.example")
        self.assertEqual(robots.origin_of("http://kakuu-coffee.example:8080"), "http://kakuu-coffee.example:8080")
        self.assertEqual(robots.origin_of("https://[::1]:8443/x"), "https://[::1]:8443")

    def test_rejects(self):
        for url in ("ftp://kakuu-coffee.example/", "kakuu-coffee.example", "https://user:pass@kakuu-coffee.example/",
                    "https://kakuu-coffee.example:99999/", "https:///path", ""):
            with self.subTest(url=url):
                with self.assertRaises(robots.InputError):
                    robots.origin_of(url)

    def test_rejects_malformed_host(self):
        # 空のラベル・64 文字以上のラベル・253 文字を超えるホスト名は、名前解決に進まず入力の誤りにする
        # （以前は IDNA の変換の UnicodeError が「取得できず（全拒否）」になり、終了コード 0 で全拒否の表が出た）
        long_host = ".".join(["a" * 60] * 5)  # 304 文字
        for url in ("https://example..com", "https://.example.com", "https://www.example.com..",
                    "https://" + "a" * 64 + ".com", "https://" + long_host, "https://日本..jp"):
            with self.subTest(url=url):
                with self.assertRaises(robots.InputError) as ctx:
                    robots.origin_of(url)
                self.assertIn("ホスト名", str(ctx.exception))

    def test_accepts_valid_host_shapes(self):
        # 末尾の . が1つの FQDN と、63 文字のラベルは有効
        self.assertEqual(robots.origin_of("https://kakuu-coffee.example."), "https://kakuu-coffee.example.")
        host = "a" * 63 + ".example"
        self.assertEqual(robots.origin_of("https://" + host), "https://" + host)
        self.assertEqual(robots.origin_of("https://日本.example/"), "https://xn--wgv71a.example")

    def test_rejects_idna_deviation_characters(self):
        # IDNA 2003（Python 標準の idna）と IDNA 2008 で変換の結果が違う文字（ß ς ZWJ ZWNJ）を含むホスト名は、
        # 黙って別のホスト（faß.de → fass.de）を取得しないよう、入力の誤りにする
        for url in ("https://faß.de", "https://FAẞ.de", "https://βόλος.com", "https://a‍b.example",
                    "https://a‌b.example"):
            with self.subTest(url=url):
                with self.assertRaises(robots.InputError) as ctx:
                    robots.origin_of(url)
                self.assertIn("IDNA", str(ctx.exception))
        # Punycode の表記なら取得できる
        self.assertEqual(robots.origin_of("https://xn--fa-hia.de"), "https://xn--fa-hia.de")

    def test_userinfo_not_shown_in_messages(self):
        # スキームのない入力や、// のない入力に含まれるパスワードも、エラーの文に出さない
        for url in ("user:secret@kakuu-coffee.example", "https:user:secret@kakuu-coffee.example",
                    "ftp://user:secret@kakuu-coffee.example/", "https://user:secret@kakuu-coffee.example:99999/"):
            with self.subTest(url=url):
                with self.assertRaises(robots.InputError) as ctx:
                    robots.origin_of(url)
                self.assertNotIn("secret", str(ctx.exception))


class RedirectTargetTest(unittest.TestCase):
    def test_utf8_location_is_read_as_utf8(self):
        # http.client はヘッダーを latin-1 で読む。UTF-8 のままの Location を UTF-8 として読み直す
        raw = "/日本/robots.txt".encode("utf-8").decode("latin-1")
        target, problem = robots._redirect_target("http://kakuu-coffee.example/robots.txt", raw)
        self.assertEqual(problem, "")
        self.assertEqual(target, "http://kakuu-coffee.example/%E6%97%A5%E6%9C%AC/robots.txt")

    def test_japanese_host(self):
        raw = "https://日本.example/robots.txt".encode("utf-8").decode("latin-1")
        target, problem = robots._redirect_target("http://kakuu-coffee.example/robots.txt", raw)
        self.assertEqual((target, problem), ("https://xn--wgv71a.example/robots.txt", ""))

    def test_latin1_location_kept(self):
        # UTF-8 として読めない Location（latin-1 の é）は、そのまま UTF-8 の %XX にする
        target, _ = robots._redirect_target("http://kakuu-coffee.example/robots.txt", "/caf\xe9/robots.txt")
        self.assertEqual(target, "http://kakuu-coffee.example/caf%C3%A9/robots.txt")

    def test_ascii_location_unchanged(self):
        target, _ = robots._redirect_target("http://kakuu-coffee.example/robots.txt",
                                            "https://sample-roast.example:8443/a%20b/robots.txt?x=1#frag")
        self.assertEqual(target, "https://sample-roast.example:8443/a%20b/robots.txt?x=1")

    def test_bad_port(self):
        target, problem = robots._redirect_target("http://kakuu-coffee.example/robots.txt",
                                                  "http://kakuu-coffee.example:99999/robots.txt")
        self.assertIsNone(target)
        self.assertIn("解釈できない", problem)

    def test_idna_deviation_host(self):
        # ß を含むリダイレクト先は、IDNA 2003 で fass.de に変えて取得せず、たどれないものとする
        raw = "https://faß.de/robots.txt".encode("utf-8").decode("latin-1")
        target, problem = robots._redirect_target("http://kakuu-coffee.example/robots.txt", raw)
        self.assertIsNone(target)
        self.assertIn("IDNA", problem)

    def test_malformed_host(self):
        for location in ("http://a..example/robots.txt", "http://" + "a" * 64 + ".example/robots.txt"):
            with self.subTest(location=location):
                target, problem = robots._redirect_target("http://kakuu-coffee.example/robots.txt", location)
                self.assertIsNone(target)
                self.assertIn("ホスト名", problem)


# ---------------------------------------------------------------------------
# 取得（ローカルのテスト用サーバー）
# ---------------------------------------------------------------------------

ROBOTS_BODY = b"User-agent: GPTBot\nDisallow: /\n"
BIG_BODY = b"User-agent: *\n" + b"Disallow: /page-abcdefghij\n" * 25000  # 約 650 KiB


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", location=None):
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        server = self.server
        server.requests.append((self.path, self.headers.get("User-Agent")))
        mode = server.mode
        try:
            if mode == "ok":
                self._send(200, ROBOTS_BODY)
            elif mode in ("missing", "rate", "error", "unavailable"):
                self._send({"missing": 404, "rate": 429, "error": 500, "unavailable": 503}[mode])
            elif mode == "to-japanese":
                # UTF-8 のままの Location（send_header は latin-1 で書くので、UTF-8 のバイト列を latin-1 の文字にして渡す）
                if self.path == "/robots.txt":
                    self._send(301, location="/日本/robots.txt".encode("utf-8").decode("latin-1"))
                elif self.path == "/%E6%97%A5%E6%9C%AC/robots.txt":
                    self._send(200, ROBOTS_BODY)
                else:
                    self._send(404)
            elif mode == "to-nxdomain":
                self._send(301, location="http://nxdomain.kakuu-coffee.example:{}/robots.txt".format(
                    server.server_address[1]))
            elif mode == "redirect":
                if self.path == "/robots.txt":
                    self._send(301, location="/moved/robots.txt")
                else:
                    self._send(200, ROBOTS_BODY)
            elif mode in ("redirect5", "redirect6"):
                # redirect5: 5回のリダイレクトのあとに 200。redirect6: 6回のリダイレクト
                limit = 5 if mode == "redirect5" else 6
                step = 0 if self.path == "/robots.txt" else int(self.path.rsplit("/", 1)[-1])
                if step < limit:
                    self._send(301, location="/hop/{}".format(step + 1))
                else:
                    self._send(200, ROBOTS_BODY)
            elif mode == "slow":
                time.sleep(2)
                self._send(200, ROBOTS_BODY)
            elif mode == "big":
                self._send(200, BIG_BODY)
            elif mode == "no-location":
                self._send(302)
            elif mode == "to-ftp":
                self._send(301, location="ftp://kakuu-coffee.example/robots.txt")
            elif mode == "to-internal":
                server.flags["redirected"] = True
                self._send(301, location="http://127.0.0.1:{}/robots.txt".format(server.server_address[1]))
            else:
                self._send(500)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False  # 待たせる応答のスレッドの終わりを待たない

    def handle_error(self, request, client_address):
        pass


MODES = ("ok", "missing", "rate", "error", "unavailable", "redirect", "redirect5", "redirect6", "slow", "big",
         "no-location", "to-ftp", "to-internal", "to-japanese", "to-nxdomain")


class _PlainTextTLSPeer(object):
    """
    TLS で話しかけられても、平文の HTTP の応答を返すだけのサーバー（https で平文のサーバーにつないだ場合の再現）。
    http.server は ClientHello に改行がないと読み続けて待つので、受け取った量に関係なくすぐに応答を返す。
    """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.stopped.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.accepted += 1
            try:
                conn.settimeout(2)
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                conn.shutdown(socket.SHUT_WR)
                while conn.recv(65536):  # 相手が閉じるまで読み捨てる（未読のまま閉じると RST になる）
                    pass
            except OSError:
                pass
            finally:
                conn.close()

    def close(self):
        self.stopped.set()
        self.sock.close()
        self.thread.join(2)


class _RawPeer(object):
    """
    リクエストを読んだあと、respond(conn, path, stopped) で決まったバイト列を返すだけのサーバー。
    http.server では送れない応答（1xx の中間の応答、1バイトずつの送信）を再現する。接続ごとにスレッドを立てる。
    """

    def __init__(self, respond):
        self.respond = respond
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def url(self):
        return "http://127.0.0.1:{}".format(self.port)

    def _serve(self):
        while not self.stopped.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            conn.settimeout(10)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            path = data.split(b" ", 2)[1].decode("latin-1")
            self.respond(conn, path, self.stopped)
        except OSError:  # 取得する側が接続を切った
            pass
        finally:
            conn.close()

    def close(self):
        self.stopped.set()
        self.sock.close()
        self.thread.join(2)


def _drip(data, interval):
    """data を interval 秒ごとに1バイトずつ送る応答（1回の操作のタイムアウトより短い間隔で送り続けるサーバー）。"""
    def respond(conn, path, stopped):
        for i in range(len(data)):
            if stopped.is_set():
                return
            conn.sendall(data[i:i + 1])
            time.sleep(interval)
    return respond


def _ok_response(body=ROBOTS_BODY):
    return (b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: " + str(len(body)).encode("ascii")
            + b"\r\nConnection: close\r\n\r\n" + body)


def _gaierror(code_name, message):
    return socket.gaierror(getattr(socket, code_name), message)


class FetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers = {}
        for mode in MODES:
            server = _Server(("127.0.0.1", 0), _Handler)
            server.mode = mode
            server.requests = []
            server.flags = {}
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.servers[mode] = server
        cls.tls_peer = _PlainTextTLSPeer()

    @classmethod
    def tearDownClass(cls):
        for server in cls.servers.values():
            server.shutdown()
            server.server_close()
        cls.tls_peer.close()

    def patched_dns(self, table):
        """table: ホスト名 → 返すアドレスか、送出する例外。ほかのホストは本物の getaddrinfo に任せる。"""
        real_getaddrinfo = socket.getaddrinfo

        def fake_getaddrinfo(host, port_, *args, **kwargs):
            if host in table:
                value = table[host]
                if isinstance(value, BaseException):
                    raise value
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, port_))]
            return real_getaddrinfo(host, port_, *args, **kwargs)

        return mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo)

    def origin(self, mode, host="127.0.0.1"):
        return "http://{}:{}".format(host, self.servers[mode].server_address[1])

    def fetch(self, mode, timeout=0.5):
        return robots.fetch_robots(self.origin(mode), timeout, True)

    def test_ok(self):
        state = self.fetch("ok", timeout=5)
        self.assertEqual(state["state"], "ok")
        self.assertEqual(state["code"], 200)
        self.assertEqual(state["text"], ROBOTS_BODY.decode("utf-8"))
        self.assertFalse(state["truncated"])
        self.assertTrue(state["final_url"].endswith("/robots.txt"))
        path, ua = self.servers["ok"].requests[-1]
        self.assertEqual(path, "/robots.txt")
        # 仕様（設計書 7.5）の文字列と比べる。AI クローラーの UA は名乗らない
        self.assertEqual(ua, "ai-search-operator/{} (+https://github.com/indiabiyori/ai-search-operator)".format(
            common.VERSION))

    def test_missing(self):
        state = self.fetch("missing", timeout=5)
        self.assertEqual((state["state"], state["code"]), ("missing", 404))

    def test_rate_limited(self):
        state = self.fetch("rate", timeout=5)
        self.assertEqual((state["state"], state["code"]), ("rate_limited", 429))

    def test_server_error(self):
        state = self.fetch("error", timeout=5)
        self.assertEqual((state["state"], state["code"]), ("unreachable", 500))

    def test_redirect_then_ok(self):
        state = self.fetch("redirect", timeout=5)
        self.assertEqual(state["state"], "ok")
        self.assertTrue(state["final_url"].endswith("/moved/robots.txt"))

    def test_five_redirects_followed(self):
        state = self.fetch("redirect5", timeout=5)
        self.assertEqual(state["state"], "ok")
        self.assertTrue(state["final_url"].endswith("/hop/5"))

    def test_redirect_without_location(self):
        state = self.fetch("no-location", timeout=5)
        self.assertEqual((state["state"], state["code"]), ("unreachable", 302))
        self.assertIn("Location", state["detail"])

    def test_redirect_to_other_scheme(self):
        state = self.fetch("to-ftp", timeout=5)
        self.assertEqual(state["state"], "unreachable")
        self.assertIn("http / https 以外", state["detail"])

    def test_too_many_redirects(self):
        # RFC 9309 2.3.1.2: 5回を超えるリダイレクトは unavailable（2.3.1.3、全許可）とみなしてよい。
        # Google も 404 として扱う。計画の「全拒否」から変えた（notes に記載）
        state = self.fetch("redirect6", timeout=5)
        self.assertEqual(state["state"], "missing")
        self.assertIn("リダイレクトが多すぎる", state["detail"])
        self.assertEqual(len(self.servers["redirect6"].requests), 6)
        # 判定の行にも、全許可にした根拠（RFC の節と Google の扱い）が出る
        row = robots.evaluate(state, [crawler("GPTBot")], ["/"])[0]
        self.assertEqual(row["verdict"], "全許可（robots.txt なし）")
        self.assertIn("RFC 9309 2.3.1.2", row["note"])
        self.assertIn("Google も 404 として扱う", row["note"])

    def test_redirect_to_japanese_path(self):
        server = self.servers["to-japanese"]
        state = self.fetch("to-japanese", timeout=5)
        self.assertEqual(state["state"], "ok", state["detail"])
        self.assertTrue(state["final_url"].endswith("/%E6%97%A5%E6%9C%AC/robots.txt"), state["final_url"])
        self.assertEqual([p for p, _ in server.requests[-2:]], ["/robots.txt", "/%E6%97%A5%E6%9C%AC/robots.txt"])

    def test_https_to_plain_server_is_tls_error(self):
        # https で平文のサーバーにつなぐと TLS のエラーになり、全拒否（取得できず）として扱う。
        # allow_private=False の経路（接続先を確かめてからつなぐ）でも同じ
        port = self.tls_peer.port
        with self.subTest(allow_private=True):
            state = robots.fetch_robots("https://127.0.0.1:{}".format(port), 5, True)
            self.assertEqual(state["state"], "unreachable")
            self.assertIn("TLS のエラー", state["detail"])
            self.assertIsNone(state["code"])
        with self.subTest(allow_private=False):
            before = self.tls_peer.accepted
            with self.patched_dns({"tls.kakuu-coffee.example": "127.0.0.1"}), \
                    mock.patch.object(robots, "internal_address", lambda address: False):
                state = robots.fetch_robots("https://tls.kakuu-coffee.example:{}".format(port), 5, False)
            self.assertEqual(state["state"], "unreachable")
            self.assertIn("TLS のエラー", state["detail"])
            self.assertGreater(self.tls_peer.accepted, before)

    def test_https_dns_change_before_connect_rejected(self):
        # https でも、接続の直前の名前解決で内部アドレスに変わったら、TCP の接続の前に止める
        port = self.tls_peer.port
        before = self.tls_peer.accepted
        calls = []
        real_getaddrinfo = socket.getaddrinfo
        real_internal = robots.internal_address

        def fake_getaddrinfo(host, port_, *args, **kwargs):
            if host == "rebind-tls.kakuu-coffee.example":
                calls.append(host)
                address = "192.0.2.10" if len(calls) == 1 else "127.0.0.1"
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port_))]
            return real_getaddrinfo(host, port_, *args, **kwargs)

        def fake_internal(address):
            return address != "192.0.2.10" and real_internal(address)

        with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo), \
                mock.patch.object(robots, "internal_address", fake_internal):
            with self.assertRaises(robots.InputError) as ctx:
                robots.fetch_robots("https://rebind-tls.kakuu-coffee.example:{}".format(port), 5, False)
        self.assertIn("127.0.0.1", str(ctx.exception))
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(self.tls_peer.accepted, before)

    def test_first_host_not_found_is_input_error(self):
        # 最初の URL のホストが存在しない（打ち間違いなど）ときは、全拒否の表を出さずに終了コード 2 で止める
        nx = _gaierror("EAI_NONAME", "nodename nor servname provided, or not known")
        for allow_private in (True, False):
            with self.subTest(allow_private=allow_private):
                with self.patched_dns({"typo.kakuu-coffee.example": nx}):
                    with self.assertRaises(robots.InputError) as ctx:
                        robots.fetch_robots("https://typo.kakuu-coffee.example", 5, allow_private)
                self.assertIn("typo.kakuu-coffee.example", str(ctx.exception))
                self.assertIn("ホスト名", str(ctx.exception))
                # macOS はネットワークにつながっていないときも EAI_NONAME を返すので、その可能性も添える
                self.assertIn("ネットワーク", str(ctx.exception))

    def test_first_host_temporary_failure_is_unreachable(self):
        again = _gaierror("EAI_AGAIN", "temporary failure in name resolution")
        with self.patched_dns({"flaky.kakuu-coffee.example": again}):
            state = robots.fetch_robots("http://flaky.kakuu-coffee.example", 5, True)
        self.assertEqual(state["state"], "unreachable")
        self.assertIn("名前解決できない", state["detail"])

    def test_redirect_target_not_found_is_unreachable(self):
        nx = _gaierror("EAI_NONAME", "nodename nor servname provided, or not known")
        with self.patched_dns({"nxdomain.kakuu-coffee.example": nx}):
            state = self.fetch("to-nxdomain", timeout=5)
        self.assertEqual(state["state"], "unreachable")
        self.assertIn("名前解決できない", state["detail"])

    def test_timeout(self):
        t0 = time.monotonic()
        state = self.fetch("slow", timeout=0.5)
        self.assertEqual(state["state"], "unreachable")
        self.assertIn("タイムアウト", state["detail"])
        self.assertLess(time.monotonic() - t0, 1.8)

    def test_connection_refused(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()  # 誰も待ち受けていないポート
        state = robots.fetch_robots("http://127.0.0.1:{}".format(port), 1.0, True)
        self.assertEqual(state["state"], "unreachable")
        self.assertIsNone(state["code"])

    def test_truncated(self):
        state = self.fetch("big", timeout=5)
        self.assertEqual(state["state"], "ok")
        self.assertTrue(state["truncated"])
        self.assertLessEqual(len(state["text"].encode("utf-8")), LIMIT)
        self.assertTrue(state["text"].endswith("Disallow: /page-abcdefghij"))
        for line in state["text"].split("\n"):
            self.assertIn(line, ("User-agent: *", "Disallow: /page-abcdefghij", ""))

    def test_environment_proxy_is_ignored(self):
        env = {"HTTP_PROXY": "http://proxy.invalid:3128", "http_proxy": "http://proxy.invalid:3128",
               "HTTPS_PROXY": "http://proxy.invalid:3128", "https_proxy": "http://proxy.invalid:3128",
               "NO_PROXY": "", "no_proxy": ""}
        with mock.patch.dict(os.environ, env):
            state = self.fetch("ok", timeout=5)
        self.assertEqual(state["state"], "ok")

    def test_private_address_rejected(self):
        with self.assertRaises(robots.InputError) as ctx:
            robots.fetch_robots(self.origin("ok"), 5, False)
        self.assertIn("--allow-private", str(ctx.exception))

    def test_special_purpose_address_rejected_with_old_is_private(self):
        # 名前解決の結果が 6to4 に内部の IPv4 を埋め込んだアドレスや 192.0.0.0/24 のとき、ipaddress の is_private が
        # 古い表（macOS の /usr/bin/python3 の 3.9.6 など。パッチの前）でも、取得に進まず入力の誤りにする
        table = {"sixtofour.kakuu-coffee.example": "2002:a00:1::1",
                 "loop6to4.kakuu-coffee.example": "2002:7f00:1::1",
                 "ietf.kakuu-coffee.example": "192.0.0.100"}
        with mock.patch.object(ipaddress.IPv4Address, "is_private", new_callable=mock.PropertyMock,
                               return_value=False), \
                mock.patch.object(ipaddress.IPv6Address, "is_private", new_callable=mock.PropertyMock,
                                  return_value=False), \
                self.patched_dns(table):
            for host, address in table.items():
                with self.subTest(host=host):
                    with self.assertRaises(robots.PrivateAddressBlocked) as ctx:
                        robots.fetch_robots("http://{}".format(host), 5, False)
                    self.assertIn(address, str(ctx.exception))
                    self.assertIn("--allow-private", str(ctx.exception))

    def test_redirect_to_internal_address_rejected(self):
        # 1段目のホストは公開アドレスとして扱い（mock）、実際にはローカルのサーバーにつなぐ。
        # サーバーが 127.0.0.1 へのリダイレクトを返したあとは、internal_address を本来の判定に戻す
        server = self.servers["to-internal"]
        port = server.server_address[1]
        real_getaddrinfo = socket.getaddrinfo
        real_internal = robots.internal_address

        def fake_getaddrinfo(host, port_, *args, **kwargs):
            if host == "public.kakuu-coffee.example":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port_))]
            return real_getaddrinfo(host, port_, *args, **kwargs)

        def fake_internal(address):
            return bool(server.flags.get("redirected")) and real_internal(address)

        with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo), \
                mock.patch.object(robots, "internal_address", fake_internal):
            with self.assertRaises(robots.InputError) as ctx:
                robots.fetch_robots("http://public.kakuu-coffee.example:{}".format(port), 5, False)
        self.assertTrue(server.flags.get("redirected"))
        self.assertIn("リダイレクト先", str(ctx.exception))
        self.assertIn("127.0.0.1", str(ctx.exception))

    def test_dns_change_before_connect_rejected(self):
        # 取得前の確認では公開アドレス、接続のときには 127.0.0.1 を返す（DNS の答えが途中で変わる）
        server = self.servers["ok"]
        port = server.server_address[1]
        before = len(server.requests)
        calls = []
        real_getaddrinfo = socket.getaddrinfo
        real_internal = robots.internal_address

        def fake_getaddrinfo(host, port_, *args, **kwargs):
            if host == "rebind.kakuu-coffee.example":
                calls.append(host)
                address = "192.0.2.10" if len(calls) == 1 else "127.0.0.1"
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port_))]
            return real_getaddrinfo(host, port_, *args, **kwargs)

        def fake_internal(address):
            return address != "192.0.2.10" and real_internal(address)

        with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo), \
                mock.patch.object(robots, "internal_address", fake_internal):
            with self.assertRaises(robots.InputError):
                robots.fetch_robots("http://rebind.kakuu-coffee.example:{}".format(port), 5, False)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(len(server.requests), before)  # リクエストは届いていない

    def test_userinfo_rejected(self):
        with self.assertRaises(robots.InputError):
            robots.fetch_robots("http://user:pass@127.0.0.1:{}".format(self.servers["ok"].server_address[1]),
                                5, True)

    def test_main_with_url(self):
        result = helpers.run_script("ai_robots_check", [
            "--url", self.origin("ok") + "/blog/", "--allow-private", "--crawlers", CRAWLERS_CSV,
            "--paths", "/,/blog/"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# AI クローラーの robots.txt 判定", result.stdout)
        self.assertIn("| OpenAI | GPTBot | 学習 | / | 拒否 |", result.stdout)

    def test_main_private_without_flag(self):
        result = helpers.run_script("ai_robots_check", [
            "--url", self.origin("ok"), "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--allow-private", result.stderr)

    def test_main_markdown_for_unreachable_and_rate_limited(self):
        # Markdown の「取得の結果」に、扱いの根拠と各社の違いを書く（仕様 7.5 の文を直接比べる）
        result = helpers.run_script("ai_robots_check", [
            "--url", self.origin("unavailable"), "--allow-private", "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- ステータス: 503", result.stdout)
        self.assertIn("RFC 9309 に従って全拒否として扱った。各社の実際の扱いは異なりうる", result.stdout)
        self.assertIn("| OpenAI | GPTBot | 学習 | / | 全拒否（取得できず） |", result.stdout)
        self.assertIn("学習: 1 件中 1 件が拒否", result.stdout)

        result = helpers.run_script("ai_robots_check", [
            "--url", self.origin("rate"), "--allow-private", "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- ステータス: 429", result.stdout)
        self.assertIn("RFC 9309 では 4xx の一つとして全許可、Google はサーバーエラーとして扱いクロールを止める",
                      result.stdout)
        self.assertIn("| OpenAI | GPTBot | 学習 | / | 不定（429） |", result.stdout)
        self.assertIn("学習: 1 件中 0 件が拒否、1 件が不定", result.stdout)

    def test_main_first_host_not_found(self):
        # 実際の名前解決に頼らないよう、同じプロセスで main を呼ぶ
        nx = _gaierror("EAI_NONAME", "nodename nor servname provided, or not known")
        with self.patched_dns({"typo.kakuu-coffee.example": nx}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = robots.main(["--url", "https://typo.kakuu-coffee.example", "--crawlers", CRAWLERS_CSV])
        self.assertEqual(code, 2, err.getvalue())
        self.assertEqual(out.getvalue(), "")
        self.assertIn("typo.kakuu-coffee.example", err.getvalue())

    # --- 名前はあるがアドレスがない（EAI_NODATA） ---

    @unittest.skipUnless(hasattr(socket, "EAI_NODATA"), "この環境の socket に EAI_NODATA がない")
    def test_first_host_without_address_is_input_error(self):
        # Linux の glibc は、名前はあるがアドレスのレコードがない（apex に A レコードがない）と EAI_NODATA を返す。
        # 打ち間違いと同じく、全拒否の表を出さずに終了コード 2 で止める
        nodata = _gaierror("EAI_NODATA", "No address associated with hostname")
        for allow_private in (True, False):
            with self.subTest(allow_private=allow_private):
                with self.patched_dns({"apex.kakuu-coffee.example": nodata}):
                    with self.assertRaises(robots.InputError) as ctx:
                        robots.fetch_robots("https://apex.kakuu-coffee.example", 5, allow_private)
                self.assertIn("apex.kakuu-coffee.example の名前解決ができません", str(ctx.exception))
        with self.patched_dns({"apex.kakuu-coffee.example": nodata}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = robots.main(["--url", "https://apex.kakuu-coffee.example", "--crawlers", CRAWLERS_CSV])
        self.assertEqual(code, 2, err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_name_not_found_without_nodata_constant(self):
        # EAI_NODATA のない環境（定数が定義されていない）でも落ちず、EAI_NONAME は今までどおり見つからない扱い
        saved = getattr(socket, "EAI_NODATA", None)
        if saved is not None:
            del socket.EAI_NODATA
        try:
            self.assertTrue(robots._name_not_found(_gaierror("EAI_NONAME", "not known")))
            self.assertFalse(robots._name_not_found(_gaierror("EAI_AGAIN", "temporary failure")))
            self.assertFalse(robots._name_not_found(socket.gaierror(-12345, "other")))
        finally:
            if saved is not None:
                socket.EAI_NODATA = saved

    # --- 取得全体の締め切り ---

    def test_total_timeout(self):
        # 取得全体の締め切りは --timeout の 3 倍か 30 秒の長いほう
        self.assertEqual(robots.total_timeout(1.0), 30.0)
        self.assertEqual(robots.total_timeout(10.0), 30.0)
        self.assertEqual(robots.total_timeout(20.0), 60.0)
        self.assertEqual(robots.total_timeout(600.0), 1800.0)

    def drip_fetch(self, respond, timeout=0.5):
        """1回の操作のタイムアウトより短い間隔で送り続けるサーバーから取得する（締め切りは timeout の 3 倍）。"""
        peer = _RawPeer(respond)
        self.addCleanup(peer.close)
        t0 = time.monotonic()
        with mock.patch.object(robots, "MIN_TOTAL_TIMEOUT", 0.0):
            state = robots.fetch_robots(peer.url(), timeout, True)
        return state, time.monotonic() - t0

    def test_slow_drip_headers_hit_total_deadline(self):
        # 状態行とヘッダーを 0.08 秒に1バイトずつ送る（全部で約 8 秒）。1回の操作は 0.5 秒で切れないが、
        # 取得全体の締め切り（1.5 秒）で止めて全拒否（取得できず）にする
        state, elapsed = self.drip_fetch(_drip(_ok_response(), 0.08))
        self.assertEqual(state["state"], "unreachable", state)
        self.assertIn("タイムアウト", state["detail"])
        self.assertIn("取得全体で 1.5 秒", state["detail"])  # --timeout 0.5 の 3 倍
        self.assertGreaterEqual(elapsed, 1.4)  # 1回の操作のタイムアウト（0.5 秒）ではなく、取得全体の締め切りで止まる
        self.assertLess(elapsed, 4.0)

    def test_slow_drip_body_hits_total_deadline(self):
        # ヘッダーはすぐ送り、本文を1バイトずつ送る。途中まで読んだ本文で判定しない
        body = b"User-agent: *\nAllow: /\n" + b"# " + b"x" * 80 + b"\n"
        head = _ok_response(body)[:-len(body)]

        def respond(conn, path, stopped):
            conn.sendall(head)
            _drip(body, 0.08)(conn, path, stopped)

        state, elapsed = self.drip_fetch(respond)
        self.assertEqual(state["state"], "unreachable", state)
        self.assertIn("取得全体", state["detail"])
        self.assertEqual(state["text"], "")
        self.assertLess(elapsed, 4.0)

    def test_slow_redirect_chain_hits_total_deadline(self):
        # 1段ごとは 0.35 秒（1回の操作のタイムアウト 0.5 秒より短い）でも、5回のリダイレクトが積み上がれば締め切りで止める
        def respond(conn, path, stopped):
            time.sleep(0.35)
            step = 0 if path == "/robots.txt" else int(path.rsplit("/", 1)[-1])
            if step < 5:
                conn.sendall("HTTP/1.1 301 Moved\r\nLocation: /hop/{}\r\nContent-Length: 0\r\nConnection: close\r\n"
                             "\r\n".format(step + 1).encode("ascii"))
            else:
                conn.sendall(_ok_response())

        state, elapsed = self.drip_fetch(respond)
        self.assertEqual(state["state"], "unreachable", state)
        self.assertIn("取得全体", state["detail"])
        self.assertLess(elapsed, 4.0)

    def test_fast_fetch_within_deadline(self):
        # 締め切りの中で終わる取得は今までどおり
        peer = _RawPeer(lambda conn, path, stopped: conn.sendall(_ok_response()))
        self.addCleanup(peer.close)
        state = robots.fetch_robots(peer.url(), 5, True)
        self.assertEqual((state["state"], state["code"]), ("ok", 200))

    # --- 1xx の中間の応答 ---

    def interim_fetch(self, interim):
        peer = _RawPeer(lambda conn, path, stopped: conn.sendall(interim + _ok_response()))
        self.addCleanup(peer.close)
        return robots.fetch_robots(peer.url(), 5, True)

    def test_interim_responses_are_skipped(self):
        # 103 Early Hints などの中間の応答は読み飛ばし、そのあとの最終の応答（200）の本文を判定する
        cases = [
            ("103", b"HTTP/1.1 103 Early Hints\r\nLink: </style.css>; rel=preload; as=style\r\n\r\n"),
            ("102", b"HTTP/1.1 102 Processing\r\n\r\n"),
            ("100", b"HTTP/1.1 100 Continue\r\n\r\n"),
            ("100+103", b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 103 Early Hints\r\nLink: </a.css>\r\n\r\n"
                        b"HTTP/1.1 103 Early Hints\r\nLink: </b.css>\r\n\r\n"),
        ]
        for name, interim in cases:
            with self.subTest(interim=name):
                state = self.interim_fetch(interim)
                self.assertEqual((state["state"], state["code"]), ("ok", 200), state)
                self.assertEqual(len(robots.robots_groups(state)), 1)
                rows = robots.evaluate(state, [crawler("GPTBot"), crawler("CCBot", "dataset")], ["/"])
                self.assertEqual([r["verdict"] for r in rows], ["拒否", "許可"])

    def test_switching_protocols_is_final(self):
        # 101（プロトコルの切り替え）は最終の応答なので読み飛ばさず、2xx ではない応答として全拒否（取得できず）にする
        state = self.interim_fetch(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: h2c\r\nConnection: Upgrade\r\n\r\n")
        self.assertEqual((state["state"], state["code"]), ("unreachable", 101), state)
        self.assertEqual(state["text"], "")

    def test_too_many_interim_responses(self):
        # 中間の応答が際限なく続くサーバーでは止まらずに、全拒否（取得できず）にする
        state = self.interim_fetch(b"HTTP/1.1 103 Early Hints\r\n\r\n" * 200)
        self.assertEqual(state["state"], "unreachable", state)
        self.assertIn("中間の応答", state["detail"])


# ---------------------------------------------------------------------------
# コマンドライン（別プロセス）
# ---------------------------------------------------------------------------

class MainTest(TempDirCase):
    ROBOTS = ("User-agent: GPTBot\nDisallow: /\n\n"
              "User-agent: *\nDisallow: /admin/\n\n"
              "User-agent: CCBot\nAllow: /\n")

    def run_main(self, args):
        return helpers.run_script("ai_robots_check", args, cwd=self.tmp)

    def test_file_markdown(self):
        path = self.write("robots.txt", self.ROBOTS)
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "--paths", "/,/admin/"])
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("# AI クローラーの robots.txt 判定", out)
        self.assertIn("## 要約（パス / で判定）", out)
        self.assertIn("学習: 1 件中 1 件が拒否", out)
        self.assertIn("| OpenAI | GPTBot | 学習 | / | 拒否 | User-agent: GPTBot | `Disallow: /` |", out)
        self.assertIn("| Common Crawl | CCBot | 公開データセット | /admin/ | 許可 | User-agent: CCBot | `Allow: /` |", out)
        # Markdown では robots.txt 由来のパターンをコードスパンにする（リンクや画像として解釈させない）
        self.assertIn("CCBot 向けのグループがあるため、User-agent: * の Disallow: `/admin/` は CCBot に適用されません", out)
        self.assertIn("一覧の確認日: 2026-08-01", out)
        self.assertIn("CCBot 向けのグループがあるため、User-agent: * の Disallow: /admin/ は CCBot に適用されません",
                      result.stderr)

    def test_file_csv_stdout(self):
        path = self.write("robots.txt", self.ROBOTS)
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "--format", "csv"])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "operator,token,category,path,verdict,matched_group,matched_rule,note")
        self.assertFalse(result.stdout.startswith("\ufeff"))
        self.assertIn("OpenAI,GPTBot,training,/,拒否,User-agent: GPTBot,Disallow: /,", lines)
        self.assertEqual(len(lines), 7)

    def test_file_csv_output_file_is_sanitized(self):
        path = self.write("robots.txt", self.ROBOTS)
        crawlers = self.write("c.csv", "operator,token,category\n=HYPERLINK(\"x\"),GPTBot,training\n")
        out = os.path.join(self.tmp, "out.csv")
        result = self.run_main(["--file", path, "--crawlers", crawlers, "--format", "csv", "-o", out])
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(codecs.BOM_UTF8))
        self.assertIn("'=HYPERLINK", data.decode("utf-8-sig"))

    def test_markdown_output_file(self):
        path = self.write("robots.txt", self.ROBOTS)
        out = os.path.join(self.tmp, "report.md")
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "-o", out])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        with open(out, encoding="utf-8") as f:
            self.assertIn("# AI クローラーの robots.txt 判定", f.read())

    def test_shift_jis_file_warns(self):
        text = "# 架空珈琲の設定\nUser-agent: GPTBot\nDisallow: /\n"
        path = self.write("robots.txt", text.encode("cp932"))
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UTF-8 として読めない", result.stderr)
        self.assertIn("| OpenAI | GPTBot | 学習 | / | 拒否 |", result.stdout)

    def test_url_and_file_together(self):
        path = self.write("robots.txt", self.ROBOTS)
        result = self.run_main(["--url", "https://kakuu-coffee.example", "--file", path,
                                "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--url と --file", result.stderr)

    def test_neither_url_nor_file(self):
        result = self.run_main(["--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 2)

    def test_userinfo_url(self):
        result = self.run_main(["--url", "https://user:secret@kakuu-coffee.example/", "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 2)
        self.assertIn("userinfo", result.stderr)
        self.assertNotIn("secret", result.stderr)

    def test_bad_format(self):
        path = self.write("robots.txt", self.ROBOTS)
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "--format", "xml"])
        self.assertEqual(result.returncode, 2)

    def test_empty_paths(self):
        path = self.write("robots.txt", self.ROBOTS)
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "--paths", " , "])
        self.assertEqual(result.returncode, 2)

    def test_missing_crawlers_file(self):
        path = self.write("robots.txt", self.ROBOTS)
        result = self.run_main(["--file", path, "--crawlers", os.path.join(self.tmp, "none.csv")])
        self.assertEqual(result.returncode, 2)

    def test_missing_robots_file(self):
        result = self.run_main(["--file", os.path.join(self.tmp, "none.txt"), "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 2)

    def test_default_crawlers_missing(self):
        # 既定の一覧（スクリプトの親フォルダの data/ai-crawlers.csv）がないときは終了コード 2
        skill = os.path.join(self.tmp, "skill")
        os.makedirs(os.path.join(skill, "scripts"))
        for name in ("ai_robots_check.py", "ai_search_common.py"):
            shutil.copy(os.path.join(helpers.SCRIPTS, name), os.path.join(skill, "scripts", name))
        path = self.write("robots.txt", self.ROBOTS)
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-B", os.path.join(skill, "scripts", "ai_robots_check.py"), "--file", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("ai-crawlers.csv", result.stderr)
        self.assertIn("--crawlers", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(skill, "scripts", "__pycache__")))

    def test_markdown_does_not_render_robots_content(self):
        text = "User-agent: *\nDisallow: /![x](https://tracker.example/p.png)\n\nUser-agent: GPTBot\nAllow: /\n"
        path = self.write("robots.txt", text)
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV,
                                "--paths", "/![x](https://tracker.example/p.png)"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| `Disallow: /![x](https://tracker.example/p.png)` |", result.stdout)
        self.assertIn("Disallow: `/![x](https://tracker.example/p.png)` は GPTBot", result.stdout)

    def test_timeout_must_be_finite_and_bounded(self):
        path = self.write("robots.txt", self.ROBOTS)
        for value in ("0", "-1", "inf", "nan", "1e300", "601"):
            with self.subTest(value=value):
                result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "--timeout=" + value])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("--timeout は 0 より大きく 600 以下の秒数にしてください", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "--timeout", "600"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_timeout_inf_with_url_does_not_crash(self):
        # レビューの再現手順: --timeout inf で接続すると OverflowError の traceback で終わっていた
        result = self.run_main(["--url", "http://127.0.0.1:9", "--allow-private", "--crawlers", CRAWLERS_CSV,
                                "--timeout", "inf"])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_unexpected_error_returns_1(self):
        # 想定外の例外は、ほかのスクリプトと同じく日本語の見出しと経緯を出して 1 を返す（例外を外に出さない）
        with mock.patch.object(robots, "run", side_effect=RuntimeError("架空の不具合")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = robots.main(["--file", "robots.txt"])
        self.assertEqual(code, 1)
        self.assertIn("想定外のエラー（ai_robots_check.py {}）: RuntimeError: 架空の不具合".format(common.VERSION),
                      err.getvalue())
        self.assertIn("Traceback", err.getvalue())

    def test_paths_not_utf8(self):
        # UTF-8 でないバイトを含む引数（Python では surrogate の文字になる）は入力の誤りとして 2 で止める
        with self.assertRaises(robots.InputError):
            robots.parse_paths("/\udcff")
        if os.name != "posix":
            self.skipTest("引数にバイト列を渡せるのは POSIX だけ")
        path = self.write("robots.txt", self.ROBOTS)
        cmd = [sys.executable, "-B", os.path.join(helpers.SCRIPTS, "ai_robots_check.py"), "--file", path,
               "--crawlers", CRAWLERS_CSV, "--paths", b"/\xff"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        stderr = result.stderr.decode("utf-8", "replace")
        self.assertEqual(result.returncode, 2, stderr)
        self.assertIn("--paths", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_file_name_not_utf8(self):
        # ファイル名に UTF-8 でないバイトがある（引数では surrogate の文字になる）と、Markdown を標準出力に
        # 書くときに落ちていた。macOS ではそういうファイル名を作れないので、ファイルを開く処理を差し替えて確かめる
        name = "/tmp/robots-\udcff.txt"
        data = self.ROBOTS.encode("utf-8")
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8", errors="strict", write_through=True)
        with mock.patch.object(robots, "open", create=True, new=lambda path, mode="r": io.BytesIO(data)), \
                mock.patch("sys.stdout", stream), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = robots.main(["--file", name, "--crawlers", CRAWLERS_CSV])
        self.assertEqual(code, 0, err.getvalue())
        out = buffer.getvalue().decode("utf-8")
        self.assertIn("読んだファイル: `/tmp/robots-\\udcff.txt`", out)
        self.assertIn("| OpenAI | GPTBot | 学習 | / | 拒否 |", out)
        stream.detach()

    def test_csv_stdout_line_endings_on_windows_like_stream(self):
        # Windows の標準出力（\n を \r\n に変える）を模す。行末が \r\r\n にならないこと
        path = self.write("robots.txt", self.ROBOTS)
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8", newline="\r\n", write_through=True)
        with mock.patch("sys.stdout", stream), mock.patch("sys.stderr", new_callable=io.StringIO):
            code = robots.main(["--file", path, "--crawlers", CRAWLERS_CSV, "--format", "csv"])
        self.assertEqual(code, 0)
        data = buffer.getvalue()
        self.assertNotIn(b"\r\r\n", data)
        self.assertTrue(data.startswith(b"operator,token,category,path,verdict,matched_group,matched_rule,note\r\n"))
        self.assertEqual(data.count(b"\r\n"), 7)
        stream.detach()

    def test_stdout_in_cp932_does_not_crash_in_process(self):
        # Windows でパイプやファイルにつないだ標準出力（cp932）を模す。cp932 にない文字（é、–）があっても落ちず、
        # UTF-8 のバイト列で書く（-o で書くファイルと同じ UTF-8）
        path = self.write("robots.txt", self.ROBOTS)
        for fmt in ("md", "csv"):
            with self.subTest(format=fmt):
                buffer = io.BytesIO()
                stream = io.TextIOWrapper(buffer, encoding="cp932", errors="strict", write_through=True)
                with mock.patch("sys.stdout", stream), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                    code = robots.main(["--file", path, "--crawlers", CRAWLERS_CSV, "--format", fmt,
                                        "--paths", "/café/,/news/2026–10/"])
                stream.detach()
                self.assertEqual(code, 0, err.getvalue())
                out = buffer.getvalue().decode("utf-8")
                self.assertIn("/café/", out)
                self.assertIn("/news/2026–10/", out)

    def test_stdout_in_cp932_does_not_crash(self):
        # 別プロセスで PYTHONIOENCODING=cp932（日本語版 Windows でパイプにつないだときの既定を模す）
        path = self.write("robots–copy.txt", self.ROBOTS)
        env = dict(os.environ, PYTHONIOENCODING="cp932")
        env.pop("PYTHONUTF8", None)
        for fmt in ("md", "csv"):
            with self.subTest(format=fmt):
                cmd = [sys.executable, "-B", os.path.join(helpers.SCRIPTS, "ai_robots_check.py"), "--file", path,
                       "--crawlers", CRAWLERS_CSV, "--format", fmt, "--paths", "/café/"]
                result = subprocess.run(cmd, cwd=self.tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 0, result.stderr.decode("cp932", errors="replace"))
                out = result.stdout.decode("utf-8")
                self.assertIn("/café/", out)
                self.assertNotIn(b"Traceback", result.stderr)
                if fmt == "md":
                    self.assertIn("robots–copy.txt", out)
                else:
                    self.assertEqual(out.count("\r\n"), 7)

    def test_output_same_as_input_is_rejected(self):
        # -o が入力のファイルと同じなら、入力を報告で上書きせずに終了コード 2 で止める
        path = self.write("r2.txt", self.ROBOTS)
        crawlers = self.write("c.csv", HEADER + "OpenAI,GPTBot,training,,,,,2026-09-26\n")
        cases = [
            (["--file", path, "--crawlers", CRAWLERS_CSV, "-o", path], path, "--file"),
            (["--file", path, "--crawlers", CRAWLERS_CSV, "--format", "csv", "-o", path], path, "--file"),
            (["--file", path, "--crawlers", crawlers, "-o", crawlers], crawlers, "--crawlers"),
            # 相対パスと絶対パスのように書き方が違っても、同じファイルなら止める
            (["--file", "r2.txt", "--crawlers", CRAWLERS_CSV, "-o", os.path.join(".", "r2.txt")], path, "--file"),
        ]
        for args, target, flag in cases:
            with self.subTest(args=args):
                with open(target, "rb") as f:
                    before = f.read()
                result = self.run_main(args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("-o の出力先が {} のファイルと同じ".format(flag), result.stderr)
                self.assertEqual(result.stdout, "")
                with open(target, "rb") as f:
                    self.assertEqual(f.read(), before)

    @unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "シンボリックリンクを作れる POSIX だけ")
    def test_output_symlink_to_input_is_rejected(self):
        path = self.write("robots.txt", self.ROBOTS)
        link = os.path.join(self.tmp, "link.md")
        os.symlink(path, link)
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "-o", link])
        self.assertEqual(result.returncode, 2, result.stderr)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), self.ROBOTS)

    def test_output_other_file_is_written(self):
        path = self.write("robots.txt", self.ROBOTS)
        out = os.path.join(self.tmp, "report.md")
        self.write("report.md", "古い報告\n")
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV, "-o", out])
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, encoding="utf-8") as f:
            self.assertIn("# AI クローラーの robots.txt 判定", f.read())

    def test_malformed_host_is_input_error(self):
        # 二重のドットなどの打ち間違いを、全拒否の表（終了コード 0）として報告しない
        for url in ("https://example..com", "https://" + "a" * 64 + ".com"):
            with self.subTest(url=url):
                result = self.run_main(["--url", url, "--crawlers", CRAWLERS_CSV, "--format", "csv"])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("ホスト名", result.stderr)

    def test_idna_deviation_host_is_input_error(self):
        result = self.run_main(["--url", "https://faß.de", "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("IDNA", result.stderr)

    def test_help_describes_total_timeout(self):
        result = self.run_main(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("取得全体", "".join(result.stdout.split()))  # 折り返しの改行と空白を除いて比べる

    def test_utf16_file_cli(self):
        path = self.write("robots.txt", "User-agent: GPTBot\r\nDisallow: /\r\n".encode("utf-16"))
        result = self.run_main(["--file", path, "--crawlers", CRAWLERS_CSV])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UTF-16 で保存されているため、どの行も読めませんでした", result.stderr)
        self.assertIn("UTF-16 で保存されているため、どの行も読めませんでした", result.stdout)
        self.assertNotIn("コメントの中だけなら", result.stderr)

    def test_schemeless_userinfo_not_shown(self):
        for url in ("user:secret@kakuu-coffee.example", "https:user:secret@kakuu-coffee.example"):
            with self.subTest(url=url):
                result = self.run_main(["--url", url, "--crawlers", CRAWLERS_CSV])
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("secret", result.stderr)

    def test_help(self):
        result = self.run_main(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout)


if __name__ == "__main__":
    unittest.main()
