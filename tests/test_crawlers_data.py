# -*- coding: utf-8 -*-
"""
data/ai-crawlers.csv（AI クローラーの一覧の正本）の形と中身を確かめるテスト。

ai_robots_check.py はこの一覧を読んで判定する。一覧を手で直したときに、次の誤りに気づけるようにする。
- 列の欠け、決まった値以外の category、手順書で名前を挙げるトークンの分類の書き換え
- 同じトークンの重複（robots.txt の照合は大文字・小文字を区別しない）
- RFC 9309 の product token に使えない文字（数字、ドット、全角、ノーブレークハイフン）を含むトークン
- 未来の確認日、ホストのない出典の URL、仮の URL（example.com など）
- 確認日の時点で過ぎた予定を、まだ先のことのように書いた文
- source_url 以外の資料から写した内容で、資料名を書いていない文

一覧に入れる行の決まり: 2026-09-26 の再確認で公式資料と一致した行（confirmed と corrected）を入れる。
ただし、robots.txt に従わないと公式が明記していて AI の用途もないもの（EXCLUDED_TOKENS）は、
判定しても意味がないので入れない。公式資料で確認できなかった名前も入れない。

後半の RobotsCheckIntegrationTest は、本物の一覧を ai_robots_check.py に通して、一覧の robots_control の説明と
判定の結果が食い違わないかを確かめる（実装計画 Task 7 の Step 2 の代わり）。
"""
import csv
import datetime
import io
import os
import re
import shutil
import tempfile
import unittest
from urllib.parse import urlsplit

try:
    import helpers
except ImportError:  # リポジトリのルートで python3 -m unittest tests.test_crawlers_data と実行したとき
    from tests import helpers

common = helpers.load_script("ai_search_common")

DATA = os.path.join(helpers.SKILL_DIR, "data", "ai-crawlers.csv")
ROBOTS_CHECK = os.path.join(helpers.SCRIPTS, "ai_robots_check.py")

# 仕様 7.5 の列。この順番で並べる
FIELDS = ["operator", "token", "category", "purpose", "robots_control", "block_effect", "source_url", "checked_on"]
# ai_robots_check.CATEGORIES のキー。並び順は一覧の中での category の順でもある
CATEGORIES = ["general-search", "search", "training", "user", "control", "dataset", "other"]
# 仕様 7.5 の判定の出力の列
OUTPUT_FIELDS = ["operator", "token", "category", "path", "verdict", "matched_group", "matched_rule", "note"]

# RFC 9309 2.2.1 の product token に使える文字だけ。robots.txt 側の User-agent の値からは、先頭の
# 英字・下線・ハイフンの並びだけを切り出して比べるので、ほかの文字を含むトークンは専用のグループに一致しない
TOKEN_RE = re.compile(r"^[A-Za-z_-]+$")
TOKEN_RULE = ("RFC 9309 の product token に使えるのは英字・下線・ハイフンだけ。数字やドットを含むと "
              "robots.txt のグループに一致しない（全角文字やノーブレークハイフンも同じ）")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 分類を固定するトークン。書き換えると、ai_robots_check の要約（学習 n 件中 m 件が拒否など）と、
# 手順書 05 の方針（学習用だけ拒否する、など）が食い違う
EXPECTED_CATEGORIES = {
    # 手順書と要約で名前を挙げる主なトークン
    "Googlebot": "general-search",
    "Bingbot": "general-search",
    "Applebot": "general-search",
    "OAI-SearchBot": "search",
    "Claude-SearchBot": "search",
    "PerplexityBot": "search",
    "GPTBot": "training",
    "ClaudeBot": "training",
    "ChatGPT-User": "user",
    "Claude-User": "user",
    "Perplexity-User": "user",
    "Google-Extended": "control",
    "Applebot-Extended": "control",
    "CCBot": "dataset",
    # 手順書 05 が「AI ボットの一括遮断で止めない」例に挙げる（ChatGPT 広告の審査に必要）
    "OAI-AdsBot": "other",
    # 2026-09-26 のレビューで分類を決めた行
    "YouBot": "general-search",  # 公式の説明は検索エンジン用で、AI の回答への利用は書かれていない
    "Coherebot": "other",  # 公式の一覧表で N/A（現在は稼働していない）
    "GoogleOther": "other",  # 公式の説明に AI や学習の記載がない
}

# 公式資料で確認できたが、一覧に入れないトークンと理由
EXCLUDED_TOKENS = {
    "iTMS": "Apple Podcasts 用。robots.txt に従わないと公式が明記しており、AI の用途もないので、判定しても意味がない",
}

# robots_control に「自分のグループがなければ Googlebot のグループに従う（Googlebot のトークンでも一致する）」
# という公式の説明を書いた行
GOOGLEBOT_FALLBACK_TOKENS = ("Applebot", "Google-CloudVertexBot")

# user の行を、robots.txt の扱いについての運営の説明で分ける
USER_MAY_IGNORE_ROBOTS = (  # robots.txt で止まらない場合があると運営が説明している
    "Google-Agent", "Google-GeminiNotebook", "ChatGPT-User", "Perplexity-User", "meta-externalfetcher", "Amzn-User")
USER_CONTROLLABLE = ("Claude-User", "MistralAI-User")  # 制御できるとだけ説明し、適用外とは書いていない
MAY_IGNORE_RE = re.compile(r"無視|迂回|適用されない場合|従わない場合")
USER_NOT_APPLY_NOTE = "robots.txt が適用されない場合がある（運営の説明）"

# robots.txt 用のトークンが公表されておらず、token の欄に UA 文字列の名前を書いた行。
# robots_control をこの文で始める（ai_robots_check.py が注記の条件に使えるように、文言を固定する）
NOT_ROBOTS_TOKEN_PREFIX = "robots.txt 用のトークンの記載はなく"
NOT_ROBOTS_TOKENS = ("Google-Agent", "Google-GeminiNotebook")

# source_url 以外の資料から写した内容。(トークン, 列, 内容の目印, 同じ文に書く資料名)
ATTRIBUTIONS = [
    ("Googlebot", "block_effect", "nosnippet", "AI 機能のページ"),
    ("Googlebot", "block_effect", "生成 AI 設定", "AI 最適化ガイド"),
    ("Google-Agent", "purpose", "2026-03-20", "変更履歴"),
    ("Google-Agent", "purpose", "一部のリクエスト", "Web Bot Auth のページ"),
    ("Google-GeminiNotebook", "purpose", "NotebookLM が Gemini Notebook", "変更履歴"),
    ("OAI-SearchBot", "block_effect", "2026-08-09", "告知したヘルプ記事"),
    ("GPTBot", "block_effect", "2026-08-09", "告知したヘルプ記事"),
    ("OAI-AdsBot", "robots_control", "User-agent: OAI-AdsBot", "広告主向けのガイダンス"),
    ("Bingbot", "robots_control", "User-agent: Bingbot", "robots.txt の作成ガイド"),
    ("Bingbot", "robots_control", "X-Robots-Tag", "robots メタタグのヘルプ"),
    ("Bingbot", "block_effect", "NOINDEX", "robots メタタグのヘルプ"),
    ("CCBot", "robots_control", "Crawl-delay", "FAQ"),
]

# 仮の URL のホスト（RFC 2606 と RFC 6761 で予約されたもの）
PLACEHOLDER_HOSTS = ("example.com", "example.net", "example.org")
PLACEHOLDER_TLDS = ("example", "test", "invalid", "localhost")

# 期限を過ぎた予定を書いた文に入れる目印
ELAPSED_MARK = "確認日の時点で"
SCHEDULE_WINDOW = 15  # 日付の後ろの何文字までに「予定」があれば予定の日付とみなすか
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_YEAR_MONTH_RE = re.compile(r"(\d{4}) ?年 ?(\d{1,2}) ?月")
_AI_UNDOCUMENTED_RE = re.compile(r"AI[^。]*(書かれていない|記載はない)")
TEXT_FIELDS = ("purpose", "robots_control", "block_effect")


def load_rows():
    fields, rows = common.read_csv(DATA)
    return fields, rows


def where(n, row):
    # 行番号は見出しを1行目として数える
    return "{} 行目（{}）".format(n + 2, row.get("token", ""))


def sentences(text):
    return [s for s in (text or "").split("。") if s.strip()]


def by_token(rows):
    return dict((row.get("token", ""), row) for row in rows)


# ---------------------------------------------------------------------------
# 検査（問題の一覧を返す。空なら合格）
# ---------------------------------------------------------------------------

def token_problems(rows):
    return ["{}: {}".format(where(n, row), TOKEN_RULE)
            for n, row in enumerate(rows) if not TOKEN_RE.match(row.get("token", ""))]


def category_problems(rows, expected):
    table = by_token(rows)
    out = []
    for token, category in expected.items():
        row = table.get(token)
        if row is None:
            out.append("{} の行がありません".format(token))
        elif row.get("category") != category:
            out.append("{} の category が {} です（{} のはず）".format(token, row.get("category"), category))
    return out


def checked_on_problems(rows, today):
    latest = today + datetime.timedelta(days=1)  # CI（UTC）と日本時間で日付がずれる分を許す
    out = []
    for n, row in enumerate(rows):
        value = row.get("checked_on", "")
        if not DATE_RE.match(value):
            out.append("{}: checked_on が YYYY-MM-DD ではありません: {}".format(where(n, row), value))
            continue
        try:
            date = datetime.datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            out.append("{}: checked_on が存在しない日付です: {}".format(where(n, row), value))
            continue
        if date > latest:
            out.append("{}: checked_on が未来の日付です: {}".format(where(n, row), value))
    return out


def _is_placeholder_host(host):
    host = host.lower().rstrip(".")
    if any(host == h or host.endswith("." + h) for h in PLACEHOLDER_HOSTS):
        return True
    return host.rsplit(".", 1)[-1] in PLACEHOLDER_TLDS


def source_url_problems(rows):
    out = []
    for n, row in enumerate(rows):
        url = row.get("source_url", "")
        if not url.startswith("https://"):
            out.append("{}: source_url が https:// で始まりません: {}".format(where(n, row), url))
            continue
        if re.search(r"[\s;,]", url) or url.count("https://") != 1:
            out.append("{}: source_url は1つだけにしてください（空白・;・, で並べない）: {}".format(where(n, row), url))
            continue
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            host = ""
        if not host:
            out.append("{}: source_url にホストがありません: {}".format(where(n, row), url))
        elif _is_placeholder_host(host):
            out.append("{}: source_url が仮の URL です。公式資料の URL を書いてください: {}".format(where(n, row), url))
    return out


def _is_schedule(sentence, end):
    # 日付の直後が「まで」か、すぐ後ろに「予定」があれば予定の日付とみなす（「2026-08-09 に停止予定」
    # 「2026 年 8 月までサポート」）。「（2026-07-10 更新）によると、反映まで」のような更新日は数えない
    rest = sentence[end:end + SCHEDULE_WINDOW]
    return rest.lstrip().startswith("まで") or "予定" in rest


def scheduled_dates(sentence):
    """文の中の、予定として書かれた日付の一覧。年と月だけの日付は、その月の末日とみなす。"""
    dates = []
    for m in _ISO_DATE_RE.finditer(sentence):
        if not _is_schedule(sentence, m.end()):
            continue
        try:
            dates.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    for m in _YEAR_MONTH_RE.finditer(sentence):
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and _is_schedule(sentence, m.end()):
            first_of_next = datetime.date(year + month // 12, month % 12 + 1, 1)
            dates.append(first_of_next - datetime.timedelta(days=1))
    return dates


def stale_schedule_problems(rows):
    out = []
    for n, row in enumerate(rows):
        try:
            checked = datetime.datetime.strptime(row.get("checked_on", ""), "%Y-%m-%d").date()
        except ValueError:
            continue  # 日付の誤りは checked_on_problems で出す
        for name in TEXT_FIELDS:
            for sentence in sentences(row.get(name, "")):
                if any(d < checked for d in scheduled_dates(sentence)) and ELAPSED_MARK not in sentence:
                    out.append("{}: {} の「{}」は、確認日（{}）より前の日付の予定を先のことのように書いています。"
                               "「{}予定日を過ぎている」のように、確認日から見た状態を書いてください".format(
                                   where(n, row), name, sentence, row.get("checked_on"), ELAPSED_MARK))
    return out


def attribution_problems(rows, attributions):
    table = by_token(rows)
    out = []
    for token, name, mark, source in attributions:
        row = table.get(token)
        if row is None:
            out.append("{} の行がありません".format(token))
            continue
        found = [s for s in sentences(row.get(name, "")) if mark in s]
        if not found:
            out.append("{} の {} に「{}」がありません（書き換えたなら ATTRIBUTIONS も直す）".format(token, name, mark))
        for sentence in found:
            if source not in sentence:
                out.append("{} の {}: 「{}」を述べた文に資料名「{}」がありません（source_url 以外の資料の内容）".format(
                    token, name, mark, source))
    return out


def search_purpose_problems(rows):
    return ["{}: category が search（AI の検索・回答）なのに、purpose は AI での利用が書かれていないとしています".format(
        where(n, row)) for n, row in enumerate(rows)
        if row.get("category") == "search" and _AI_UNDOCUMENTED_RE.search(row.get("purpose", ""))]


def user_robots_problems(rows):
    users = dict((row.get("token"), row) for row in rows if row.get("category") == "user")
    expected = set(USER_MAY_IGNORE_ROBOTS) | set(USER_CONTROLLABLE)
    out = []
    if set(users) != expected:
        out.append("user の行が変わりました（増えた: {}、減った: {}）。USER_MAY_IGNORE_ROBOTS か "
                   "USER_CONTROLLABLE に振り分けてください".format(
                       ", ".join(sorted(set(users) - expected)) or "なし",
                       ", ".join(sorted(expected - set(users))) or "なし"))
    for token in USER_MAY_IGNORE_ROBOTS:
        if token in users and not MAY_IGNORE_RE.search(users[token].get("robots_control", "")):
            out.append("{}: robots_control に、robots.txt で止まらない場合があるという運営の説明がありません".format(token))
    for token in USER_CONTROLLABLE:
        if token in users and MAY_IGNORE_RE.search(users[token].get("robots_control", "")):
            out.append("{}: robots_control が robots.txt で止まらない場合があると読めます".format(token))
    return out


def not_robots_token_problems(rows):
    out = []
    for n, row in enumerate(rows):
        control = row.get("robots_control", "")
        starts = control.startswith(NOT_ROBOTS_TOKEN_PREFIX)
        listed = row.get("token") in NOT_ROBOTS_TOKENS
        if listed and not starts:
            out.append("{}: robots_control を「{}」で始めてください".format(where(n, row), NOT_ROBOTS_TOKEN_PREFIX))
        elif starts and not listed:
            out.append("{}: robots_control が「{}」で始まっています。NOT_ROBOTS_TOKENS に足してください".format(
                where(n, row), NOT_ROBOTS_TOKEN_PREFIX))
        elif not starts and NOT_ROBOTS_TOKEN_PREFIX in control:
            out.append("{}: 「{}」は robots_control の先頭に置いてください".format(where(n, row), NOT_ROBOTS_TOKEN_PREFIX))
    return out


def fake_row(**values):
    """検査そのものを確かめるための架空の行。"""
    row = {"operator": "架空AI", "token": "KakuuBot", "category": "search", "purpose": "架空の用途。",
           "robots_control": "制御できる。", "block_effect": "公式の説明なし。",
           "source_url": "https://kakuu-coffee.example/bot", "checked_on": "2026-09-26"}
    row.update(values)
    return row


# ---------------------------------------------------------------------------
# 検査そのもののテスト（壊れた一覧を見逃さないこと）
# ---------------------------------------------------------------------------

class CheckerSelfTest(unittest.TestCase):
    def test_token_rejects_digits_dots_and_non_ascii(self):
        for token in ("AI2Bot", "Kakuu.Bot", "Kakuu‑Bot", "ＫａｋｕｕBot", "Kakuu Bot", ""):
            self.assertEqual(len(token_problems([fake_row(token=token)])), 1, token)
        self.assertEqual(token_problems([fake_row(token="Kakuu_Bot-Extended")]), [])

    def test_category_detects_changed_and_missing(self):
        rows = [fake_row(token="GPTBot", category="search")]
        problems = category_problems(rows, {"GPTBot": "training", "ClaudeBot": "training"})
        self.assertEqual(len(problems), 2)
        self.assertIn("GPTBot の category が search", problems[0])
        self.assertIn("ClaudeBot の行がありません", problems[1])

    def test_checked_on_rejects_future_and_bad_dates(self):
        today = datetime.date(2026, 9, 27)
        for value in ("2099-12-31", "2026-09-29", "2026-02-30", "2026/09/26", ""):
            self.assertEqual(len(checked_on_problems([fake_row(checked_on=value)], today)), 1, value)
        for value in ("2026-09-26", "2026-09-28"):  # 翌日までは日付のずれとして許す
            self.assertEqual(checked_on_problems([fake_row(checked_on=value)], today), [], value)

    def test_source_url_rejects_missing_host_and_placeholders(self):
        for url in ("https://", "https://example.com/test", "https://docs.example.org/bot",
                    "https://kakuu-coffee.example/bot", "https://sample-roast.test/", "https://localhost/",
                    "http://kakuu-coffee.example/",
                    "https://kakuu-coffee.example/a https://sample-roast.example/b",
                    "https://kakuu-coffee.example/;x", "https://[::1"):
            self.assertEqual(len(source_url_problems([fake_row(source_url=url)])), 1, url)

    def test_stale_schedule(self):
        bad = ["旧 UA は「2026 年 8 月までサポート」と記載されている。",
               "Atlas は 2026-08-09 に停止予定と告知されている。",
               "Atlas は 2026-08-09 に動作を停止する予定。",
               "旧 UA は 2026-08-31 まで使える。"]
        for text in bad:
            self.assertEqual(len(stale_schedule_problems([fake_row(purpose=text)])), 1, text)
        good = ["Atlas は 2026-08-09 に停止すると告知されていた（確認日の時点で予定日を過ぎている）。",
                "2026-12-31 に停止予定と告知されている。",
                "AI 最適化ガイド（2026-07-10 更新）によると、反映まで約 24 時間かかる。"]
        for text in good:
            self.assertEqual(stale_schedule_problems([fake_row(purpose=text)]), [], text)

    def test_attribution(self):
        attributions = [("KakuuBot", "robots_control", "User-agent: KakuuBot", "作成ガイド")]
        missing = fake_row(robots_control="制御できる。公式の例の表記は User-agent: KakuuBot。")
        self.assertEqual(len(attribution_problems([missing], attributions)), 1)
        named = fake_row(robots_control="制御できる。作成ガイドの例の表記は User-agent: KakuuBot。")
        self.assertEqual(attribution_problems([named], attributions), [])
        rewritten = fake_row(robots_control="制御できる。")
        self.assertEqual(len(attribution_problems([rewritten], attributions)), 1)

    def test_search_purpose(self):
        row = fake_row(purpose="検索エンジンのクローラー（AI の学習や AI 回答への利用は書かれていない）。")
        self.assertEqual(len(search_purpose_problems([row])), 1)
        self.assertEqual(search_purpose_problems([dict(row, category="general-search")]), [])

    def test_not_robots_token_prefix(self):
        row = fake_row(token="Google-Agent", robots_control="一般に無視する。robots.txt 用のトークンの記載はなく、…")
        self.assertEqual(len(not_robots_token_problems([row])), 1)
        other = fake_row(robots_control="robots.txt 用のトークンの記載はなく、…")
        self.assertEqual(len(not_robots_token_problems([other])), 1)


# ---------------------------------------------------------------------------
# 一覧のテスト
# ---------------------------------------------------------------------------

class CrawlersFileTest(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(os.path.isfile(DATA), "data/ai-crawlers.csv がありません: {}".format(DATA))

    def test_utf8(self):
        # cp932 への切り替えに頼らず、UTF-8 として読めること（BOM はあってもよい）
        with open(DATA, "rb") as f:
            data = f.read()
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            self.fail("UTF-8 として読めません（Excel で Shift_JIS に保存していませんか）: {}".format(exc))

    def test_columns_in_order(self):
        fields, _ = load_rows()
        self.assertEqual(fields, FIELDS)

    def test_has_rows(self):
        _, rows = load_rows()
        self.assertGreater(len(rows), 0)


class CrawlersRowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields, cls.rows = load_rows()

    def assertNoProblems(self, problems):
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_all_cells_filled(self):
        for n, row in enumerate(self.rows):
            for name in FIELDS:
                self.assertTrue(row.get(name, "").strip(), "{}: {} が空です".format(where(n, row), name))

    def test_no_extra_cells(self):
        # 列より多いセルがあると csv の読み込みで捨てられるので、生の行で確かめる
        text = common.read_text(DATA)
        for n, raw in enumerate(list(csv.reader(io.StringIO(text)))[1:]):
            if not any(cell.strip() for cell in raw):
                continue
            self.assertEqual(len(raw), len(FIELDS), "{} 行目: セルの数が {} 個です".format(n + 2, len(raw)))

    def test_category_values(self):
        for n, row in enumerate(self.rows):
            self.assertIn(row["category"], CATEGORIES, where(n, row))

    def test_expected_categories(self):
        self.assertNoProblems(category_problems(self.rows, EXPECTED_CATEGORIES))

    def test_excluded_tokens_absent(self):
        tokens = set(row["token"].lower() for row in self.rows)
        for token, reason in EXCLUDED_TOKENS.items():
            self.assertNotIn(token.lower(), tokens, "{} は一覧に入れない: {}".format(token, reason))

    def test_token_format(self):
        self.assertNoProblems(token_problems(self.rows))

    def test_token_unique_case_insensitive(self):
        seen = {}
        for n, row in enumerate(self.rows):
            key = row["token"].lower()
            self.assertNotIn(key, seen, "{}: {} 行目と同じトークンです".format(where(n, row), seen.get(key)))
            seen[key] = n + 2

    def test_checked_on(self):
        self.assertNoProblems(checked_on_problems(self.rows, datetime.date.today()))

    def test_source_url(self):
        self.assertNoProblems(source_url_problems(self.rows))

    def test_no_stale_schedule(self):
        self.assertNoProblems(stale_schedule_problems(self.rows))

    def test_other_sources_are_named(self):
        self.assertNoProblems(attribution_problems(self.rows, ATTRIBUTIONS))

    def test_search_purpose_matches_category(self):
        self.assertNoProblems(search_purpose_problems(self.rows))

    def test_user_rows_robots_statement(self):
        self.assertNoProblems(user_robots_problems(self.rows))

    def test_not_robots_token_rows(self):
        self.assertNoProblems(not_robots_token_problems(self.rows))

    def test_googlebot_fallback_rows(self):
        table = by_token(self.rows)
        for token in GOOGLEBOT_FALLBACK_TOKENS:
            self.assertIn(token, table)
            self.assertIn("Googlebot", table[token]["robots_control"], token)

    def test_no_bold_markup(self):
        for n, row in enumerate(self.rows):
            for name in FIELDS:
                self.assertNotIn("**", row[name], "{}: {}".format(where(n, row), name))

    def test_no_newline_in_cells(self):
        for n, row in enumerate(self.rows):
            for name in FIELDS:
                self.assertNotIn("\n", row[name], "{}: {}".format(where(n, row), name))

    def test_operator_rows_are_contiguous(self):
        finished = set()
        previous = None
        for n, row in enumerate(self.rows):
            operator = row["operator"]
            if operator != previous:
                self.assertNotIn(operator, finished, "{}: {} の行が離れています".format(where(n, row), operator))
                if previous is not None:
                    finished.add(previous)
                previous = operator

    def test_category_order_within_operator(self):
        previous_operator = None
        previous_index = -1
        for n, row in enumerate(self.rows):
            index = CATEGORIES.index(row["category"]) if row["category"] in CATEGORIES else -1
            if row["operator"] == previous_operator:
                self.assertGreaterEqual(index, previous_index,
                                        "{}: category の順番が違います".format(where(n, row)))
            previous_operator = row["operator"]
            previous_index = index


# ---------------------------------------------------------------------------
# 本物の一覧を ai_robots_check.py に通す
# ---------------------------------------------------------------------------

def parse_csv_output(stdout):
    reader = csv.DictReader(io.StringIO(stdout))
    return reader.fieldnames, list(reader)


def warning_lines(stderr):
    return [line[len("警告: "):] for line in stderr.splitlines() if line.startswith("警告: ")]


def mentions(text, token):
    # Applebot を探すときに Applebot-Extended を数えない
    return re.search(r"(?<![\w-]){}(?![\w-])".format(re.escape(token)), text) is not None


class RobotsCheckIntegrationTest(unittest.TestCase):
    """
    本物の一覧（--crawlers を付けない既定の一覧）を ai_robots_check.py に通して確かめる。
    ai_robots_check.py はスキルの一部なので、見つからなければスキップせず失敗にする。

    Googlebot のグループに従うクローラー（fallback）、user の行の注記、robots.txt 用のトークンでない行の注記を、
    一覧の robots_control の説明と照らして確かめる（2026-09-26 のレビューの指摘）。
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(ROBOTS_CHECK):
            raise AssertionError("ai_robots_check.py がありません（スキルのフォルダが欠けています）: {}".format(
                ROBOTS_CHECK))
        cls.robots = helpers.load_script("ai_robots_check")
        cls.data_fields, cls.data_rows = load_rows()
        cls.tmp = tempfile.mkdtemp(prefix="crawlers-data-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        # GPTBot だけを拒否した robots.txt（計画 Task 7 の Step 2 の代わり）
        cls.gptbot_csv = cls.run_check("gptbot.txt", "User-agent: GPTBot\nDisallow: /\n", "csv")
        cls.gptbot_md = cls.run_check("gptbot.txt", "User-agent: GPTBot\nDisallow: /\n", "md")
        # Googlebot のグループしかない robots.txt（Applebot などは Googlebot のグループに従うはず）
        cls.googlebot_csv = cls.run_check(
            "googlebot.txt", "User-agent: Googlebot\nDisallow: /\n\nUser-agent: *\nAllow: /\n", "csv")
        # * の Disallow が Googlebot のグループに書かれていない robots.txt
        cls.star_csv = cls.run_check(
            "star.txt", "User-agent: *\nDisallow: /admin/\n\nUser-agent: Googlebot\nAllow: /\n", "csv")

    @classmethod
    def run_check(cls, name, robots_txt, fmt):
        path = os.path.join(cls.tmp, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(robots_txt)
        return helpers.run_script("ai_robots_check", ["--file", path, "--format", fmt], cwd=cls.tmp)

    def assertRan(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def output_rows(self, result):
        self.assertRan(result)
        fields, rows = parse_csv_output(result.stdout)
        self.assertEqual(fields, OUTPUT_FIELDS)
        return dict((row["token"], row) for row in rows)

    def test_categories_match_script(self):
        self.assertEqual(sorted(self.robots.CATEGORIES), sorted(CATEGORIES))

    def test_script_loads_data(self):
        crawlers = self.robots.load_crawlers(DATA)
        self.assertEqual([c["token"] for c in crawlers], [r["token"] for r in self.data_rows])

    def test_default_list_csv(self):
        self.assertRan(self.gptbot_csv)
        fields, rows = parse_csv_output(self.gptbot_csv.stdout)
        self.assertEqual(fields, OUTPUT_FIELDS)
        # パスは既定の / だけなので、一覧の1行が出力の1行になる
        self.assertEqual([r["token"] for r in rows], [r["token"] for r in self.data_rows])
        for row in rows:
            self.assertEqual(row["path"], "/")
            if row["token"] == "GPTBot":
                self.assertEqual(row["verdict"], "拒否")
                self.assertEqual(row["matched_group"], "User-agent: GPTBot")
                self.assertEqual(row["matched_rule"], "Disallow: /")
            else:
                self.assertEqual(row["verdict"], "許可", row["token"])

    def test_default_list_loads_without_warnings(self):
        # 一覧の読み込みの警告（トークンの形、重複、category の誤り）は「○ 行目」を含む
        self.assertRan(self.gptbot_csv)
        self.assertNotIn("行目", self.gptbot_csv.stderr)

    def test_default_list_markdown(self):
        self.assertRan(self.gptbot_md)
        self.assertIn("# AI クローラーの robots.txt 判定", self.gptbot_md.stdout)
        for row in self.data_rows:
            self.assertIn("| {} |".format(row["token"]), self.gptbot_md.stdout)

    def test_user_note_for_rows_that_may_ignore_robots(self):
        rows = self.output_rows(self.gptbot_csv)
        for token in USER_MAY_IGNORE_ROBOTS:
            self.assertIn("robots.txt", rows[token]["note"], token)

    def test_googlebot_group_itself(self):
        rows = self.output_rows(self.googlebot_csv)
        self.assertEqual(rows["Googlebot"]["verdict"], "拒否")
        self.assertEqual(rows["Bingbot"]["verdict"], "許可")

    def test_star_warning_for_googlebot(self):
        self.assertRan(self.star_csv)
        self.assertTrue(any(mentions(w, "Googlebot") for w in warning_lines(self.star_csv.stderr)),
                        self.star_csv.stderr)

    def test_googlebot_fallback(self):
        # 指摘 1（major）: Apple と Google は、自分のグループがなければ Googlebot のグループに従うと説明している
        rows = self.output_rows(self.googlebot_csv)
        for token in GOOGLEBOT_FALLBACK_TOKENS:
            self.assertEqual(rows[token]["verdict"], "拒否", token)

    def test_star_warning_follows_googlebot_fallback(self):
        # 指摘 1 の続き: Googlebot のグループに従うクローラーにも、* の Disallow は適用されない
        warnings = warning_lines(self.star_csv.stderr)
        for token in GOOGLEBOT_FALLBACK_TOKENS:
            self.assertTrue(any(mentions(w, token) for w in warnings), token)

    def test_user_note_does_not_overstate(self):
        # 指摘 2（major）: 運営が制御できるとだけ説明している user の行に「適用されない場合がある（運営の説明）」と書かない
        rows = self.output_rows(self.gptbot_csv)
        for token in USER_CONTROLLABLE:
            self.assertNotIn(USER_NOT_APPLY_NOTE, rows[token]["note"], token)

    def test_not_robots_token_note(self):
        # 指摘 6（minor）: robots.txt 用のトークンではない名前の行は、判定が参考にすぎないことを注記に出す
        rows = self.output_rows(self.gptbot_csv)
        for token in NOT_ROBOTS_TOKENS:
            self.assertIn("robots.txt 用のトークン", rows[token]["note"], token)


if __name__ == "__main__":
    unittest.main()
