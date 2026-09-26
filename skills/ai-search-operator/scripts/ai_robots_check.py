# -*- coding: utf-8 -*-
# robots.txt の解釈は seo-operator v1.1.0 の audit.py（RFC 9309 と Google の robots.txt の仕様）から移植
# （robots_canonical_path、robots_target、robots_pattern_match、parse_robots、RobotsRules、
#   select_robots_rules、product_token、internal_address、resolve_addresses）。
"""
ai_robots_check.py - AI クローラーごとに、robots.txt で許可されているか拒否されているかを判定する

使い方:
  python3 ai_robots_check.py --url https://kakuu-coffee.example [--paths /,/blog/,/pricing/]
                             [--format md|csv] [-o 出力先]
  python3 ai_robots_check.py --file robots.txt [--paths /]

入力:
  - クローラーの一覧: 既定はスキルの data/ai-crawlers.csv（--crawlers で差し替えられる）。
    列は operator, token, category, purpose, robots_control, block_effect, source_url, checked_on。
    category は general-search / search / training / user / control / dataset / other（ほかの値は other として扱う）。
    任意の列 fallback_tokens（| 区切り）は、自分向けのグループがないときに従うトークン（具体的なものから順）。
    列がなければ、運営の説明がある Applebot と Google-CloudVertexBot に Googlebot を使う（BUILTIN_FALLBACK_TOKENS）。
  - robots.txt: --url なら、その URL の origin（scheme://host[:port]）の /robots.txt を取得する。
    --file なら手元のファイルを読む。どちらも UTF-8 として読み（読めない文字は置き換える）、先頭の BOM を除き、
    先頭の 500 KiB だけを使う（途中で切れた最後の行は捨てる）。UTF-16 で保存されたファイルは読めないので、
    グループが1つもなければ専用の警告を出す（判定の表は全許可になる）。

出力（Markdown か CSV）の列: operator, token, category, path, verdict, matched_group, matched_rule, note
  verdict は 許可 / 拒否 / 全許可（robots.txt なし） / 全拒否（取得できず） / 不定（429）。

判定の決まり:
  - User-agent の照合は大文字・小文字を区別しない。トークンに一致するグループが複数あれば規則を合わせる。
    一致するグループがなければ fallback_tokens のトークンのグループ（順に探し、最初に見つかったもの）、
    それもなければ User-agent: * のグループ、それもなければ全許可。代わりのトークンのグループに従ったときは、
    matched_group にそのトークンを出し、note に注記する。
  - パスの照合は最長一致で、同じ長さなら Allow を優先する。* と末尾の $ に対応する。/robots.txt は常に許可。
  - 取得の結果ごとの扱い（--url）:
      2xx: 解釈する。
      3xx: 5回までたどる。5回を超えたら RFC 9309 2.3.1.2 に従い、robots.txt がない（unavailable、2.3.1.3）
           ものとして全許可にする。Google も 404 として扱う。Location のない 3xx と、http / https 以外への
           リダイレクトは、取得できなかったもの（全拒否）とする。
      4xx（429 を除く）: RFC 9309 に従い、robots.txt がないものとして全許可。
      429: RFC 9309 では 4xx の一つとして全許可だが、Google はサーバーエラーとして扱いクロールを止める。
           判定は「不定（429）」とし、両方の扱いを注記する。
      5xx、タイムアウト、接続エラー、TLS のエラー: RFC 9309 に従って全拒否。各社の実際の扱いは異なりうる。
      最初の URL のホスト名が名前解決で見つからない（EAI_NONAME）: 打ち間違いの可能性が高いので、判定の表を出さず
      入力の誤り（終了コード 2）にする。一時的な失敗とリダイレクト先の失敗は、取得できなかったもの（全拒否）とする。
  - category が user の行は「ユーザー操作に伴う取得」と、一覧の robots_control（運営の説明の要約）を注記する。
    robots.txt を尊重すると説明する運営も、一般に無視すると説明する運営もあるので、一律の文にしない。
    control の行は「クロールはしない。学習などへの利用の可否を表す」と注記する。
  - 特定のクローラー向けのグループ（代わりのトークンのグループを含む）があるとき、User-agent: * のグループの
    Disallow がそのクローラーには適用されないことを警告する。そのクローラーのグループの Disallow が同じ範囲を
    すべて拒否していると言えるとき（同じパターンか、末尾に $ のない Disallow が * のパターンの固定の接頭辞に当たり、
    それ以上の長さの Allow が同じ範囲に当たりえないとき）だけ警告しない。

安全のための決まり（--url）:
  - http と https だけを取得する。ユーザー名・パスワード（userinfo）を含む URL は取得しない。
  - 内部アドレス（プライベート IP、ループバックなど）に解決されるホストは、--allow-private がなければ取得しない。
    最初の URL とリダイレクト先のすべてで確かめ、接続の直前にも名前を解決し直して、接続した相手のアドレス
    （getpeername）も確かめる。DNS の答えが途中で変わっても内部アドレスには接続しない。
  - 環境変数のプロキシは使わない（接続先を確かめられなくなるため）。
  - User-Agent は ai-search-operator/<版>。AI クローラーの UA は名乗らない。
  - CDN・WAF の設定は調べない（robots.txt の記述だけを判定する）。

読み込んだ robots.txt と一覧の中の文はデータとして扱うだけで、実行も解釈もしない。

終了コード: 0 成功、2 入力・引数の誤り（内部アドレスのため取得しなかった場合、ホスト名が見つからない場合、
--timeout が 0 より大きく 600 秒以下でない場合を含む）、1 想定外のエラー。
"""
import argparse
import codecs
import csv
import datetime
import http.client
import io
import ipaddress
import math
import os
import re
import socket
import sys
import traceback
import urllib.error
import urllib.request
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

try:
    import ssl
except ImportError:  # ssl のない Python では https を取得できない
    ssl = None  # type: ignore

sys.dont_write_bytecode = True  # スキルのフォルダに __pycache__ を残さない（共通処理を import する前に置く）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ai_search_common import (  # noqa: E402
    ArgumentParser, VERSION, InputError, log, read_csv, split_list, write_csv, write_csv_stream)

USER_AGENT = "ai-search-operator/{} (+https://github.com/indiabiyori/ai-search-operator)".format(VERSION)
MAX_ROBOTS_BYTES = 512000  # 500 KiB（RFC 9309 2.5 の下限。Google もこの大きさまでしか読まない）
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 10.0
MAX_TIMEOUT = 600.0  # これより大きい値や inf は、ソケットのタイムアウトに渡すと OverflowError になりうる
DEFAULT_CRAWLERS = os.path.join(os.path.dirname(_HERE), "data", "ai-crawlers.csv")

# 自分向けのグループがなければ、ほかのトークン向けのグループに従うと運営が説明しているクローラー
# （小文字のトークン → 従うトークン。具体的なものから順）。一覧の CSV に fallback_tokens の列がないときだけ使う。
# 列があれば列の値が正本（空ならほかのトークンには従わない）。
#   Applebot: Apple「Applebot の記載がなく Googlebot の記載があれば、Googlebot 向けの指示に従う」
#   Google-CloudVertexBot: Google「robots.txt 用のトークンは Google-CloudVertexBot と Googlebot」
#     （複数のトークンがあるクローラーは、具体的なトークンのグループを優先する。googlebot-news → googlebot と同じ）
BUILTIN_FALLBACK_TOKENS = {
    "applebot": ("Googlebot",),
    "google-cloudvertexbot": ("Googlebot",),
}
FALLBACK_COLUMN = "fallback_tokens"

CATEGORIES = {
    "general-search": "通常の検索",
    "search": "AI 検索・回答",
    "training": "学習",
    "user": "ユーザー操作に伴う取得",
    "control": "制御用（クロールしない）",
    "dataset": "公開データセット",
    "other": "その他",
}
CRAWLER_COLUMNS = ("operator", "token", "category")
OUTPUT_FIELDS = ["operator", "token", "category", "path", "verdict", "matched_group", "matched_rule", "note"]

VERDICT_ALLOW = "許可"
VERDICT_DENY = "拒否"
VERDICT_MISSING = "全許可（robots.txt なし）"
VERDICT_UNREACHABLE = "全拒否（取得できず）"
VERDICT_RATE_LIMITED = "不定（429）"

# user の行の注記。robots.txt の扱いは運営ごとに違う（尊重すると説明する運営も、一般に無視すると説明する運営もある）ので、
# 一律の文にせず、一覧の robots_control（運営の説明の要約）を添える。robots_control が空のときだけ一般的な文にする
NOTE_USER = "ユーザー操作に伴う取得。robots.txt の扱い（運営の説明）: {}"
NOTE_USER_GENERIC = "ユーザー操作に伴う取得。robots.txt の扱いは運営ごとに違う（各社の公式の説明を確かめる）"
NOTE_CONTROL = "クロールはしない。この指定は学習などへの利用の可否を表す"
NOTE_UNREACHABLE = "RFC 9309 に従って全拒否として扱った。各社の実際の扱いは異なりうる"
NOTE_RATE_LIMITED = "RFC 9309 では全許可、Google はサーバーエラーとして扱いクロールを止める"
NOTE_FALLBACK = "{0} 向けのグループがないため、{1} 向けのグループに従う（運営の説明）"
DETAIL_TOO_MANY_REDIRECTS = (
    "リダイレクトが多すぎる（{} 回を超えた）。RFC 9309 2.3.1.2 では robots.txt がない（unavailable）と"
    "みなしてよく、Google も 404 として扱う".format(MAX_REDIRECTS))
WARN_UTF16 = ("robots.txt が UTF-16 で保存されているため、どの行も読めませんでした（判定の表は、ルールがないものとして"
              "全許可になっています）。RFC 9309 は UTF-8 を求めているので、クローラーも読めない可能性が高いです。"
              "UTF-8 で保存し直してください")
WARN_UNDECODABLE_NO_GROUPS = (
    "robots.txt に UTF-8 として読めない文字があり、User-agent のグループが1つもありません（判定の表は、ルールがない"
    "ものとして全許可になっています）。文字コードの違いで読めていない可能性があるので、UTF-8 で保存されているか"
    "確かめてください")
WARN_UNDECODABLE = (
    "robots.txt に UTF-8 として読めない文字があります（Shift_JIS などで保存されている可能性）。"
    "読めない文字は置き換えて判定しました。コメントの中だけなら判定に影響しませんが、"
    "パスに日本語を使っているなら UTF-8 で保存し直してください")

_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")  # 共有アドレス空間（RFC 6598）
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_SCHEME_AUTHORITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/?#]*")
_HOST_RE = re.compile(r"^[a-z0-9_.-]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HAS_HTTPS = ssl is not None and hasattr(http.client, "HTTPSConnection")


# ---------------------------------------------------------------------------
# robots.txt（RFC 9309 と Google の robots.txt の仕様）。audit.py からの移植
# ---------------------------------------------------------------------------

_ROBOTS_NEWLINE_RE = re.compile(r"\r\n|\r|\n")
_ROBOTS_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")
_PRODUCT_TOKEN_RE = re.compile(r"^[A-Za-z_-]+")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_URL_ASCII_OK = _UNRESERVED.union(":/?#[]@!$&'()*+,;=%")
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def product_token(user_agent):
    # type: (str) -> str
    """User-Agent の先頭のプロダクトトークン（英字・ハイフン・アンダースコアの並び）を小文字で返す。"""
    match = _PRODUCT_TOKEN_RE.match((user_agent or "").strip())
    return match.group(0).lower() if match else ""


def robots_canonical_path(value):
    # type: (str) -> str
    """
    ルールのパスと URL のパスを同じ表記にそろえる（RFC 9309 2.2.2）。
    非 ASCII 文字と URL に使えない ASCII 文字は UTF-8 の %XX に、%xx の16進は大文字にし、
    予約されていない文字（英数字と - . _ ~）の %XX は元の文字に戻す。* と $ はそのまま残す。
    """
    out = []  # type: list
    length = len(value)
    i = 0
    while i < length:
        ch = value[i]
        if ch == "%" and i + 2 < length and value[i + 1] in _HEX_DIGITS and value[i + 2] in _HEX_DIGITS:
            decoded = chr(int(value[i + 1:i + 3], 16))
            out.append(decoded if decoded in _UNRESERVED else "%" + value[i + 1:i + 3].upper())
            i += 3
            continue
        if ch in _URL_ASCII_OK:
            out.append(ch)
        else:
            out.append("".join("%{:02X}".format(b) for b in ch.encode("utf-8", "surrogatepass")))
        i += 1
    return "".join(out)


def robots_target(url):
    # type: (str) -> str
    """URL から照合に使う「パス + ?クエリ」を取り出す（フラグメントは除く）。"""
    rest = url.split("#", 1)[0]
    match = _SCHEME_AUTHORITY_RE.match(rest)
    if match:
        rest = rest[match.end():]
    if not rest.startswith("/"):
        rest = "/" + rest
    return robots_canonical_path(rest)


def robots_pattern_match(path, pattern):
    # type: (str, str) -> bool
    """
    パスの先頭からパターンを照合する。* は0文字以上の任意の文字、末尾の $ は URL の終わり
    （途中の $ はただの文字）。* で区切った断片を左から最短の位置で当てていくので、
    * が多いパターンでも処理時間は線形に近い（正規表現の後戻りによる暴走を避ける）。
    """
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    pieces = pattern.split("*")
    first = pieces[0]
    if not path.startswith(first):
        return False
    if len(pieces) == 1:
        return path == first if anchored else True
    pos = len(first)
    for piece in pieces[1:-1]:
        if not piece:
            continue
        found = path.find(piece, pos)
        if found < 0:
            return False
        pos = found + len(piece)
    last = pieces[-1]
    if anchored:
        return path.endswith(last) and len(path) - len(last) >= pos
    return not last or path.find(last, pos) >= 0


def parse_robots(text):
    # type: (str) -> list
    """
    robots.txt を (User-agent の値のリスト, [(パターン, allow か)]) のグループのリストにする。
    連続する User-agent 行は1つのグループにまとめ、allow / disallow の後の User-agent 行から
    新しいグループを始める。sitemap など他の行はグループの区切りにしない。
    最初の User-agent より前のルールと、値が空のルールは無視する。
    """
    groups = []  # type: list
    current = None
    in_agent_lines = False
    for raw_line in _ROBOTS_NEWLINE_RE.split(text):
        match = _ROBOTS_LINE_RE.match(raw_line.split("#", 1)[0])
        if not match:
            continue
        field = match.group(1).lower()
        value = match.group(2)
        if field == "user-agent":
            if current is None or not in_agent_lines:
                current = ([], [])
                groups.append(current)
                in_agent_lines = True
            current[0].append(value)
        elif field in ("allow", "disallow"):
            in_agent_lines = False
            if current is None or not value:
                continue
            current[1].append((robots_canonical_path(value), field == "allow"))
    return groups


def _is_global_agent(value):
    # type: (str) -> bool
    return value.startswith("*") and (len(value) == 1 or value[1].isspace())


def _agent_matches(value, token):
    # type: (str, str) -> bool
    match = _PRODUCT_TOKEN_RE.match(value)  # googlebot/1.2 や googlebot* は googlebot として扱う
    return bool(match) and match.group(0).lower() == token


class RobotsRules(object):
    """
    あるクローラーに適用するルール。長いパターンから順に並べ、同じ長さなら Allow を先にする。
    移植元からの変更: blocked_status を外し、適用したグループ（agent）と、決め手のルールを返す decide を足した。
    """

    def __init__(self, rules, label, agent=None):
        # type: (list, str, object) -> None
        self.rules = sorted(rules, key=lambda rule: (-len(rule[0]), not rule[1]))
        self.label = label
        self.agent = agent  # 適用したグループ: トークン（小文字）、"*"、なし（None）

    def decide(self, path):
        # type: (str) -> tuple
        """(許可か, 決め手のルール (パターン, allow か) または None) を返す。"""
        if path == "/robots.txt":  # robots.txt 自体は常に許可
            return True, None
        for pattern, allow in self.rules:
            if robots_pattern_match(path, pattern):
                return allow, (pattern, allow)
        return True, None

    def allowed_path(self, path):
        # type: (str) -> bool
        return self.decide(path)[0]

    def allowed(self, url):
        # type: (str) -> bool
        return self.allowed_path(robots_target(url))


def select_robots_rules(groups, tokens):
    # type: (list, list) -> RobotsRules
    """
    tokens（具体的なものから順に並べたプロダクトトークン）のうち、一致するグループがある最初の
    トークンのグループをすべて結合して使う。どれも一致しなければ User-agent: * のグループ（これも結合）、
    それもなければルールなし（全許可）。
    """
    for token in tokens:
        if not token:
            continue
        matched = [g for g in groups if any(_agent_matches(a, token) for a in g[0])]
        if matched:
            return RobotsRules([r for g in matched for r in g[1]],
                               "User-agent: {} のグループを適用".format(token), token)
    matched = [g for g in groups if any(_is_global_agent(a) for a in g[0])]
    if matched:
        return RobotsRules([r for g in matched for r in g[1]], "User-agent: * のグループを適用", "*")
    return RobotsRules([], "該当するグループなし", None)


# ---------------------------------------------------------------------------
# 内部アドレスの拒否（audit.py からの移植）
# ---------------------------------------------------------------------------

def internal_address(address):
    # type: (str) -> bool
    """
    内部アドレスなら True。プライベート（100.64.0.0/10 の共有アドレスを含む）・ループバック・リンクローカル・
    予約済み・マルチキャスト・未指定と、IPv6 のサイトローカル。IPv4 射影の IPv6（::ffff:0:0/96）と
    NAT64（64:ff9b::/96）のアドレスは、中の IPv4 アドレスで判定する。解釈できない値は内部とみなす。
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64_PREFIX:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip.version == 4 and ip in _SHARED_ADDRESS_SPACE:
        return True
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
            or ip.is_unspecified or (ip.version == 6 and ip.is_site_local))


def resolve_addresses(host, port=None):
    # type: (str, object) -> list
    """ホスト名を DNS で解決したアドレスの一覧（重複なし）。IP アドレスならそのまま。解決できなければ例外。"""
    found = []  # type: list
    for info in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        address = str(info[4][0])
        if address not in found:
            found.append(address)
    return found


class PrivateAddressBlocked(InputError):
    """取得先が内部アドレスだった。OSError ではないので、urllib に接続エラーとして包まれずに届く。"""


def _blocked_message(where, host, address):
    # type: (str, str, str) -> str
    return "{}のホスト {} が内部アドレス（{}）に解決されるため取得しません。--allow-private で許可できます".format(
        where, host, address)


def _check_peer(sock, host):
    # type: (socket.socket, str) -> None
    """接続した相手のアドレスを確かめる。内部アドレスならソケットを閉じて止める。"""
    peer = str(sock.getpeername()[0])
    if internal_address(peer):
        sock.close()
        raise PrivateAddressBlocked(_blocked_message("接続先", host, peer))


def _guarded_create_connection(address, allow_private, *args, **kwargs):
    # type: (tuple, bool, object, object) -> socket.socket
    """
    socket.create_connection の代わり。接続の直前に名前を解決し直し、内部アドレスがあれば接続しない。
    解決したアドレスに直接つなぎ、つないだ相手のアドレスも確かめる（DNS の答えが途中で変わる場合への対策）。
    """
    if allow_private:
        return socket.create_connection(address, *args, **kwargs)
    host, port = address[0], address[1]
    bare = host.strip("[]")
    addresses = resolve_addresses(bare, port)
    for resolved in addresses:
        if internal_address(resolved):
            raise PrivateAddressBlocked(_blocked_message("接続の直前の名前解決で、接続先", bare, resolved))
    error = None
    for resolved in addresses:
        try:
            sock = socket.create_connection((resolved, port), *args, **kwargs)
        except OSError as exc:
            error = exc
            continue
        _check_peer(sock, bare)
        return sock
    raise error or OSError("名前解決の結果が空です: {}".format(bare))


class _GuardMixin(object):
    """
    HTTPConnection / HTTPSConnection のサブクラスに混ぜる。ソケットを作る関数を差し替え、TCP の接続の前後で
    接続先のアドレスを確かめる（HTTPS では TLS の前に確かめる）。
    """

    def _install_guard(self, allow_private):
        # type: (bool) -> None
        self._allow_private = allow_private
        self._create_connection = self._guarded_create

    def _guarded_create(self, address, *args, **kwargs):
        return _guarded_create_connection(address, self._allow_private, *args, **kwargs)


class _GuardedHTTPConnection(_GuardMixin, http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        allow_private = kwargs.pop("allow_private", False)
        http.client.HTTPConnection.__init__(self, *args, **kwargs)
        self._install_guard(allow_private)


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allow_private):
        # type: (bool) -> None
        urllib.request.HTTPHandler.__init__(self)
        self._allow_private = allow_private

    def http_open(self, req):
        allow = self._allow_private

        def connection(host, **kwargs):
            return _GuardedHTTPConnection(host, allow_private=allow, **kwargs)

        return self.do_open(connection, req)


if _HAS_HTTPS:
    class _GuardedHTTPSConnection(_GuardMixin, http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            allow_private = kwargs.pop("allow_private", False)
            http.client.HTTPSConnection.__init__(self, *args, **kwargs)
            self._install_guard(allow_private)

    class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
        def __init__(self, allow_private):
            # type: (bool) -> None
            urllib.request.HTTPSHandler.__init__(self)
            self._allow_private = allow_private

        def https_open(self, req):
            allow = self._allow_private

            def connection(host, **kwargs):
                return _GuardedHTTPSConnection(host, allow_private=allow, **kwargs)

            return self.do_open(connection, req, context=self._context)


def _build_opener(allow_private):
    # type: (bool) -> urllib.request.OpenerDirector
    """
    取得に使う opener。環境変数のプロキシを使わない（ProxyHandler({})）。リダイレクトは自前でたどるので
    HTTPRedirectHandler を入れず、4xx・5xx も例外にしないよう HTTPErrorProcessor も入れない。
    """
    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.ProxyHandler({}))
    opener.add_handler(_GuardedHTTPHandler(allow_private))
    if _HAS_HTTPS:
        opener.add_handler(_GuardedHTTPSHandler(allow_private))
    return opener


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------

def _url_suffix(text):
    # type: (str) -> str
    """
    エラーの文の末尾に付ける入力の URL。@ を含むときは、ユーザー名・パスワード（user:pass@host の形。
    スキームのない入力や // のない入力も含む）の可能性があるので、値を出さない。
    """
    if "@" in text:
        return "（入力に @ があるため、値は表示しません）"
    return ": " + text


def origin_of(url):
    # type: (str) -> str
    """URL から scheme://host[:port] を取り出す。http / https 以外、userinfo 付き、ホストのない URL は InputError。"""
    text = (url or "").strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        raise InputError("URL を解釈できません{}".format(_url_suffix(text)))
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InputError("--url には http:// か https:// で始まる URL を指定してください（例: https://example.jp）{}".format(
            _url_suffix(text)))
    if "@" in parts.netloc:
        raise InputError("URL にユーザー名・パスワード（userinfo）が含まれているため取得しません。@ より前を外してください")
    try:
        port = parts.port
    except ValueError:
        raise InputError("URL のポート番号を読めません{}".format(_url_suffix(text)))
    host = parts.hostname or ""
    if not host:
        raise InputError("URL にホスト名がありません{}".format(_url_suffix(text)))
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise InputError("ホスト名を IDNA の表記にできません{}".format(_url_suffix(text)))
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise InputError("ホスト名を読めません{}".format(_url_suffix(text)))
        netloc = "[{}]".format(host)
    else:
        if not _HOST_RE.match(host):
            raise InputError("ホスト名に使えない文字があります{}".format(_url_suffix(text)))
        netloc = host
    if port is not None:
        netloc += ":{}".format(port)
    return "{}://{}".format(scheme, netloc)


def _check_target(url, allow_private, redirected):
    # type: (str, bool, bool) -> None
    """取得する前の確認。userinfo と内部アドレスは InputError。名前解決できなければ socket.gaierror。"""
    where = "リダイレクト先" if redirected else "取得先"
    parts = urlsplit(url)
    if "@" in parts.netloc:
        raise InputError("{}の URL にユーザー名・パスワード（userinfo）が含まれているため取得しません".format(where))
    if allow_private:
        return
    host = parts.hostname or ""
    for address in resolve_addresses(host, parts.port):
        if internal_address(address):
            raise PrivateAddressBlocked(_blocked_message(where, host, address))


def _redirect_target(base, location):
    # type: (str, str) -> tuple
    """
    リダイレクト先の URL と、たどれないときの理由を返す。http.client はヘッダーを latin-1 で読むので、
    UTF-8 のまま送られた Location（日本語のパスなど）は UTF-8 として読み直す（requests と同じ扱い）。
    UTF-8 として読めなければ latin-1 の文字のままにする。非 ASCII のホスト名は IDNA の表記に、
    パスとクエリの非 ASCII の文字は UTF-8 の %XX にする。フラグメントは外す。
    """
    try:
        location = location.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    try:
        target = urljoin(base, location.strip())
        parts = urlsplit(target)
        hostname = parts.hostname
        port = parts.port  # 範囲外のポート番号は ValueError
    except ValueError:
        return None, "リダイレクト先の URL を解釈できない"
    if parts.scheme.lower() not in ("http", "https") or not hostname:
        return None, "http / https 以外へのリダイレクト"
    netloc = parts.netloc
    if not hostname.isascii():
        try:
            ascii_host = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return None, "リダイレクト先のホスト名を IDNA の表記にできない"
        userinfo = netloc.rpartition("@")[0] + "@" if "@" in netloc else ""  # userinfo は取得の前の確認で止める
        netloc = userinfo + ascii_host + (":{}".format(port) if port is not None else "")
    target = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
    return quote(target, safe="!#$%&'()*+,/:;=?@[]~"), ""


def _read_limited(response, limit):
    # type: (object, int) -> bytes
    buf = bytearray()
    while len(buf) < limit:
        chunk = response.read(min(65536, limit - len(buf)))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _request(opener, url, timeout):
    # type: (urllib.request.OpenerDirector, str, float) -> tuple
    """1回だけ取得して (ステータス, Location, 本文) を返す。本文は 2xx のときだけ、上限 + 1 バイトまで読む。"""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    response = opener.open(request, timeout=timeout)
    try:
        code = int(response.status)
        location = response.headers.get("Location")
        body = _read_limited(response, MAX_ROBOTS_BYTES + 1) if 200 <= code < 300 else b""
        return code, location, body
    finally:
        response.close()


def _describe_error(exc, timeout):
    # type: (BaseException, float) -> str
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        return "名前解決できない（{}）。ホスト名が正しいか確かめる".format(reason)
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "タイムアウト（{} 秒）".format(timeout)
    if ssl is not None and isinstance(reason, ssl.SSLError):
        return "TLS のエラー（{}）".format(reason)
    if isinstance(reason, http.client.HTTPException):
        return "応答を読めない（{}）".format(type(reason).__name__)  # 中身はサーバーが決めるので出さない
    if isinstance(reason, ValueError):
        return "URL を解釈できない（{}）".format(reason)
    return "接続エラー（{}: {}）".format(type(reason).__name__, reason)


def decode_robots(data):
    # type: (bytes) -> tuple
    """
    robots.txt の中身を (文字列, 500 KiB で切ったか, 読めない文字を置き換えたか) にする。UTF-8 として読み、
    先頭の BOM を除く。切ったときは、途中で切れた最後の行を捨てる（短くなったパスが広すぎるルールになるため）。
    """
    truncated = len(data) > MAX_ROBOTS_BYTES
    if truncated:
        data = data[:MAX_ROBOTS_BYTES]
    text = data.decode("utf-8", errors="replace").lstrip("\ufeff")
    if truncated:
        text = text[:max(text.rfind("\n"), text.rfind("\r"), 0)]
    return text, truncated, "\ufffd" in text


def looks_like_utf16(data):
    # type: (bytes) -> bool
    """UTF-16 \u3067\u4fdd\u5b58\u3055\u308c\u305f robots.txt \u3089\u3057\u3044\u304b\uff08UTF-16 \u306e BOM \u304c\u3042\u308b\u304b\u3001\u5148\u982d\u306e 1 KiB \u306b NUL \u30d0\u30a4\u30c8\u304c\u3042\u308b\uff09\u3002"""
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return True
    return b"\x00" in data[:1024]


def _set_body(state, data):
    # type: (dict, bytes) -> None
    """\u53d6\u5f97\u3057\u305f\u304b\u8aad\u3093\u3060 robots.txt \u306e\u4e2d\u8eab\u3092 state \u306b\u5165\u308c\u3001state \u3092 ok \u306b\u3059\u308b\u3002"""
    text, truncated, replaced = decode_robots(data)
    state.update(state="ok", text=text, truncated=truncated, replaced=replaced, utf16=looks_like_utf16(data))


def _new_state(url):
    # type: (str) -> dict
    return {"state": "", "code": None, "text": "", "url": url, "final_url": url, "detail": "",
            "truncated": False, "replaced": False, "utf16": False, "source": "url"}


def _name_not_found(exc):
    # type: (BaseException) -> bool
    """\u540d\u524d\u89e3\u6c7a\u3067\u300c\u305d\u306e\u540d\u524d\u304c\u306a\u3044\u300d\uff08EAI_NONAME\uff09\u3068\u8fd4\u3063\u305f\u304b\u3002\u4e00\u6642\u7684\u306a\u5931\u6557\uff08EAI_AGAIN \u306a\u3069\uff09\u306f\u542b\u3081\u306a\u3044\u3002"""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    code = getattr(socket, "EAI_NONAME", None)
    return isinstance(reason, socket.gaierror) and code is not None and reason.errno == code


def fetch_robots(origin, timeout, allow_private):
    # type: (str, float, bool) -> dict
    """
    origin（scheme://host[:port]。URL を渡してもよい）の /robots.txt を取得する。返り値のキー:
    state（ok / missing / unreachable / rate_limited）, code, text, url, final_url, detail, truncated, replaced, utf16。
    userinfo 付きの URL と、内部アドレスに解決されるホスト（allow_private でないとき）は InputError。
    最初の URL のホスト名が名前解決で見つからない（EAI_NONAME。打ち間違いなど）ときも InputError にする。
    全拒否（取得できず）の表を出すと、サイトが全クローラーを拒否しているように読めてしまうため。
    一時的な失敗（EAI_AGAIN など）とリダイレクト先の失敗は unreachable のまま。
    """
    url = origin_of(origin) + "/robots.txt"
    if url.startswith("https:") and not _HAS_HTTPS:
        raise InputError("この Python は ssl に対応していないため、https の robots.txt を取得できません")
    state = _new_state(url)
    opener = _build_opener(allow_private)
    redirects = 0
    while True:
        state["final_url"] = url
        try:
            _check_target(url, allow_private, redirects > 0)
            code, location, body = _request(opener, url, timeout)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if redirects == 0 and _name_not_found(exc):
                raise InputError("{} の名前解決ができません（その名前は見つかりません）。ホスト名に打ち間違いが"
                                 "ないか、ネットワークにつながっているかを確かめてください（macOS はネットワークに"
                                 "つながっていないときも同じエラーを返します）".format(urlsplit(url).hostname))
            state.update(state="unreachable", detail=_describe_error(exc, timeout))
            return state
        state["code"] = code
        if 200 <= code < 300:
            _set_body(state, body)
            state["detail"] = "ステータス {}".format(code)
            return state
        if 300 <= code < 400:
            if not location:
                state.update(state="unreachable", detail="ステータス {}。リダイレクト先（Location）がない".format(code))
                return state
            if redirects >= MAX_REDIRECTS:
                state.update(state="missing", detail=DETAIL_TOO_MANY_REDIRECTS)
                return state
            target, problem = _redirect_target(url, location)
            if target is None:
                state.update(state="unreachable", detail="ステータス {}。{}".format(code, problem))
                return state
            redirects += 1
            url = target
            continue
        if code == 429:
            state.update(state="rate_limited", detail="ステータス 429")
        elif 400 <= code < 500:
            state.update(state="missing", detail="ステータス {}".format(code))
        else:
            state.update(state="unreachable", detail="ステータス {}".format(code))
        return state


def read_robots_file(path):
    # type: (str) -> dict
    """手元の robots.txt を読み、fetch_robots と同じ形（state=ok）で返す。"""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_ROBOTS_BYTES + 1)
    except OSError as exc:
        raise InputError("robots.txt のファイルを読めません: {}（{}）".format(path, exc.strerror or exc))
    # ファイル名に UTF-8 でないバイトがあると（surrogate の文字）、標準出力に書くときに落ちるので置き換えておく
    state = _new_state(_printable(path))
    _set_body(state, data)
    state["source"] = "file"
    return state


def _printable(text):
    # type: (str) -> str
    """UTF-8 で書き出せない文字（引数やファイル名の surrogate）を \\udcff の形の文字に置き換える。"""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


# ---------------------------------------------------------------------------
# クローラーの一覧と判定
# ---------------------------------------------------------------------------

def _fallback_tokens(values, key, where):
    # type: (list, str, str) -> list
    """代わりに従うトークンの一覧を検証する。プロダクトトークンの形でないものは警告して外す。"""
    out = []  # type: list
    keys = [key]
    for value in values:
        fallback = product_token(value)
        if not fallback or fallback != value.lower():
            log("警告: {}: fallback_tokens の {} は RFC 9309 のプロダクトトークンの形（英字・ハイフン・下線）"
                "ではないため、使いません".format(where, value))
            continue
        if fallback in keys:
            continue
        keys.append(fallback)
        out.append(value)
    return out


def crawler_tokens(crawler):
    # type: (dict) -> list
    """
    クローラーが従うグループのトークンを [(照合に使う小文字のトークン, 表示するトークン)] で返す。
    一覧の token が先、fallback_tokens（| 区切り）が後。select_robots_rules はこの順に探す。
    """
    token = (crawler.get("token") or "").strip()
    key = product_token(token)
    out = [(key, token)] if key else []
    for value in split_list(crawler.get(FALLBACK_COLUMN) or ""):
        fallback = product_token(value)
        if fallback and fallback == value.lower() and fallback not in [k for k, _ in out]:
            out.append((fallback, value))
    return out


def load_crawlers(path):
    # type: (str) -> list
    """
    クローラーの一覧の CSV を読む。category が決まった値でなければ other として扱う。
    fallback_tokens の列（任意。| 区切り）は、自分向けのグループがないときに従うトークン。列がなければ
    BUILTIN_FALLBACK_TOKENS を使う。
    """
    if not os.path.isfile(path):
        raise InputError("クローラーの一覧がありません: {}".format(path))
    try:
        fields, rows = read_csv(path)
    except (OSError, csv.Error) as exc:
        raise InputError("クローラーの一覧を読めません: {}（{}）".format(path, exc))
    missing = [name for name in CRAWLER_COLUMNS if name not in fields]
    if missing:
        raise InputError("{}: 列が足りません: {}".format(path, ", ".join(missing)))
    has_fallback_column = FALLBACK_COLUMN in fields
    crawlers = []
    seen = set()
    for n, row in enumerate(rows, start=2):
        where = "{} の {} 行目".format(path, n)
        token = row.get("token", "")
        if not token:
            raise InputError("{}: token が空です".format(where))
        key = product_token(token)
        if not key:
            log("警告: {}: token {} は英字で始まらないため、robots.txt の User-agent と照合できません。"
                "この行を飛ばします".format(where, token))
            continue
        if key != token.lower():
            log("警告: {}: token {} は RFC 9309 のプロダクトトークンの形（英字・ハイフン・下線）ではないため、"
                "先頭の {} で照合します".format(where, token, key))
        if key in seen:
            log("警告: {}: token {} が重複しています。先の行だけを使います".format(where, token))
            continue
        seen.add(key)
        category = row.get("category", "")
        if category not in CATEGORIES:
            log("警告: {}: category {} は決まった値（{}）ではないため、その他として扱います".format(
                where, category or "（空）", " / ".join(CATEGORIES)))
            category = "other"
        if has_fallback_column:
            fallback_values = split_list(row.get(FALLBACK_COLUMN, ""))
        else:
            fallback_values = list(BUILTIN_FALLBACK_TOKENS.get(key, ()))
        crawler = dict(row)
        crawler["category"] = category
        crawler[FALLBACK_COLUMN] = "|".join(_fallback_tokens(fallback_values, key, where))
        crawlers.append(crawler)
    if not crawlers:
        raise InputError("{}: クローラーの一覧が空です".format(path))
    return crawlers


def oldest_checked_on(crawlers):
    # type: (list) -> object
    """一覧の checked_on のうち最も古い日付（YYYY-MM-DD）。なければ None。"""
    dates = []
    for crawler in crawlers:
        value = (crawler.get("checked_on") or "").strip()
        if not _DATE_RE.match(value):
            continue
        try:
            datetime.date(int(value[:4]), int(value[5:7]), int(value[8:10]))
        except ValueError:
            continue
        dates.append(value)
    return min(dates) if dates else None


def _months_later(date, months):
    # type: (datetime.date, int) -> datetime.date
    index = date.year * 12 + date.month - 1 + months
    year, month = index // 12, index % 12 + 1
    for day in (date.day, 30, 29, 28):
        try:
            return datetime.date(year, month, day)
        except ValueError:
            continue
    return datetime.date(year, month, 28)


def stale_warning(checked_on, today=None):
    # type: (object, object) -> object
    """確認日から3か月以上たっていれば警告の文を返す。"""
    if not checked_on:
        return None
    today = today or datetime.date.today()
    date = datetime.date(int(checked_on[:4]), int(checked_on[5:7]), int(checked_on[8:10]))
    if today >= _months_later(date, 3):
        return "クローラーの一覧の確認日（{}）から3か月以上たっています。各社の公式資料で再確認してください".format(
            checked_on)
    return None


def display_path(path):
    # type: (str) -> str
    """判定するパスの表示。URL ならパス以降だけにし、/ で始まらなければ / を足す。フラグメントは除く。"""
    value = (path or "").strip()
    match = _SCHEME_AUTHORITY_RE.match(value)
    if match:
        value = value[match.end():]
    value = value.split("#", 1)[0]
    if not value.startswith("/"):
        value = "/" + value
    return value


def parse_paths(value):
    # type: (str) -> list
    """--paths の値（カンマ区切り）を、表示用のパスの一覧にする。重複は除く。"""
    paths = []  # type: list
    for part in split_list(value or "", ","):
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in part):
            raise InputError("--paths に制御文字を含むパスがあります: {!r}".format(part))
        try:
            part.encode("utf-8")
        except UnicodeEncodeError:  # 引数に UTF-8 でないバイトがあると surrogate の文字になる
            raise InputError("--paths に UTF-8 として読めない文字を含むパスがあります: {!r}".format(part))
        shown = display_path(part)
        if shown not in paths:
            paths.append(shown)
    if not paths:
        raise InputError("--paths に判定するパスがありません（例: --paths /,/blog/）")
    return paths


def _group_label(rules, tokens):
    # type: (RobotsRules, list) -> str
    """適用したグループの表示。代わりのトークンのグループを使ったときは、そのトークンを出す。"""
    if rules.agent is None:
        return "なし"
    if rules.agent == "*":
        return "User-agent: *"
    return "User-agent: {}".format(dict(tokens).get(rules.agent, rules.agent))


def _fallback_note(rules, tokens):
    # type: (RobotsRules, list) -> str
    """代わりのトークンのグループに従ったときの注記。自分のグループか * なら空。"""
    if not tokens or rules.agent in (None, "*", tokens[0][0]):
        return ""
    return NOTE_FALLBACK.format(tokens[0][1], dict(tokens).get(rules.agent, rules.agent))


def robots_groups(state):
    # type: (dict) -> list
    """取得の結果の robots.txt を解析したグループ（state が ok でなければ空）。解析は1回だけ行い、結果を持っておく。"""
    if state.get("state") != "ok":
        return []
    if "_groups" not in state:
        state["_groups"] = parse_robots(state.get("text") or "")
    return state["_groups"]


def evaluate(state, crawlers, paths):
    # type: (dict, list, list) -> list
    """クローラーごと・パスごとの判定の行（列は OUTPUT_FIELDS）を返す。"""
    kind = state.get("state")
    detail = state.get("detail") or ""
    groups = robots_groups(state)
    rows = []
    for crawler in crawlers:
        token = (crawler.get("token") or "").strip()
        category = crawler.get("category") or ""
        tokens = crawler_tokens(crawler)
        rules = select_robots_rules(groups, [k for k, _ in tokens]) if kind == "ok" else None
        for path in paths:
            shown = display_path(path)
            notes = []  # type: list
            group = ""
            matched_rule = ""
            if kind == "ok":
                allowed, rule = rules.decide(robots_target(shown))
                verdict = VERDICT_ALLOW if allowed else VERDICT_DENY
                group = _group_label(rules, tokens)
                notes.append(_fallback_note(rules, tokens))
                if rule is not None:
                    matched_rule = "{}: {}".format("Allow" if rule[1] else "Disallow", rule[0])
            elif kind == "missing":
                verdict = VERDICT_MISSING
                notes.append(detail)
            elif kind == "rate_limited":
                verdict = VERDICT_RATE_LIMITED
                notes.extend([detail, NOTE_RATE_LIMITED])
            elif kind == "unreachable":
                verdict = VERDICT_UNREACHABLE
                notes.extend([detail, NOTE_UNREACHABLE])
            else:
                raise ValueError("取得の結果の state が不正です: {}".format(kind))
            if category == "user":
                control_text = (crawler.get("robots_control") or "").strip()
                notes.append(NOTE_USER.format(control_text) if control_text else NOTE_USER_GENERIC)
            elif category == "control":
                notes.append(NOTE_CONTROL)
            rows.append({
                "operator": crawler.get("operator") or "",
                "token": token,
                "category": category,
                "path": shown,
                "verdict": verdict,
                "matched_group": group,
                "matched_rule": matched_rule,
                "note": " / ".join(n for n in notes if n),
            })
    return rows


def _literal_prefix(pattern):
    # type: (str) -> str
    """パターンに当たるパスが必ず持つ先頭の固定の部分（最初の * より前。末尾の $ は除く）。"""
    if pattern.endswith("$"):
        pattern = pattern[:-1]
    return pattern.split("*", 1)[0]


def _covers(rules, pattern):
    # type: (list, str) -> bool
    """
    クローラーのグループのルール（rules）が、User-agent: * の Disallow のパターン（pattern）に当たるパスを
    すべて拒否していると言えるなら True。言い切れないときは False（警告を出す側に倒す）。
    - 覆う Disallow: pattern と同じパターン（末尾の $ 付きどうしを含む）か、末尾に $ のない Disallow で、
      pattern の固定の接頭辞に当たるもの（その接頭辞で始まるパスには、すべて当たる）。
      末尾に $ のある Disallow は、その1点にしか当たらないので覆わない。
    - ただし、その Disallow 以上の長さの Allow（同じ長さなら Allow が勝つ）が pattern の範囲に当たりうるなら、
      範囲の一部が開いている可能性があるので覆っていないとする。末尾に $ があり * のない Allow（Allow: /$ など）は
      その1点のパスにしか当たらないので、そのパスが pattern に当たるときだけ数える。ほかの Allow は、固定の接頭辞が
      pattern の固定の接頭辞と重なれば（どちらかがもう一方の先頭の部分なら）当たりうるとみなす。
    """
    prefix = _literal_prefix(pattern)
    for deny, allow in rules:
        if allow:
            continue
        if deny != pattern and (deny.endswith("$") or not robots_pattern_match(prefix, deny)):
            continue
        if not any(other_allow and len(other) >= len(deny) and _may_open(other, pattern, prefix)
                   for other, other_allow in rules):
            return True
    return False


def _may_open(allow_pattern, pattern, prefix):
    # type: (str, str, str) -> bool
    """Allow のパターンが、* の Disallow のパターン（固定の接頭辞は prefix）に当たるパスに当たりうるか。"""
    if allow_pattern.endswith("$") and "*" not in allow_pattern:
        return robots_pattern_match(allow_pattern[:-1], pattern)
    other_prefix = _literal_prefix(allow_pattern)
    return other_prefix.startswith(prefix) or prefix.startswith(other_prefix)


def _star_inheritance(groups, crawlers):
    # type: (list, list) -> list
    """
    [(トークン, 従ったグループのトークン（自分のグループなら None）, 適用されない * の Disallow のパターンの一覧)]。
    自分向けのグループがなく、代わりのトークン（fallback_tokens）のグループに従うクローラーも対象にする。
    """
    star = []  # type: list
    for agents, rules in groups:
        if any(_is_global_agent(a) for a in agents):
            for pattern, allow in rules:
                if not allow and pattern not in star:
                    star.append(pattern)
    if not star:
        return []
    out = []
    seen = set()
    for crawler in crawlers:
        token = (crawler.get("token") or "").strip()
        tokens = crawler_tokens(crawler)
        if not tokens or tokens[0][0] in seen:
            continue
        seen.add(tokens[0][0])
        matched = []  # type: list
        via = None
        for index, (key, shown) in enumerate(tokens):
            matched = [g for g in groups if any(_agent_matches(a, key) for a in g[0])]
            if matched:
                via = shown if index > 0 else None
                break
        if not matched:
            continue
        rules = [r for g in matched for r in g[1]]
        # そのクローラーのグループが同じ範囲を拒否していれば、警告しても意味がないので除く
        lacking = [p for p in star if not _covers(rules, p)]
        if lacking:
            out.append((token, via, lacking))
    return out


def _star_message(token, patterns, via=None):
    # type: (str, list, object) -> str
    if via:
        return "{0} が従う {2} 向けのグループがあるため、User-agent: * の Disallow: {1} は {0} に適用されません".format(
            token, ", ".join(patterns), via)
    return "{0} 向けのグループがあるため、User-agent: * の Disallow: {1} は {0} に適用されません".format(
        token, ", ".join(patterns))


def star_inheritance_warnings(groups, crawlers):
    # type: (list, list) -> list
    """特定のクローラー向けのグループがあるために、User-agent: * の Disallow が適用されないことの警告。"""
    return [_star_message(token, patterns, via) for token, via, patterns in _star_inheritance(groups, crawlers)]


def summary_path(paths):
    # type: (list) -> str
    shown = [display_path(p) for p in paths]
    return "/" if "/" in shown else shown[0]


def summarize(rows, paths):
    # type: (list, list) -> list
    """分類ごとに「n 件中 m 件が拒否」の行（パス / で判定。/ がなければ最初のパス）。"""
    target = summary_path(paths)
    counts = {}  # type: dict
    for row in rows:
        if row["path"] != target:
            continue
        category = row["category"] if row["category"] in CATEGORIES else "other"
        total, denied, unknown = counts.get(category, (0, 0, 0))
        verdict = row["verdict"]
        counts[category] = (total + 1, denied + (verdict in (VERDICT_DENY, VERDICT_UNREACHABLE)),
                            unknown + (verdict == VERDICT_RATE_LIMITED))
    lines = []
    for category, label in CATEGORIES.items():
        if category not in counts:
            continue
        total, denied, unknown = counts[category]
        line = "{}: {} 件中 {} 件が拒否".format(label, total, denied)
        if unknown:
            line += "、{} 件が不定".format(unknown)
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def _plain(value):
    # type: (object) -> str
    return "" if value is None else str(value)


def describe_state(state, md=False):
    # type: (dict, bool) -> list
    """
    取得の結果の説明（標準エラーと Markdown の箇条書きに使う）。md なら、URL（リダイレクト先はサーバーが決める）を
    コードスパンにし、ほかの文もリンクや HTML として解釈されないようにする。
    """
    code = _md_code if md else _plain
    text = _md_text if md else _plain
    lines = []
    if state.get("source") == "file":
        lines.append("読んだファイル: {}".format(code(state.get("url"))))
    else:
        lines.append("robots.txt の URL: {}".format(code(state.get("url"))))
        if state.get("final_url") and state.get("final_url") != state.get("url"):
            lines.append("最後に取得した URL: {}".format(code(state.get("final_url"))))
        lines.append("ステータス: {}".format(state.get("code") if state.get("code") is not None else "なし"))
    kind = state.get("state")
    detail = text(state.get("detail") or "")
    if kind == "ok":
        lines.append("判定のもと: robots.txt の記述（グループ {} 個）".format(len(robots_groups(state))))
    elif kind == "missing":
        lines.append("判定のもと: robots.txt がないものとして全許可で扱った（RFC 9309 2.3.1.3。{}）".format(detail))
    elif kind == "rate_limited":
        lines.append("判定のもと: ステータス 429。RFC 9309 では 4xx の一つとして全許可、Google はサーバーエラーとして"
                     "扱いクロールを止める。判定は「不定（429）」とした")
    else:
        lines.append("判定のもと: robots.txt を取得できなかった（{}）。{}".format(detail, NOTE_UNREACHABLE))
    lines.append("CDN・WAF の設定は調べていない（robots.txt の記述だけを判定した）")
    return lines


_MD_ESCAPE_RE = re.compile(r"([\\\[\]<>|])")


def _md_text(value):
    # type: (object) -> str
    """
    Markdown の地の文や表のセルに入れる文字列。改行を空白にし、\\ [ ] < > | の前に \\ を付けて、
    リンク・画像・HTML として解釈されず、表も崩れないようにする。
    """
    text = _plain(value).replace("\r", " ").replace("\n", " ")
    return _MD_ESCAPE_RE.sub(r"\\\1", text)


def _md_code(value):
    # type: (object) -> str
    """robots.txt やサーバーに由来する文字列をコードスパンにする（リンクや画像として解釈させない）。"""
    text = _plain(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    if not text:
        return ""
    fence = "``" if "`" in text else "`"
    return "{0}{1}{0}".format(fence, text)


def render_markdown(state, rows, paths, warnings_md, checked_on):
    # type: (dict, list, list, list, object) -> str
    lines = ["# AI クローラーの robots.txt 判定", "", "## 取得の結果", ""]
    lines += ["- " + line for line in describe_state(state, md=True)]
    lines += ["", "## 要約（パス {} で判定）".format(_md_text(summary_path(paths))), ""]
    lines += ["- " + line for line in summarize(rows, paths)]
    lines += ["", "## 警告", ""]
    lines += ["- " + line for line in warnings_md] if warnings_md else ["- なし"]
    lines += ["", "## 判定", "",
              "| 運営 | トークン | 分類 | パス | 判定 | 適用したグループ | 決め手のルール | 注記 |",
              "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        cells = [_md_text(row["operator"]), _md_text(row["token"]),
                 _md_text(CATEGORIES.get(row["category"], row["category"])), _md_text(row["path"]),
                 _md_text(row["verdict"]), _md_text(row["matched_group"]), _md_code(row["matched_rule"]),
                 _md_text(row["note"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "一覧の確認日: {}。3か月以上前なら各社の公式資料で再確認する。".format(checked_on or "不明"), ""]
    return "\n".join(lines)


def collect_warnings(state, crawlers, checked_on):
    # type: (dict, list, object) -> tuple
    """(標準エラー用の警告, Markdown 用の警告)。robots.txt 由来のパターンは Markdown ではコードスパンにする。"""
    plain = []  # type: list
    md = []  # type: list
    if state.get("state") == "ok":
        groups = robots_groups(state)
        for token, via, patterns in _star_inheritance(groups, crawlers):
            plain.append(_star_message(token, patterns, via))
            md.append(_star_message(_md_text(token), [_md_code(p) for p in patterns], _md_text(via) if via else None))
        if state.get("truncated"):
            text = ("robots.txt が 500 KiB を超えているため、先頭の 500 KiB だけを判定しました"
                    "（途中で切れた最後の行は捨てました）")
            plain.append(text)
            md.append(text)
        # 文字コードの警告。グループが1つも読めなかったときは、判定の表が全許可になっていることを伝える
        encoding_warning = None
        if state.get("utf16") and not groups:
            encoding_warning = WARN_UTF16
        elif state.get("replaced"):
            encoding_warning = WARN_UNDECODABLE if groups else WARN_UNDECODABLE_NO_GROUPS
        if encoding_warning:
            plain.append(encoding_warning)
            md.append(encoding_warning)
    stale = stale_warning(checked_on)
    if stale:
        plain.append(stale)
        md.append(stale)
    return plain, md


def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = ArgumentParser(
        prog="ai_robots_check.py",
        description="AI クローラーごとに robots.txt の許可・拒否を判定する（RFC 9309 に沿う）。",
        epilog="例: python3 ai_robots_check.py --url https://example.jp --paths /,/blog/ "
               "/ python3 ai_robots_check.py --file robots.txt --format csv -o robots.csv")
    parser.add_argument("--url", help="サイトの URL（http / https）。その origin の /robots.txt を取得する")
    parser.add_argument("--file", help="手元の robots.txt のファイル（--url とどちらか一方）")
    parser.add_argument("--paths", default="/", help="判定するパス。カンマ区切り（既定: /）")
    parser.add_argument("--format", default="md", help="出力の形式: md（既定）か csv")
    parser.add_argument("-o", "--output", help="出力先のファイル。省略すると標準出力")
    parser.add_argument("--crawlers", help="クローラーの一覧の CSV（既定: スキルの data/ai-crawlers.csv）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="取得のタイムアウト（秒、既定 {:g}、0 より大きく {:g} 以下）".format(
                            DEFAULT_TIMEOUT, MAX_TIMEOUT))
    parser.add_argument("--allow-private", action="store_true",
                        help="内部アドレス（プライベート IP など）に解決されるホストからも取得する")
    return parser


def _write_csv_stdout(rows):
    # type: (list) -> None
    """
    CSV を標準出力に書く（BOM なし、sanitize しない）。CSV の行末は \\r\\n なので、改行を変換する標準出力
    （Windows では \\n → \\r\\n）にそのまま書くと \\r\\r\\n になる。下のバイト列に newline="" で書き直す。
    """
    stream = sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is None:  # io.StringIO など、改行を変換しないストリーム
        write_csv_stream(stream, OUTPUT_FIELDS, rows, sanitize=False)
        return
    stream.flush()
    wrapper = io.TextIOWrapper(buffer, encoding=getattr(stream, "encoding", None) or "utf-8",
                               errors=getattr(stream, "errors", None) or "strict", newline="")
    try:
        write_csv_stream(wrapper, OUTPUT_FIELDS, rows, sanitize=False)
        wrapper.flush()
    finally:
        wrapper.detach()  # 標準出力のバイト列は閉じない


def run(args):
    # type: (argparse.Namespace) -> int
    if args.url and args.file:
        raise InputError("--url と --file はどちらか一方だけを指定してください")
    if not args.url and not args.file:
        raise InputError("--url（サイトの URL）か --file（robots.txt のファイル）を指定してください")
    if args.format not in ("md", "csv"):
        raise InputError("--format は md か csv にしてください: {}".format(args.format))
    if not (math.isfinite(args.timeout) and 0 < args.timeout <= MAX_TIMEOUT):
        raise InputError("--timeout は 0 より大きく {:g} 以下の秒数にしてください: {}".format(MAX_TIMEOUT, args.timeout))
    paths = parse_paths(args.paths)
    if not args.crawlers and not os.path.isfile(DEFAULT_CRAWLERS):
        raise InputError("既定のクローラーの一覧 {} がありません。スキルのフォルダが欠けていないか確かめるか、"
                         "--crawlers で一覧の CSV を指定してください".format(DEFAULT_CRAWLERS))
    crawlers = load_crawlers(args.crawlers or DEFAULT_CRAWLERS)

    if args.url:
        state = fetch_robots(args.url, args.timeout, args.allow_private)
    else:
        state = read_robots_file(args.file)
    rows = evaluate(state, crawlers, paths)
    checked_on = oldest_checked_on(crawlers)
    warnings_plain, warnings_md = collect_warnings(state, crawlers, checked_on)

    try:
        if args.format == "csv":
            if args.output:
                write_csv(args.output, OUTPUT_FIELDS, rows)
            else:
                _write_csv_stdout(rows)
        else:
            report = render_markdown(state, rows, paths, warnings_md, checked_on)
            if args.output:
                with open(args.output, "w", encoding="utf-8", newline="\n") as f:
                    f.write(report)
            else:
                sys.stdout.write(report)
        sys.stdout.flush()
    except OSError as exc:
        raise InputError("出力を書けません: {}（{}）".format(args.output or "標準出力", exc))

    log("robots.txt を判定しました: クローラー {} 件 × パス {} 件{}".format(
        len(crawlers), len(paths), "（出力: {}）".format(args.output) if args.output else ""))
    for line in describe_state(state):
        log("  " + line)
    log("  要約（パス {} で判定）:".format(summary_path(paths)))
    for line in summarize(rows, paths):
        log("    " + line)
    for warning in warnings_plain:
        log("警告: " + warning)
    return 0


def main(argv=None):
    # type: (object) -> int
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except InputError as exc:
        log("エラー: {}".format(exc))
        return 2
    except Exception as exc:  # noqa: BLE001  想定外のエラーは原因を追えるように経緯も出し、終了コード 1
        log("想定外のエラー（ai_robots_check.py {}）: {}: {}".format(VERSION, type(exc).__name__, exc))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
