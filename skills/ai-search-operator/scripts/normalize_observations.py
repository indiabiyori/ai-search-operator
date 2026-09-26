# -*- coding: utf-8 -*-
"""
normalize_observations.py - 回答ファイルを observations.csv と citations.csv にまとめる

目的:
  AI の回答を貼り付けた回答ファイルを読み、自社・競合の言及と引用を判定して CSV にする。
  判定は決まった規則だけで行い、同じ入力なら毎回同じ CSV になる。回答の本文や出典の中の文は
  データとして照合するだけで、実行も解釈もしない。

入力（作業フォルダ。既定は ai-search/）:
  entities.csv  自社と競合の表記ゆれ・除外語・ドメイン（必須）
  prompts.csv   プロンプトセット（任意。あれば stage・branded・intent_group を結合する）
  answers/      回答ファイル（answers/<ラウンド>/<サービス>/<プロンプトID>-<回数>.md）。
                先頭の欄（--- で囲んだ key: value）と、「## 回答」「## 出典」の見出しを持つ。
                見出しは「## Answer」「## Sources」も受け付ける。

出力（毎回作り直す派生物。手で直さない）:
  observations.csv       1行＝1回答
  citations.csv          1行＝1出典（出典の欄の URL と、回答の欄の中のリンク）
  observations.run.json  スクリプトの版、実行日時、entities.csv と prompts.csv の SHA-256、件数

有効な回答の決まり（言及率・引用率の分母に入れるか）:
  - status が空なら、回答の欄に文字があれば「記録済み」、なければ「未記入」とみなす。
  - sources_status が空なら、出典の欄か回答の欄に URL があれば「記録済み」、なければ「不明」とみなす。
  - status が記録済みでない、必須の欄（round、prompt_id、service、surface、login、repeat）が
    欠けているか値が不正、「## 回答」の見出しがない、回答が空、のどれかに当たれば、
    valid_mention と valid_citation を 0 にし、理由を exclusion_reason に書く。
  - sources_status が「不明」か決まった値以外なら、valid_citation だけを 0 にする。
  - 無効な回答も CSV に残す。記録できなかった回答を「言及なし」として数えないため。

回答の欄と出典の欄:
  - 見出しは「## 回答」「## 出典」（「## Answer」「## Sources」）。全角の ＃ と空白、見出しの語の後ろの
    「:」「（3件）」のような補足も受け付ける。
  - 回答の欄の中の「## 参考」「## 参考文献」「## 引用元」「## References」のような見出しは、出典の見出しと
    みなし、その下を出典の欄に入れる（見出しの書き方のゆれで、出典のページ名を言及として数えないため）。
  - AI の回答そのものにある、そのほかの ## の見出しでは回答の欄を切らない。「## 出典」の見出しより後ろにある、
    そのほかの ## の見出しの下（メモなど）は、どちらの欄にも入れない。
  - 出典の見出しが見つからず、回答の欄に ## の見出しがあれば警告する（見出しの書き間違いに気づくため）。

言及の判定:
  - 回答の欄だけを見る（出典の欄のページ名は数えない）。
  - 照合の前に、回答の欄の URL を空白に置き換える。Markdown のリンクは URL とタイトルを消し、リンクの文字は
    残す。参照形式のリンクは、定義の行（[1]: URL "タイトル"）をまるごと消す。リンクの文字がリンク先の
    ドメインだけのもの（ChatGPT の出典の表示など）は、文字も消す。
  - 回答の欄の URL の直後に空白なしで日本語が続き、その手前までが出典の欄の URL と同じなら、そこで URL を
    切り、日本語を照合に残す。出典の欄の URL は切らない（日本語を含む URL があるため）。
  - 本文と表記の両方を正規化（NFKC、大文字・小文字、ダッシュ類、連続する空白）してから探す。
  - 英数字で始まる（終わる）表記は、前（後ろ）の文字が英数字なら一致とみなさない。
  - 除外語の出現範囲に含まれる一致は数えない。

引用の判定:
  - 出典の欄の URL を出現順に拾い、同じ URL（追跡用のパラメータを除いて比べる）の2回目以降は
    数えない。出現順を source_order にする。画面の表示順であって、重要度を表すとは限らない。
  - ホスト名のない URL（https:// だけ）は URL とみなさない。
  - 回答の欄のリンクは location=body とし、source_order は付けない。出典の欄と同じ URL は数えない。
  - Google の /url?q= は行き先に戻す。行き先を復元できないリダイレクト用の URL と短縮 URL は
    entity_kind=unresolved にする。
  - ホスト名が entities.csv のドメインか、そのサブドメインなら、その entity とする。複数に当たれば
    いちばん長いドメインを使う（同じ長さなら自社を先にし、entities.csv の順）。
  - own_cited は、自社のドメインの URL が出典か本文のリンクにあることだけを表す。
    その出典が自社についての主張を裏付けているかは判定しない。
  - 出典の欄に URL のない行があれば警告する。ただし、ページ名の行の次の行に（番号や記号なしで）URL が
    あれば、同じ出典の続きとみなして数えない。

observed_at:
  - 先頭の日付を YYYY-MM-DD の形にそろえて出す（「2026/10/01」「2026-10-1」「2026年10月1日」も読む）。
    compare_runs.py が観測した日数を数えるのに使うため。読めなければ元の値のまま出し、警告する。

使い方:
  python3 normalize_observations.py [--workspace ai-search] [--rounds 2026-10-01,2026-10-08]

終了コード: 0 成功、2 入力や引数の誤り（回答ファイルを読めない、出力を書けないを含む）、1 想定外のエラー。
処理の要約と警告は標準エラー出力に出す。
"""
import argparse
import datetime
import json
import os
import re
import sys
import traceback
import unicodedata
from urllib.parse import parse_qsl, unquote_plus, urlsplit

sys.dont_write_bytecode = True  # スキルのフォルダに __pycache__ を残さない（共通処理を import する前に置く）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)  # どのフォルダから実行しても、同じフォルダの共通処理を読む

import ai_search_common as common  # noqa: E402

SCRIPT_NAME = "normalize_observations.py"

OBS_FIELDS = [
    "round", "answer_file", "answer_sha256", "prompt_id", "stage", "branded", "intent_group", "observed_at",
    "service", "surface", "mode", "login", "region", "language", "repeat", "status", "sources_status",
    "valid_mention", "valid_citation", "exclusion_reason", "own_mentioned", "own_entities_mentioned",
    "own_mention_snippet", "own_cited", "own_first_source_order", "own_cited_urls", "source_count",
    "unresolved_sources", "competitors_mentioned", "competitors_cited", "accuracy", "reviewed_by", "warnings",
]
CIT_FIELDS = [
    "round", "answer_file", "prompt_id", "service", "surface", "login", "mode", "location", "source_order",
    "url", "host", "entity_id", "entity_kind",
]
REQUIRED_FIELDS = ("round", "prompt_id", "service", "surface", "login", "repeat")
# 同じ条件の回答の重複を調べる組
DUPLICATE_KEY = ("round", "prompt_id", "service", "surface", "login", "mode", "region", "language", "repeat")

# URL の終わりとみなす文字: 空白、<>"'`、全角のかっこ・かぎかっこ・引用符、[]{}|\^、全角の読点・句点。
# 半角の ( ) は URL に含まれうる（Wikipedia など）ので許し、clean_url_tail で対応の取れない ) を外す。
URL_RE = re.compile(
    r"https?://[^\s<>\"'`「」『』【】（）［］〈〉《》〔〕〘〙〚〛“”‘’｛｝｜\[\]{}|\\^、。，．]+", re.I)
# Markdown のリンク [文字](URL "タイトル")。グループは 1 リンクの文字、2 かっこの部分、3 URL。
# タイトルは "…"、'…'、(…) のどれか。URL の中のかっこは1段だけ許す（Wikipedia の A_(B) など）。
# ) の直後に日本語が続いても URL に含めないよう、ふつうの URL より先にこちらを拾う。
MD_LINK_RE = re.compile(
    r"\[([^\[\]\n]*)\]"
    r"(\(\s*<?(https?://(?:[^\s()<>]|\([^\s()<>]*\))+)>?"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\))", re.I)
# 参照形式のリンクの定義の行 [1]: URL "タイトル"。グループは 1 参照の名前、2 URL。
MD_REF_DEF_RE = re.compile(
    r"^[^\S\n]*\[([^\[\]\n]+)\]:[^\S\n]*<?(https?://[^\s<>]+)>?"
    r"(?:[^\S\n]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?[^\S\n]*$", re.I | re.M)
# 参照形式のリンク [文字][1]、[文字][]、[文字]。グループは 1 リンクの文字、2 参照の名前（なければ None）。
MD_REF_USE_RE = re.compile(r"\[([^\[\]\n]+)\](?:\[([^\[\]\n]*)\])?")
# URL の末尾から外す句読点（全角の ！？：； と、強調の * も外す）
TAIL_PUNCT = ".,;:!?・…！？：；*"
TRACKING_PARAMS = ("gclid", "fbclid", "srsltid", "yclid", "msclkid")
# 行き先を復元できない URL: (ホスト, パスの接頭辞)。ホストのサブドメインも対象
UNRESOLVED = (
    ("vertexaisearch.cloud.google.com", "/grounding-api-redirect/"),
    ("bing.com", "/ck/a"),
    ("bit.ly", "/"), ("t.co", "/"), ("lnkd.in", "/"), ("goo.gl", "/"),
    ("amzn.to", "/"), ("ow.ly", "/"), ("buff.ly", "/"), ("tinyurl.com", "/"),
)
DEFAULT_PORTS = {"http": 80, "https": 443}
_GOOGLE_HOST_RE = re.compile(r"^(?:www\.)?google\.[a-z]{2,3}(?:\.[a-z]{2})?$")
_AUTHORITY_RE = re.compile(r"^(https?://)([^/?#]*)", re.I)
# ## の見出しの行（### 以下は含めない）。NFKC の後の行に当てるので、全角の ＃ と空白も通る
_H2_LINE_RE = re.compile(r"^\s*##(?!#)(.*)$")
# 見出しの語の後ろに付けてよい補足（「:」「(3件)」など。NFKC の後なので全角の「：」「（）」も含む）
_HEADING_SUFFIX = r"\s*(?:(?::|\([^)]*\))\s*)*$"
_ANSWER_HEADING_RE = re.compile(r"^(?:回答|answer)" + _HEADING_SUFFIX)
_SOURCES_STRICT_RE = re.compile(r"^(?:出典|sources)" + _HEADING_SUFFIX)
# 出典の見出しとみなす語。「参考価格」のような AI の回答の見出しで切らないよう、見出しの全体で照合する
_SOURCES_WORD = (r"(?:出典(?:元|一覧|リンク|url|ページ)?|情報源"
                 r"|(?:参考|引用)(?:元|文献|資料|リンク|サイト|url|ページ)?"
                 r"|sources?|references?|citations?)")
_SOURCES_LIKE_RE = re.compile(
    r"^" + _SOURCES_WORD + r"(?:\s*(?:・|/|,|、|&|and)\s*" + _SOURCES_WORD + r")*" + _HEADING_SUFFIX)
# 出典の行の先頭の番号や記号（「1.」「-」「[1]」など）
_LIST_MARK_RE = re.compile(r"^(?:[-*+・•]|\d+[.)．）]|\[\d+\]|\(\d+\)|（\d+）)\s*")
_RULE_LINE_RE = re.compile(r"^[-*_=\s]*$")
# スキームのないドメインや URL（kakuu-coffee.example/menu）。ページ名の行とは区別して警告する
_SCHEMELESS_URL_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9](?::\d+)?(?:[/?#]\S*)?$", re.I)
# ドメインだけの文字（kakuucoffee.example）
_DOMAIN_LABEL_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]$")
_DASH_RE = re.compile("[‐-―−]")
_WS_RE = re.compile(r"\s+")
# observed_at の先頭の日付（2026-10-01、2026/10/1、2026.10.01、2026年10月1日）
_NUMERIC_DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_JA_DATE_RE = re.compile(r"^(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
_DIGITS_RE = re.compile(r"^[0-9]+$")


# ---------------------------------------------------------------------------
# 回答ファイルの欄

def _heading_kind(line):
    # type: (str) -> object
    """
    ## の見出しの行の種類を返す。見出しの行でなければ None。
      "answer"          回答の見出し（回答 / Answer）
      "sources-strict"  出典の見出し（出典 / Sources）
      "sources"         出典とみなす見出し（参考、参考文献、引用元、References など）
      "other"           そのほかの ## の見出し（AI の回答そのものの見出しなど）
    全角の ＃ と空白、見出しの語の後ろの「:」「（3件）」、末尾の閉じの # を受け付ける。
    """
    match = _H2_LINE_RE.match(unicodedata.normalize("NFKC", line or ""))
    if not match:
        return None
    rest = match.group(1)
    title = rest.rstrip()
    if title.endswith("#"):
        without = title.rstrip("#")
        if not without or without[-1].isspace():
            title = without  # 末尾の閉じの #（「## 出典 ##」）を外す
    title = title.strip().casefold()
    if _ANSWER_HEADING_RE.match(title):
        return "answer"
    if _SOURCES_STRICT_RE.match(title):
        return "sources-strict"
    if _SOURCES_LIKE_RE.match(title):
        return "sources"
    if not rest or rest[0].isspace():
        return "other"
    return None  # 「##タグ」のように ## の直後に文字が続くものは見出しとみなさない


def split_sections(body):
    # type: (str) -> tuple
    """
    本文から (回答の欄, 出典の欄) を取り出す。見出しがなければ None。
    回答の欄は、最初の回答の見出しの次の行から。AI の回答そのものにある ## の見出し（"other"）では切らず、
    その行も回答の欄に含める。出典の見出し（"sources-strict" と "sources"）の下は出典の欄に入れ、
    複数あればつなげる。「## 出典」の見出しより後ろの "other" の見出しの下（メモなど）と、
    2つ目の回答の見出しより後ろは、どちらの欄にも入れない。
    """
    lines = (body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    answer = None  # type: object
    sources = None  # type: object
    state = "before"  # before: 回答の見出しの前、answer: 回答の欄の中、after: 回答の欄が終わった後
    target = None  # 見出しでない行を入れる先
    for line in lines:
        kind = _heading_kind(line)
        if kind is None:
            if target == "answer":
                answer.append(line)
            elif target == "sources":
                sources.append(line)
            continue
        if kind == "answer":
            if answer is None:
                answer = []
                state = target = "answer"
            else:
                state, target = "after", None
        elif kind in ("sources-strict", "sources"):
            if sources is None:
                sources = []
            target = "sources"
            if kind == "sources-strict" and state == "answer":
                state = "after"
        elif state == "answer":
            answer.append(line)
            target = "answer"
        else:
            target = None
    return ("\n".join(answer) if answer is not None else None,
            "\n".join(sources) if sources is not None else None)


def _has_level2_heading(text):
    # type: (str) -> bool
    """回答の欄に、AI の回答そのものの ## の見出しがあるか。"""
    return any(_heading_kind(line) == "other" for line in (text or "").split("\n"))


# ---------------------------------------------------------------------------
# URL の抽出と正規化

def clean_url_tail(url):
    # type: (str) -> str
    """末尾の句読点を外す。閉じかっこ ) は、URL の中の ( の数より多いときだけ外す。"""
    while url:
        last = url[-1]
        if last in TAIL_PUNCT:
            url = url[:-1]
        elif last == ")" and url.count(")") > url.count("("):
            url = url[:-1]
        else:
            break
    return url


def _cut_unbalanced_paren(url):
    # type: (str) -> str
    """
    対応する ( のない ) があれば、その手前で切る。「サイト(https://a.example/x)の情報」のように、
    半角のかっこの直後に日本語が続いても、URL にその日本語を含めないため。A_(B) のような対のかっこは残す。
    """
    depth = 0
    for i, ch in enumerate(url):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return url[:i]
            depth -= 1
    return url


def _trim_host_bleed(url):
    # type: (str) -> str
    """
    スキームの後ろのホスト名に、英数字のドメインに続けて日本語が付いていたら（「https://a.exampleをご覧」）、
    日本語の手前で切る。日本語のドメイン（https://日本語.jp）はそのまま残す。
    """
    match = _AUTHORITY_RE.match(url)
    if not match:
        return url
    authority = match.group(2)
    for i, ch in enumerate(authority):
        if not ch.isascii():
            prefix = authority[:i]
            if "." in prefix and prefix[-1].isascii() and prefix[-1].isalnum():
                return url[:match.start(2) + i]
            return url
    return url


def _has_host(url):
    # type: (str) -> bool
    """ホスト名のある URL なら True。https:// だけのものは URL とみなさない。"""
    try:
        return bool(urlsplit(url).hostname)
    except ValueError:
        return True  # 解釈できない URL は残し、normalize_url で行き先不明にする


def _bare_host(value):
    # type: (str) -> str
    value = unicodedata.normalize("NFKC", value or "").strip().lower().rstrip("/").rstrip(".")
    return value[4:] if value.startswith("www.") else value


def _is_domain_label(label, url):
    # type: (str, str) -> bool
    """リンクの文字が、リンク先（Google の /url なら行き先）のドメインだけなら True。"""
    label_host = _bare_host(label)
    if not label_host:
        return False
    hosts = set()
    try:
        hosts.add(_bare_host(urlsplit(url).hostname or ""))
    except ValueError:
        pass
    hosts.add(_bare_host(normalize_url(url)[1]))
    hosts.discard("")
    return label_host in hosts


def _looks_like_domain(label):
    # type: (str) -> bool
    """文字がドメインの形（kakuucoffee.example）だけなら True。"""
    return bool(_DOMAIN_LABEL_RE.match(_bare_host(label)))


def _ref_key(value):
    # type: (str) -> str
    """参照形式のリンクの名前を比べるための形（大文字・小文字と空白の違いを無視する）。"""
    return _WS_RE.sub(" ", unicodedata.normalize("NFKC", value or "").strip()).casefold()


def _cut_at_known_prefix(url, known_urls):
    # type: (str, object) -> str
    """
    URL の途中から日本語などの ASCII でない文字が続き、その手前までが known_urls のどれかと同じなら、
    そこで切る（「https://a.example/x架空珈琲が人気」の「架空珈琲が人気」を URL に含めないため）。
    いちばん長く一致するものを使う。出典の欄にトップページの URL（https://a.example/）しかなく、本文に
    日本語のパスの URL（https://a.example/メニュー）があると、トップページで切ってしまう。ホストは同じなので、
    どの entity の引用かの判定は変わらない。
    """
    best = 0
    for known in known_urls:
        n = len(known)
        if n > best and len(url) > n and not url[n].isascii() and url[:n].lower() == known.lower():
            best = n
    return url[:best] if best else url


def _mask(text, spans):
    # type: (str, list) -> str
    """範囲の文字を空白にする（改行は残す）。位置を変えないよう、同じ長さのまま置き換える。"""
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def _scan_links(text, known_urls=None):
    # type: (str, object) -> tuple
    """
    本文の中の URL とリンクを調べ、(URL の一覧（出現順）, 言及の照合の前に空白にする範囲の一覧) を返す。
    次の順に拾い、拾った部分を空白で隠してから次を探す。
      1. 参照形式のリンクの定義の行（[1]: URL "タイトル"）。行ごと消す。
      2. インラインのリンク [文字](URL "タイトル")。かっこの部分を消し、文字がリンク先のドメインだけなら文字も消す。
      3. 参照形式のリンク [文字][1]。[1] の部分を消し、文字がリンク先のドメインだけなら文字も消す。
         定義が見つからないときは、文字がドメインの形なら消す（出典の表示とみなす）。
      4. ふつうの URL。対応する ( のない ) の手前で切り、末尾の句読点を外す。known_urls があれば、
         _cut_at_known_prefix で後ろに続く日本語を外す。
    ホスト名のない URL（https:// だけ）は URL とみなさない。
    """
    text = text or ""
    found = []  # (開始, URL)
    cuts = []  # (開始, 終了)

    definitions = {}
    def_spans = []
    for match in MD_REF_DEF_RE.finditer(text):
        url = clean_url_tail(match.group(2))
        if url and _has_host(url):
            found.append((match.start(2), url))
            definitions.setdefault(_ref_key(match.group(1)), url)
        def_spans.append(match.span())
    cuts.extend(def_spans)
    masked = _mask(text, def_spans)

    link_spans = []
    for match in MD_LINK_RE.finditer(masked):
        url = clean_url_tail(match.group(3))
        if url and _has_host(url):
            found.append((match.start(3), url))
            if _is_domain_label(match.group(1), url):
                cuts.append(match.span(1))
        link_spans.append(match.span(2))
    cuts.extend(link_spans)
    masked = _mask(masked, link_spans)

    for match in MD_REF_USE_RE.finditer(masked):
        label, ref = match.group(1), match.group(2)
        url = definitions.get(_ref_key(ref if ref else label))
        if ref is None and url is None:
            continue  # 定義のない [1] は番号などで、リンクではない
        if ref is not None:
            cuts.append((match.end(1) + 1, match.end()))  # [1] の部分
        if (_is_domain_label(label, url) if url is not None else _looks_like_domain(label)):
            cuts.append(match.span(1))

    for match in URL_RE.finditer(masked):
        url = clean_url_tail(_trim_host_bleed(_cut_unbalanced_paren(match.group(0))))
        if url and known_urls:
            url = _cut_at_known_prefix(url, known_urls)
        if url and _has_host(url):
            found.append((match.start(), url))
            cuts.append((match.start(), match.start() + len(url)))

    found.sort(key=lambda item: item[0])
    return [url for _, url in found], cuts


def extract_urls(text, known_urls=None):
    # type: (str, object) -> list
    """
    本文の中の URL を出現順に返す（重複はそのまま）。スキームのないドメインは URL とみなさない。
    known_urls（出典の欄の URL）を渡すと、URL の後ろに空白なしで続く日本語を、そこで切る（回答の欄にだけ使う）。
    """
    return _scan_links(text, known_urls)[0]


def strip_urls(text, known_urls=None):
    # type: (str, object) -> str
    """
    言及の照合の前に、本文の URL を空白に置き換える。Markdown のリンクは URL とタイトルを消し、
    リンクの文字は残す。参照形式のリンクの定義の行はまるごと消す。リンクの文字がリンク先のドメインだけなら
    （ChatGPT の出典の表示など）、その文字も消す。known_urls は extract_urls と同じ。
    """
    text = text or ""
    cuts = sorted(_scan_links(text, known_urls)[1])
    out = []
    last = 0
    for start, end in cuts:
        if start < last:
            last = max(last, end)  # 重なる範囲はまとめて消す
            continue
        out.append(text[last:start])
        out.append(" ")
        last = end
    out.append(text[last:])
    return "".join(out)


def _strip_tracking(query):
    # type: (str) -> str
    """クエリから utm_ で始まるキーと追跡用のキーを外す。残りの順番と書き方はそのまま。"""
    kept = []
    for part in query.split("&"):
        if not part:
            continue
        key = unquote_plus(part.split("=", 1)[0]).strip().lower()
        if key.startswith("utm_") or key in TRACKING_PARAMS:
            continue
        kept.append(part)
    return "&".join(kept)


def _google_target(query):
    # type: (str) -> str
    """Google の /url のクエリから、行き先の URL（q か url）を取り出す。なければ空。"""
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key in ("q", "url") and value.strip().lower().startswith(("http://", "https://")):
            return value.strip()
    return ""


def _is_unresolved_redirect(host, path):
    # type: (str, str) -> bool
    for domain, prefix in UNRESOLVED:
        if host_matches(host, domain) and (path or "/").startswith(prefix):
            return True
    return False


def normalize_url(url):
    # type: (str) -> tuple
    """
    (照合用の URL, ホスト, 行き先不明か) を返す。スキームとホストを小文字に、既定のポートと
    フラグメントと追跡用のパラメータを外す。Google の /url は行き先に戻す（1回だけ）。
    解釈できない URL は (元の文字列, "", True)。
    """
    return _normalize_url(url, True)


def _normalize_url(url, follow_google):
    # type: (str, bool) -> tuple
    raw = (url or "").strip()
    try:
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").rstrip(".")
        port = parts.port
    except ValueError:
        return raw, "", True
    if not host:
        return raw, "", True
    unresolved = False
    if follow_google and _GOOGLE_HOST_RE.match(host) and parts.path == "/url":
        target = _google_target(parts.query)
        if target:
            return _normalize_url(target, False)
        unresolved = True  # 行き先の書かれていない Google の /url
    if _is_unresolved_redirect(host, parts.path):
        unresolved = True
    netloc = "[" + host + "]" if ":" in host else host
    if port is not None and port != DEFAULT_PORTS.get(scheme):
        netloc += ":" + str(port)
    query = _strip_tracking(parts.query)
    match_url = scheme + "://" + netloc + (parts.path or "/") + ("?" + query if query else "")
    return match_url, host, unresolved


def host_matches(host, domain):
    # type: (str, str) -> bool
    """ホストがドメインと同じか、そのサブドメインなら True。"""
    if not host or not domain:
        return False
    return host == domain or host.endswith("." + domain)


def _match_entity(host, entities):
    # type: (str, list) -> object
    """ホストに当たる entity を返す。いちばん長いドメインを優先し、同じ長さなら自社、entities.csv の順。"""
    best = None
    best_len = -1
    for kind in ("own", "competitor"):
        for entity in entities:
            if entity["kind"] != kind:
                continue
            for domain in entity["domains"]:
                if host_matches(host, domain) and len(domain) > best_len:
                    best = entity
                    best_len = len(domain)
    return best


# ---------------------------------------------------------------------------
# 言及の判定

def _is_word_char(ch):
    # type: (str) -> bool
    return ch.isascii() and ch.isalnum()


def find_mentions(text_norm, entity):
    # type: (str, dict) -> list
    """
    正規化した本文（normalize_text(strip_urls(回答))）から entity の表記を探し、
    (開始, 終了, 表記) の一覧を位置の順で返す。英数字の境界と除外語を考える。
    """
    spans = []
    excludes = []
    for ex in entity["exclude_terms"]:
        ex_n = common.normalize_text(ex)
        start = text_norm.find(ex_n) if ex_n else -1
        while start >= 0:
            excludes.append((start, start + len(ex_n)))
            start = text_norm.find(ex_n, start + 1)
    for term in entity["terms"]:
        term_n = common.normalize_text(term)
        if not term_n:
            continue
        start = text_norm.find(term_n)
        while start >= 0:
            end = start + len(term_n)
            ok = True
            if _is_word_char(term_n[0]) and start > 0 and _is_word_char(text_norm[start - 1]):
                ok = False
            if _is_word_char(term_n[-1]) and end < len(text_norm) and _is_word_char(text_norm[end]):
                ok = False
            if ok and any(s <= start and end <= e for s, e in excludes):
                ok = False
            if ok:
                spans.append((start, end, term))
            start = text_norm.find(term_n, start + 1)
    spans.sort()
    return spans


def _display_text(text):
    # type: (str) -> str
    """抜粋を見せるための表記。normalize_text から大文字・小文字の統一だけを除いたもの。"""
    text = unicodedata.normalize("NFKC", text or "")
    return _WS_RE.sub(" ", _DASH_RE.sub("-", text))


# ---------------------------------------------------------------------------
# 欄の値

def _loose(value):
    # type: (str) -> str
    return _WS_RE.sub("", unicodedata.normalize("NFKC", value or "")).casefold()


def _canonical(value, allowed):
    # type: (str, tuple) -> str
    """全角・半角、大文字・小文字、空白の違いだけなら、決まった値の書き方にそろえる。"""
    value = (value or "").strip()
    if not value or value in allowed:
        return value
    key = _loose(value)
    for candidate in allowed:
        if candidate and _loose(candidate) == key:
            return candidate
    return value


def _parse_repeat(value):
    # type: (str) -> object
    """repeat を正の整数の文字列にする。正の整数でなければ None。"""
    value = unicodedata.normalize("NFKC", value or "").strip()
    if _DIGITS_RE.match(value) and int(value) >= 1:
        return str(int(value))
    return None


def _round_from_path(rel_path):
    # type: (str) -> str
    """answers/<ラウンド>/... の形のパスから、ラウンドのフォルダ名を取り出す。なければ空。"""
    parts = rel_path.replace("\\", "/").split("/")
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] == "answers" and i + 1 < len(parts) - 1:
            return parts[i + 1]
    return ""


def _url_on_next_line(lines, index):
    # type: (list, int) -> bool
    """次の空でない行が、番号や記号なしで URL を含むなら True（ページ名の行と URL の行に分かれた出典）。"""
    for line in lines[index + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        return not _LIST_MARK_RE.match(stripped) and bool(extract_urls(stripped))
    return False


def _count_urlless_source_lines(sources):
    # type: (str) -> int
    """
    出典の欄の、URL を含まない行を数える。空の行、「-」だけの行、コメントは数えない。
    ページ名の行の次の行に（番号や記号なしで）URL があれば、同じ出典の続きとみなして数えない。
    スキームのないドメイン（kakuu-coffee.example/menu）の行は、次の行に URL があっても数える。
    """
    lines = (sources or "").split("\n")
    count = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        content = _LIST_MARK_RE.sub("", stripped).strip()
        if not content or _RULE_LINE_RE.match(content):
            continue
        if extract_urls(line):
            continue
        if not _SCHEMELESS_URL_RE.match(content) and _url_on_next_line(lines, i):
            continue
        count += 1
    return count


def _normalize_observed_at(value):
    # type: (str) -> tuple
    """
    observed_at の先頭の日付を YYYY-MM-DD にそろえ、(そろえた値, 日付を読めたか) を返す。
    「2026/10/01 14:05」「2026-10-1」「2026年10月1日」も読む。compare_runs.py は先頭が YYYY-MM-DD の
    値だけを日付として数えるので、ここで形をそろえる。読めなければ元の値をそのまま返す。
    """
    text = unicodedata.normalize("NFKC", value or "").strip()
    match = _NUMERIC_DATE_RE.match(text) or _JA_DATE_RE.match(text)
    if not match:
        return value, False
    try:
        date = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return value, False
    rest = text[match.end():]
    if rest and not rest[0].isspace() and rest[0] != "T":
        rest = " " + rest  # 「2026年10月1日9:00」の日付と時刻の間に空白を入れる
    return date.isoformat() + rest, True


def _os_reason(exc):
    # type: (OSError) -> str
    return exc.strerror or str(exc)


# ---------------------------------------------------------------------------
# 1つの回答ファイルの処理

def process_answer(path, rel_path, entities, prompts, round_hint=None):
    # type: (str, str, list, object, object) -> tuple
    """
    回答ファイル1つを読み、(observations.csv の行, citations.csv の行の一覧, 警告の一覧) を返す。
    rel_path は作業フォルダからの相対パス（/ 区切り）。prompts は load_prompts の結果か None。
    round_hint はラウンドのフォルダ名（省略すると rel_path の answers/<ラウンド>/ から取る）。
    ファイルを読めなければ（壊れたシンボリックリンク、権限がないなど）InputError を出す。
    """
    warnings = []
    try:
        text = common.read_text(path)
        answer_sha = common.sha256_file(path)[:12]
    except OSError as exc:
        raise common.InputError("回答ファイルを読めません: {}（{}）。ファイルがあるか、読み取りの権限があるかを"
                                "確かめてください".format(rel_path, _os_reason(exc)))
    meta, body, fm_errors = common.parse_front_matter(text)
    warnings.extend(fm_errors)
    if "�" in text:
        warnings.append("読めない文字を置き換えました（文字コードを確かめてください）")

    def field(name):
        return (meta.get(name) or "").strip()

    # ラウンド
    folder_round = round_hint if round_hint is not None else _round_from_path(rel_path)
    round_name = field("round")
    if not round_name and folder_round:
        round_name = folder_round
        warnings.append("round の欄が空なので、フォルダ名 {} を使いました".format(folder_round))
    elif round_name and folder_round and round_name != folder_round:
        warnings.append("round の欄（{}）とフォルダ名（{}）が違います".format(round_name, folder_round))

    # 必須の欄
    prompt_id = field("prompt_id")
    service = _canonical(field("service"), common.SERVICES)
    surface = _canonical(field("surface"), common.SURFACES)
    login = _canonical(field("login"), common.LOGINS)
    repeat_raw = field("repeat")
    repeat = _parse_repeat(repeat_raw)
    checks = (
        ("round", round_name, bool(common.ID_RE.match(round_name)), "英数字で始まり、英数字・ハイフン・下線だけ"),
        ("prompt_id", prompt_id, bool(common.ID_RE.match(prompt_id)), "英数字で始まり、英数字・ハイフン・下線だけ"),
        ("service", service, service in common.SERVICES, " / ".join(common.SERVICES)),
        ("surface", surface, surface in common.SURFACES, " / ".join(common.SURFACES)),
        ("login", login, login in common.LOGINS, " / ".join(common.LOGINS)),
        ("repeat", repeat_raw, repeat is not None, "1 以上の整数"),
    )
    missing = []
    invalid = []
    for name, value, ok, allowed in checks:
        if not value:
            missing.append(name)
        elif not ok:
            invalid.append(name)
            warnings.append("{} の値が不正です: {}（使える値: {}）".format(name, value, allowed))

    # 状態と、決まった値のある欄
    status = _canonical(field("status"), common.STATUS_VALUES)
    if status not in common.STATUS_VALUES:
        warnings.append("status の値が決まった値ではありません: {}".format(status))
    sources_status = _canonical(field("sources_status"), common.SOURCES_STATUS_VALUES)
    if sources_status not in common.SOURCES_STATUS_VALUES:
        warnings.append("sources_status の値が決まった値ではありません: {}（引用率の分母に入れません）".format(
            sources_status))
    accuracy = _canonical(field("accuracy"), common.ACCURACY_VALUES) or "未確認"
    if accuracy not in common.ACCURACY_VALUES:
        warnings.append("accuracy の値が決まった値ではありません: {}".format(accuracy))
    reviewed_by = _canonical(field("reviewed_by"), common.REVIEWED_BY_VALUES)
    if reviewed_by not in common.REVIEWED_BY_VALUES:
        warnings.append("reviewed_by の値が決まった値ではありません: {}".format(reviewed_by))

    # 回答と出典の欄
    answer, sources = split_sections(body)
    if answer is None:
        warnings.append("## 回答 の見出しがありません")
    answer_text = answer or ""
    has_answer = bool(answer_text.strip())
    source_urls = extract_urls(sources or "")
    # 回答の欄の URL の後ろに空白なしで続く日本語を切るために、出典の欄の URL（と正規化した形）を渡す
    known_urls = set(source_urls)
    known_urls.update(normalize_url(url)[0] for url in source_urls)
    body_urls = extract_urls(answer_text, known_urls)
    if (answer is not None and sources is None and sources_status != "なし"
            and _has_level2_heading(answer_text)):
        warnings.append("## 出典 の見出しが見つかりません（回答の欄に ## の見出しがあります。出典の見出しを"
                        "「## 出典」にしてください）")
    if not status:
        status = "記録済み" if has_answer else "未記入"
    if not sources_status:
        sources_status = "記録済み" if (source_urls or body_urls) else "不明"
    if status in ("AI の回答なし", "未記入") and has_answer:
        warnings.append("status が {} ですが、回答の欄に文字があります（status を確かめてください）".format(status))
    if sources_status == "なし" and source_urls:
        warnings.append("sources_status が なし ですが、出典の欄に URL があります（sources_status を確かめてください）")
    urlless = _count_urlless_source_lines(sources)
    if urlless:
        warnings.append("URL のない出典の行が {} 行あります（URL を貼るか、sources_status を書いてください）".format(
            urlless))

    # 有効かどうか
    reasons = []
    if status != "記録済み":
        reasons.append("status が {}".format(status))
    if missing:
        reasons.append("必須の欄がない: " + ", ".join(missing))
    if invalid:
        reasons.append("値が不正: " + ", ".join(invalid))
    if answer is None:
        reasons.append("## 回答 の見出しがない")
    elif status == "記録済み" and not has_answer:
        reasons.append("回答が空")
    valid_mention = 0 if reasons else 1
    valid_citation = 0
    if valid_mention:
        if sources_status == "不明":
            reasons.append("出典が不明")
        elif sources_status not in common.SOURCES_STATUS_VALUES:
            reasons.append("sources_status の値が不正")
        else:
            valid_citation = 1

    observed_raw = field("observed_at")
    observed_at, date_ok = _normalize_observed_at(observed_raw)
    if valid_mention and not date_ok:
        hint = "YYYY-MM-DD の形で書いてください。前後の期間で観測した日数を比べるのに使います"
        if observed_raw:
            warnings.append("observed_at の日付を読めません: {}（{}）".format(observed_raw, hint))
        else:
            warnings.append("observed_at に日付がありません（{}）".format(hint))

    # 言及
    stripped = strip_urls(answer_text, known_urls)
    text_norm = common.normalize_text(stripped)
    display = _display_text(stripped)
    if len(display) != len(text_norm):
        display = text_norm  # 大文字・小文字の統一で長さが変わる文字があるときは、正規化した本文から抜き出す
    own_mentioned_ids = []
    comp_mentioned_ids = []
    first_span = None
    for entity in entities:
        spans = find_mentions(text_norm, entity)
        if not spans:
            continue
        if entity["kind"] == "own":
            own_mentioned_ids.append(entity["entity_id"])
            if first_span is None or spans[0][0] < first_span[0]:
                first_span = spans[0]
        else:
            comp_mentioned_ids.append(entity["entity_id"])
    snippet = ""
    if first_span is not None:
        snippet = display[max(0, first_span[0] - 20):first_span[1] + 20].strip()

    # 引用
    base = {
        "round": round_name, "answer_file": rel_path, "prompt_id": prompt_id, "service": service,
        "surface": surface, "login": login, "mode": field("mode"),
    }
    citations = []
    seen = set()
    for location, urls in (("sources", source_urls), ("body", body_urls)):
        for url in urls:
            match_url, host, unresolved = normalize_url(url)
            if match_url in seen:
                continue
            seen.add(match_url)
            if unresolved:
                entity_id, entity_kind = "", "unresolved"
            else:
                entity = _match_entity(host, entities)
                entity_id, entity_kind = (entity["entity_id"], entity["kind"]) if entity else ("", "other")
            row = dict(base)
            row.update({
                "location": location,
                "source_order": "",
                "url": match_url,
                "host": host,
                "entity_id": entity_id,
                "entity_kind": entity_kind,
            })
            citations.append(row)
    order = 0
    for row in citations:
        if row["location"] == "sources":
            order += 1
            row["source_order"] = order

    own_rows = [c for c in citations if c["entity_kind"] == "own"]
    own_orders = [c["source_order"] for c in own_rows if c["location"] == "sources"]
    cited_comp = set(c["entity_id"] for c in citations if c["entity_kind"] == "competitor")
    competitors_cited = [e["entity_id"] for e in entities if e["kind"] == "competitor" and e["entity_id"] in cited_comp]
    source_rows = [c for c in citations if c["location"] == "sources"]

    # prompts.csv との結合
    stage = branded = intent_group = ""
    if prompts is not None and prompt_id:
        prompt_row = prompts.get(prompt_id)
        if prompt_row is None:
            warnings.append("prompts.csv にない prompt_id です: {}".format(prompt_id))
        else:
            stage = prompt_row.get("stage", "")
            branded = prompt_row.get("branded", "")
            intent_group = prompt_row.get("intent_group", "")
            meta_prompt = field("prompt")
            if meta_prompt and (common.normalize_text(meta_prompt).strip()
                                != common.normalize_text(prompt_row.get("prompt", "")).strip()):
                warnings.append("prompt の欄が prompts.csv と違います（途中で直していませんか）")

    obs = {
        "round": round_name,
        "answer_file": rel_path,
        "answer_sha256": answer_sha,
        "prompt_id": prompt_id,
        "stage": stage,
        "branded": branded,
        "intent_group": intent_group,
        "observed_at": observed_at,
        "service": service,
        "surface": surface,
        "mode": field("mode"),
        "login": login,
        "region": field("region"),
        "language": field("language") or "ja",
        "repeat": repeat if repeat is not None else repeat_raw,
        "status": status,
        "sources_status": sources_status,
        "valid_mention": valid_mention,
        "valid_citation": valid_citation,
        "exclusion_reason": "; ".join(reasons),
        "own_mentioned": 1 if own_mentioned_ids else 0,
        "own_entities_mentioned": "|".join(own_mentioned_ids),
        "own_mention_snippet": snippet,
        "own_cited": 1 if own_rows else 0,
        "own_first_source_order": min(own_orders) if own_orders else "",
        "own_cited_urls": "|".join(c["url"] for c in own_rows),
        "source_count": len(source_rows),
        "unresolved_sources": len([c for c in source_rows if c["entity_kind"] == "unresolved"]),
        "competitors_mentioned": "|".join(comp_mentioned_ids),
        "competitors_cited": "|".join(competitors_cited),
        "accuracy": accuracy,
        "reviewed_by": reviewed_by,
        "warnings": " / ".join(warnings),
    }
    return obs, citations, warnings


# ---------------------------------------------------------------------------
# コマンドライン

def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = common.ArgumentParser(
        prog=SCRIPT_NAME,
        description="回答ファイル（answers/ の下の .md）を読み、observations.csv・citations.csv・"
                    "observations.run.json を作り直す。",
        epilog="例:\n"
               "  python3 normalize_observations.py\n"
               "  python3 normalize_observations.py --workspace ai-search --rounds 2026-10-01,2026-10-08\n"
               "\n"
               "出力は毎回上書きする。--rounds を付けると、出力には指定したラウンドだけが入る。\n"
               "終了コード: 0 成功、2 入力や引数の誤り（回答ファイルを読めない、出力を書けないを含む）、\n"
               "1 想定外のエラー。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default="ai-search", help="観測データのフォルダ（既定: ai-search。作業フォルダの中の ai-search/）")
    parser.add_argument("--rounds", default="", help="対象のラウンド（カンマ区切り）。省略するとすべて")
    parser.add_argument("--entities", help="entities.csv のパス（既定: <workspace>/entities.csv）")
    parser.add_argument("--prompts", help="prompts.csv のパス（既定: <workspace>/prompts.csv。なければ結合しない）")
    parser.add_argument("--answers", help="回答ファイルのフォルダ（既定: <workspace>/answers）")
    parser.add_argument("--out-dir", help="出力先のフォルダ（既定: <workspace>）")
    return parser


def _list_answer_files(answers_dir):
    # type: (str) -> list
    """
    answers/ の下の .md を (絶対パス, answers/ からの相対パス) の一覧で返す。. で始まるものは無視する。
    読めないフォルダがあれば InputError にする（回答を黙って落とさないため）。
    """
    def fail(exc):
        raise common.InputError("回答ファイルのフォルダを読めません: {}（{}）".format(exc.filename, _os_reason(exc)))

    found = []
    for dirpath, dirnames, filenames in os.walk(answers_dir, onerror=fail):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in filenames:
            if name.startswith(".") or not name.lower().endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, answers_dir).replace(os.sep, "/")
            found.append((path, rel))
    return found


def _rel_to_workspace(path, workspace):
    # type: (str, str) -> str
    try:
        return os.path.relpath(path, workspace).replace(os.sep, "/")
    except ValueError:  # Windows でドライブが違うとき
        return os.path.abspath(path).replace(os.sep, "/")


def _write_output(path, write):
    # type: (str, object) -> None
    """出力ファイルを書く。書けなければ（Excel で開いている、権限がないなど）InputError にする。"""
    try:
        write()
    except OSError as exc:
        raise common.InputError("{} を書けません（Excel などで開いていれば閉じてください）: {}（{}）".format(
            os.path.basename(path), path, _os_reason(exc)))


def _rate(k, n):
    # type: (int, int) -> str
    if not n:
        return "{}/{}".format(k, n)
    return "{}/{}（{:.1f}%）".format(k, n, 100.0 * k / n)


def _run(args):
    # type: (argparse.Namespace) -> int
    workspace = args.workspace
    entities_path = args.entities or os.path.join(workspace, "entities.csv")
    prompts_path = args.prompts or os.path.join(workspace, "prompts.csv")
    answers_dir = args.answers or os.path.join(workspace, "answers")
    out_dir = args.out_dir or workspace
    rounds = common.parse_id_list(args.rounds)

    if not os.path.isfile(entities_path):
        raise common.InputError("entities.csv がありません: {}（自社と競合の表記ゆれ・ドメインを先に書いてください。"
                                "手順書 01-setup.md）".format(entities_path))
    entities = common.load_entities(entities_path)
    prompts = None
    if os.path.isfile(prompts_path):
        prompts = common.load_prompts(prompts_path)
    else:
        common.log("警告: prompts.csv がないので、stage・branded・intent_group を空にします: {}".format(prompts_path))
    if not os.path.isdir(answers_dir):
        raise common.InputError("回答ファイルのフォルダがありません: {}（new_round.py でひな形を作れます）".format(
            answers_dir))
    files = _list_answer_files(answers_dir)
    if not files:
        raise common.InputError("回答ファイル（.md）が1つもありません: {}（new_round.py でひな形を作れます）".format(
            answers_dir))

    items = []
    dropped = []  # --rounds のフォルダにあるのに、round の欄が違うので外した回答
    for path, rel_answers in files:
        parts = rel_answers.split("/")
        round_hint = parts[0] if len(parts) >= 2 else ""
        rel_ws = _rel_to_workspace(path, workspace)
        obs, cits, warnings = process_answer(path, rel_ws, entities, prompts, round_hint=round_hint)
        if rounds and obs["round"] not in rounds:
            if round_hint in rounds:
                dropped.append(rel_ws)
            continue
        items.append((obs, cits, warnings))
    items.sort(key=lambda item: item[0]["answer_file"])
    if dropped:
        common.log("警告: --rounds で指定したラウンドのフォルダにあるのに、round の欄が違うので外した回答が {} 件あります"
                   "（{}）。前のラウンドからコピーしたときは round の欄を直してください".format(
                       len(dropped), ", ".join(dropped)))
    if not items:
        raise common.InputError("指定したラウンドの回答ファイルがありません: {}".format(", ".join(rounds)))

    # 同じ条件の回答の重複（必須の欄がそろっている回答だけを調べる）
    groups = {}
    for obs, _, _ in items:
        if all(str(obs[name]) for name in REQUIRED_FIELDS):
            groups.setdefault(tuple(str(obs[name]) for name in DUPLICATE_KEY), []).append(obs)
    for obs, _, warnings in items:
        if not all(str(obs[name]) for name in REQUIRED_FIELDS):
            continue
        group = groups[tuple(str(obs[name]) for name in DUPLICATE_KEY)]
        if len(group) > 1:
            others = [o["answer_file"] for o in group if o is not obs]
            warnings.append("同じ条件の回答が重複しています（{}）".format(", ".join(others)))
            obs["warnings"] = " / ".join(warnings)

    observations = [item[0] for item in items]
    citations = [c for item in items for c in item[1]]

    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise common.InputError("出力先のフォルダを作れません: {}（{}）。同じ名前のファイルがないか確かめてください".format(
            out_dir, _os_reason(exc)))
    obs_path = os.path.join(out_dir, "observations.csv")
    cit_path = os.path.join(out_dir, "citations.csv")
    run_path = os.path.join(out_dir, "observations.run.json")
    _write_output(obs_path, lambda: common.write_csv(obs_path, OBS_FIELDS, observations))
    _write_output(cit_path, lambda: common.write_csv(cit_path, CIT_FIELDS, citations))

    valid_mention = [o for o in observations if o["valid_mention"] == 1]
    valid_citation = [o for o in observations if o["valid_citation"] == 1]
    round_names = sorted(set(o["round"] for o in observations if o["round"]))
    run_info = {
        "script": SCRIPT_NAME,
        "version": common.VERSION,
        "generated_at": datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "entities_sha256": common.sha256_file(entities_path),
        "prompts_sha256": common.sha256_file(prompts_path) if prompts is not None else None,
        "answer_files": len(observations),
        "valid_mention": len(valid_mention),
        "valid_citation": len(valid_citation),
        "rounds": round_names,
    }
    def write_run_info():
        with open(run_path, "w", encoding="utf-8") as f:
            json.dump(run_info, f, ensure_ascii=False, indent=2)
            f.write("\n")

    _write_output(run_path, write_run_info)

    # 要約と警告（標準エラー）
    for obs, _, warnings in items:
        for warning in warnings:
            common.log("警告: {}: {}".format(obs["answer_file"], warning))
    reason_counts = {}
    for obs in observations:
        for reason in [r for r in obs["exclusion_reason"].split("; ") if r]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    common.log("{} {}: 回答ファイル {} 件を読みました（ラウンド: {}）".format(
        SCRIPT_NAME, common.VERSION, len(observations), ", ".join(round_names) or "なし"))
    if rounds:
        common.log("  --rounds を指定したので、出力には指定したラウンドだけが入っています")
    common.log("  有効な回答: 言及の分母 {} 件、引用の分母 {} 件".format(len(valid_mention), len(valid_citation)))
    if reason_counts:
        common.log("  分母に入れなかった理由: " + "、".join(
            "{} {} 件".format(reason, count) for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1])))
    common.log("  自社の言及: {}（有効な回答だけ。全サービス・全条件の合計なので、比較には compare_runs.py を使う）".format(
        _rate(sum(o["own_mentioned"] for o in valid_mention), len(valid_mention))))
    common.log("  自社の引用: {}".format(_rate(sum(o["own_cited"] for o in valid_citation), len(valid_citation))))
    common.log("  警告のある回答: {} 件".format(len([1 for item in items if item[2]])))
    common.log("  書き出し: {}, {}, {}".format(obs_path, cit_path, run_path))
    return 0


def main(argv=None):
    # type: (object) -> int
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except common.InputError as exc:
        common.log("エラー: {}".format(exc))
        return 2
    except Exception:  # noqa: BLE001  想定外のエラーは終了コード 1
        common.log("想定外のエラーです。以下の内容を添えて報告してください。")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
