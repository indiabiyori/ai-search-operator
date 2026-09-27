# -*- coding: utf-8 -*-
"""
ai_search_common.py - ai-search-operator のスクリプトが共通で使う処理

単独では実行しない。同じフォルダのスクリプト（normalize_observations.py、compare_runs.py、
ai_robots_check.py、new_round.py）が import する。Python 3.9 以上の標準ライブラリだけを使う。

含むもの:
  - 決まった値の一覧（サービス名、画面か API か、ログイン状態、正誤の判定、段階、指名かどうか）
  - 表記の正規化（NFKC、大文字・小文字、空白）
  - ファイルの読み込み（BOM に従い、なければ UTF-8 → cp932 の順に試す）
  - CSV の読み書き。書くときは BOM 付き UTF-8 にし、数式として実行されうるセルの先頭に ' を付ける
    （CSV インジェクション対策）。読むときはその ' を外す。NUL は書くときも読むときも除く（Python 3.9 と
    3.11 以降で csv の扱いが違うため）。読むときはセルの長さの上限（csv の既定 131072 文字）を上げる
  - 回答ファイルの先頭の欄（--- で囲んだ key: value の行）の解析
  - entities.csv と prompts.csv の読み込みと検証。ドメインは NFKC・小文字・ラベルごとの IDNA（ASCII）にそろえ、
    URL のホストも ascii_host で同じ形にしてから比べる
  - 率の表示「k/n（xx.x%）」（normalize_observations.py と compare_runs.py で丸め方をそろえる）
  - ai-search/ の中で --workspace を付けずに実行したときの案内
  - -h の説明と引数の誤りの文を日本語にした ArgumentParser
"""
import argparse
import codecs
import csv
import hashlib
import io
import os
import re
import sys
import unicodedata
from fractions import Fraction

VERSION = "1.0.0"

SERVICES = ("chatgpt", "claude", "perplexity", "gemini", "copilot", "google-ai-mode", "google-aio")
SURFACES = ("web", "app", "api")
LOGINS = ("なし", "あり（記憶オフ）", "あり")
ACCURACY_VALUES = ("未確認", "誤りなし", "誤りあり", "該当なし")
REVIEWED_BY_VALUES = ("", "claude-draft", "human")
STAGES = ("認知", "比較", "購入", "サポート")
BRANDED_VALUES = ("指名", "非指名")
ENTITY_KINDS = ("own", "competitor")
# 回答の状態。空のときは normalize_observations.py が回答の有無から決める
STATUS_VALUES = ("", "記録済み", "AI の回答なし", "回答拒否", "エラー", "未記入")
# 出典の状態。空のときは URL の有無から決める
SOURCES_STATUS_VALUES = ("", "記録済み", "なし", "不明")

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_WS_RE = re.compile(r"\s+")
# ダッシュ類（‐ ‑ ‒ – — ― −）。長音符（ー）は含めない
_DASH_RE = re.compile("[\u2010-\u2015\u2212]")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_DANGEROUS_HEADS = ("=", "+", "-", "@", "\t", "\r")
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")
_COMMENT_RE = re.compile(r"\s+#.*$")
# csv のセルの長さの上限を上げるときの下限（sys.maxsize を受け付けない環境でも、これ以上にする）
_MIN_FIELD_SIZE_LIMIT = 16 * 1024 * 1024
# IDNA（ASCII）に変換したあとのドメインの形。ラベルは英数字・ハイフン・下線で、ハイフンで始まらず終わらない。
# ラベルを2つ以上 . でつなぐ
_DOMAIN_LABEL = r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?"
_DOMAIN_RE = re.compile(r"^(?:" + _DOMAIN_LABEL + r"\.)+" + _DOMAIN_LABEL + r"$")
# IDNA がラベルの区切りとみなす点（. と、全角・半角の句点。NFKC の後は 。 だけが残る）
_IDNA_DOTS_RE = re.compile("[.。．｡]")


class InputError(Exception):
    """入力ファイルや引数の誤り。各スクリプトの main で捕まえ、終了コード 2 で終わる。"""


def log(message):
    # type: (str) -> None
    """標準エラーに1行出す。"""
    print(message, file=sys.stderr, flush=True)


def normalize_text(text):
    # type: (str) -> str
    """
    照合用に表記をそろえる。NFKC（全角英数→半角、半角カナ→全角）、大文字・小文字の統一、
    ダッシュ類を - に、連続する空白を1つに。中黒・法人格・空白の有無の違いはそろえない（表記ゆれとして書く）。
    """
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = _DASH_RE.sub("-", text)
    return _WS_RE.sub(" ", text)


def format_rate(k, n):
    # type: (int, int) -> str
    """
    「k/n（xx.x%）」。割合は厳密な値（分数）から小数第1位で四捨五入する（5/80 → 6.3%）。
    float の書式は偶数丸めになり、6.25% を 6.2% と出すので使わない。分母が 0 なら「k/n（分母なし）」。
    """
    if not n:
        return "{}/{}（分母なし）".format(k, n)
    exact = Fraction(k * 1000, n)  # 割合（%）の 10 倍
    tenths = int(abs(exact) + Fraction(1, 2))  # 0 以上なので int は切り捨て
    sign = "-" if exact < 0 and tenths else ""
    return "{}/{}（{}{}.{}%）".format(k, n, sign, tenths // 10, tenths % 10)


def workspace_hint(path, name):
    # type: (str, str) -> str
    """
    既定の場所（path = <workspace>/<name>）にファイルがないときの案内。今のフォルダに同じ名前のファイルが
    あれば、ai-search/ の中で --workspace を付けずに実行した可能性が高いので、--workspace . を案内する文を返す。
    当たらなければ空。
    """
    try:
        if os.path.isfile(name) and os.path.abspath(name) != os.path.abspath(path):
            return ("今のフォルダに {} があります。ai-search/ の中で実行しているなら --workspace . を"
                    "付けてください".format(name))
    except (OSError, ValueError):
        pass
    return ""


def split_list(value, sep="|"):
    # type: (str, str) -> list
    """区切り文字で分け、前後の空白を除いて空の要素を捨てる。"""
    return [part.strip() for part in (value or "").split(sep) if part.strip()]


def parse_id_list(value):
    # type: (str) -> list
    """カンマか空白で区切った ID の一覧。順番を保ち、重複を除く。"""
    out = []
    for part in re.split(r"[,\s]+", value or ""):
        if part and part not in out:
            out.append(part)
    return out


def sanitize_cell(value):
    # type: (object) -> str
    """数式として実行されうるセル（先頭が = + - @ タブ CR）の先頭に ' を付ける。数値はそのまま。"""
    if value is None:
        return ""
    text = str(value)
    if text and text.startswith(_DANGEROUS_HEADS) and not _NUMBER_RE.match(text):
        return "'" + text
    return text


def unsanitize_cell(value):
    # type: (str) -> str
    """sanitize_cell で付けた先頭の ' を外す。"""
    if value and len(value) >= 2 and value[0] == "'" and value[1:].startswith(_DANGEROUS_HEADS):
        return value[1:]
    return value


def sha256_file(path):
    # type: (str) -> str
    """ファイルの SHA-256（16進の小文字、64桁）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_bytes(data):
    # type: (bytes) -> str
    """BOM があればそれに従い、なければ UTF-8、だめなら cp932 で読む。BOM の文字は残さない。"""
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16", errors="replace").lstrip("﻿")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp932")
    except UnicodeDecodeError:
        log("警告: UTF-8 としても cp932 としても読めない文字を置き換えて読みました")
        return data.decode("utf-8", errors="replace")


def read_text(path):
    # type: (str) -> str
    """テキストファイルを読み、改行を \\n にそろえる。"""
    with open(path, "rb") as f:
        text = decode_bytes(f.read())
    return text.replace("\r\n", "\n").replace("\r", "\n")


def raise_csv_field_size_limit():
    # type: () -> None
    """
    csv モジュールの1つのセルの上限（既定 131072 文字）を上げる。write_csv は長さの上限なしに書くので、
    読む側で既定の上限のままだと、自分で書いた CSV を読めない。sys.maxsize は、C の long が 32 ビットの
    環境（Windows）で OverflowError になるので、受け付けられるまで半分ずつ下げる。
    """
    limit = sys.maxsize
    while limit > _MIN_FIELD_SIZE_LIMIT:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 2
    csv.field_size_limit(_MIN_FIELD_SIZE_LIMIT)


def strip_nul(text):
    # type: (str) -> str
    """NUL（\\x00）を除く。Python 3.9 の csv は NUL を含む行を読めず、3.11 以降は読むので、版の差を持ち込まない。"""
    return text.replace("\x00", "") if "\x00" in text else text


def read_csv(path):
    # type: (str) -> tuple
    """
    CSV を (列名の一覧, 行の一覧) で返す。セルは ' を外して前後の空白を除く。すべて空の行は捨てる。
    NUL は除いてから読み、除いたことを警告する（Python の版によって読める・読めないが変わらないように）。
    1つのセルの長さの上限は raise_csv_field_size_limit で上げておく。
    """
    text = read_text(path)
    nul_count = text.count("\x00")
    if nul_count:
        log("警告: {} の NUL 文字（{} 個）を除いて読みました".format(path, nul_count))
        text = strip_nul(text)
    raise_csv_field_size_limit()
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    fields = [unsanitize_cell(name.strip()).strip() for name in rows[0]]
    out = []
    for raw in rows[1:]:
        cells = [unsanitize_cell(cell.strip()).strip() for cell in raw]
        if not any(cells):
            continue
        row = {}
        for i, name in enumerate(fields):
            row[name] = cells[i] if i < len(cells) else ""
        out.append(row)
    return fields, out


def write_csv(path, fieldnames, rows):
    # type: (str, list, list) -> None
    """BOM 付き UTF-8 の CSV を書く。すべてのセルから NUL を除き、sanitize_cell を当てる。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        write_csv_stream(f, fieldnames, rows, sanitize=True)


def write_csv_stream(stream, fieldnames, rows, sanitize=True):
    # type: (object, list, list, bool) -> None
    """
    開いたストリームに CSV を書く。標準出力に書くときは sanitize=False にする。
    列名とセルの NUL は、sanitize の有無にかかわらず除く（Python 3.9 の csv は NUL を含む行を読めないため）。
    """
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow([strip_nul(str(name)) for name in fieldnames])
    for row in rows:
        values = []
        for name in fieldnames:
            value = row.get(name, "")
            text = strip_nul("" if value is None else str(value))
            values.append(sanitize_cell(text) if sanitize else text)
        writer.writerow(values)


def parse_front_matter(text):
    # type: (str) -> tuple
    """
    回答ファイルの先頭の欄を解析して (欄の辞書, 本文, エラーの一覧) を返す。
    1行目が --- なら、次の --- の行までを「key: value」として読む。値の後ろの「空白 + #」以降は
    コメントとして捨てる（C# のように空白のない # は値に残す）。キーは小文字にする。
    """
    text = (text or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text, ["先頭の欄（1行目の ---）がありません"]
    meta = {}
    errors = []
    end = None
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            end = i
            break
        if not line.strip():
            continue
        match = _KEY_RE.match(line.strip())
        if not match:
            errors.append("先頭の欄の {} 行目を読めません: {}".format(i + 1, line.strip()))
            continue
        value = _COMMENT_RE.sub("", match.group(2)).strip()
        meta[match.group(1).lower()] = value
    if end is None:
        return meta, "", errors + ["先頭の欄の終わりの --- がありません"]
    return meta, "\n".join(lines[end + 1:]), errors


def _to_ascii_labels(host):
    # type: (str) -> str
    """
    ホスト名をラベルごとに IDNA（ASCII、Python 標準の idna コーデック）に変換する。日本語のラベルは xn-- の形になり、
    ASCII のラベルはそのまま残る。変換できなければ UnicodeError（空のラベル、63 文字を超えるラベルなど）。
    """
    labels = _IDNA_DOTS_RE.split(host)
    return ".".join(label.encode("idna").decode("ascii") for label in labels)


def ascii_host(host):
    # type: (str) -> str
    """
    URL のホストを、entities.csv のドメインと同じ形にそろえる（照合用）。NFKC → 前後の空白を除く → 小文字 →
    末尾の . を除く → ラベルごとに IDNA（ASCII）。日本語ドメインの Unicode 表記と Punycode 表記（xn--）は同じ形になる。
    IPv6 のアドレス（: を含む）と、変換できないホストは、変換の手前の形のまま返す。
    """
    host = unicodedata.normalize("NFKC", host or "").strip().lower().rstrip(".")
    if not host or ":" in host:
        return host
    try:
        return _to_ascii_labels(host)
    except UnicodeError:
        return host


def normalize_domain(value, where):
    # type: (str, str) -> str
    """
    entities.csv のドメインを照合用の形にそろえる。NFKC → 前後の空白を除く → 小文字 → 末尾の . を除く →
    先頭の www. を除く → ラベルごとに IDNA（ASCII）。URL のホストも ascii_host で同じ形にしてから比べる。
    ワイルドカード、先頭の点、ポート、空のラベル、カンマ区切り、スキームやパス、そのほかドメインの形でないものは、
    理由を付けて InputError にする（黙って一度も一致しないドメインにしないため）。
    """
    def fail(reason):
        raise InputError("{}: ドメインには example.jp の形だけを書いてください（{}）: {}".format(where, reason, value))

    domain = unicodedata.normalize("NFKC", value or "").strip().lower().rstrip(".。")
    if "://" in domain or "/" in domain:
        fail("スキームやパスは不要")
    if any(sep in domain for sep in (",", "、", ";")):
        fail("複数のドメインは | で区切ってください")
    if _WS_RE.search(domain):
        fail("空白は使えません")
    if "*" in domain:
        fail("ワイルドカード（*）は使えません。example.jp と書けばサブドメインも一致します")
    if domain.startswith(".") or domain.startswith("。"):
        fail("先頭の . は不要です。example.jp と書けばサブドメインも一致します")
    if ":" in domain:
        fail("ポート（:443 など）は書かないでください")
    if not domain:
        fail("ドメインの形ではありません")
    labels = _IDNA_DOTS_RE.split(domain)
    if any(not label for label in labels):
        fail("空のラベルがあります（.. のように点が続いています）")
    if len(labels) > 2 and labels[0] == "www":
        labels = labels[1:]
    try:
        domain = _to_ascii_labels(".".join(labels))
    except UnicodeError:
        fail("ドメインとして読めません。点で区切った1つの部分が 63 文字を超えるか、使えない文字があります")
    if not _DOMAIN_RE.match(domain):
        fail("ドメインの形ではありません。英数字・ハイフン・日本語の部分を . でつないでください")
    return domain


def load_entities(path):
    # type: (str) -> list
    """entities.csv を読み、検証した辞書の一覧を返す。"""
    fields, rows = read_csv(path)
    required = ("entity_id", "kind", "name", "terms", "exclude_terms", "domains")
    missing = [name for name in required if name not in fields]
    if missing:
        raise InputError("{}: 列が足りません: {}".format(path, ", ".join(missing)))
    entities = []
    seen = set()
    for n, row in enumerate(rows, start=2):
        where = "{} の {} 行目".format(path, n)
        entity_id = row["entity_id"]
        if not ID_RE.match(entity_id):
            raise InputError("{}: entity_id は英数字で始まり、英数字・ハイフン・下線だけにしてください: {}".format(
                where, entity_id))
        if entity_id in seen:
            raise InputError("{}: entity_id が重複しています: {}".format(where, entity_id))
        seen.add(entity_id)
        kind = row["kind"]
        if kind not in ENTITY_KINDS:
            raise InputError("{}: kind は own か competitor にしてください: {}".format(where, kind))
        terms = split_list(row["terms"])
        domains = [normalize_domain(d, where) for d in split_list(row["domains"])]
        if not terms and not domains:
            raise InputError("{}: terms と domains のどちらかは必要です".format(where))
        entities.append({
            "entity_id": entity_id,
            "kind": kind,
            "name": row["name"],
            "terms": terms,
            "exclude_terms": split_list(row["exclude_terms"]),
            "domains": domains,
        })
    if not any(e["kind"] == "own" for e in entities):
        raise InputError("{}: kind が own（自社）の行が1つもありません".format(path))
    own_domains = set(d for e in entities if e["kind"] == "own" for d in e["domains"])
    for e in entities:
        if e["kind"] == "competitor":
            shared = sorted(own_domains.intersection(e["domains"]))
            if shared:
                raise InputError("{}: 同じドメインが自社と競合（{}）の両方にあります: {}".format(
                    path, e["entity_id"], ", ".join(shared)))
    return entities


def load_prompts(path):
    # type: (str) -> dict
    """prompts.csv を読み、prompt_id をキーにした辞書を返す。"""
    fields, rows = read_csv(path)
    required = ("prompt_id", "prompt", "stage", "branded")
    missing = [name for name in required if name not in fields]
    if missing:
        raise InputError("{}: 列が足りません: {}".format(path, ", ".join(missing)))
    prompts = {}
    for n, row in enumerate(rows, start=2):
        where = "{} の {} 行目".format(path, n)
        pid = row["prompt_id"]
        if not ID_RE.match(pid):
            raise InputError("{}: prompt_id は英数字で始まり、英数字・ハイフン・下線だけにしてください: {}".format(
                where, pid))
        if pid in prompts:
            raise InputError("{}: prompt_id が重複しています: {}".format(where, pid))
        if row["stage"] not in STAGES:
            raise InputError("{}: stage は {} のどれかにしてください: {}".format(where, " / ".join(STAGES), row["stage"]))
        if row["branded"] not in BRANDED_VALUES:
            raise InputError("{}: branded は {} のどちらかにしてください: {}".format(
                where, " / ".join(BRANDED_VALUES), row["branded"]))
        prompts[pid] = row
    return prompts


# argparse の誤りの文（英語）を日本語にする。Python 3.9〜3.13 で同じ文
_ARGPARSE_MESSAGES = (
    (re.compile(r"^the following arguments are required: (.+)$"), "次の引数が必要です: {0}"),
    (re.compile(r"^unrecognized arguments: (.+)$"), "使えない引数があります: {0}"),
    (re.compile(r"^ambiguous option: (\S+) could match (.+)$"),
     "{0} は複数の引数（{1}）に当てはまります。省略せずに書いてください"),
    (re.compile(r"^argument (\S+): expected one argument$"), "{0} に値を指定してください"),
    (re.compile(r"^argument (\S+): invalid int value: (.+)$"), "{0} は整数で指定してください: {1}"),
    (re.compile(r"^argument (\S+): invalid float value: (.+)$"), "{0} は数値で指定してください: {1}"),
    (re.compile(r"^argument (\S+): invalid choice: (.+)$"), "{0} に使えない値です: {1}"),
    (re.compile(r"^argument (\S+): invalid \S+ value: (.+)$"), "{0} の値が正しくありません: {1}"),
    (re.compile(r"^argument (\S+): ignored explicit argument (.+)$"), "{0} には値を付けられません: {1}"),
    (re.compile(r"^argument (\S+): not allowed with argument (.+)$"), "{0} は {1} と一緒に使えません"),
    (re.compile(r"^argument (\S+): (.+)$"), "{0}: {1}"),
)


def translate_argparse(message):
    # type: (str) -> str
    """argparse の誤りの文を日本語にする。知らない文はそのまま返す。"""
    for pattern, template in _ARGPARSE_MESSAGES:
        match = pattern.match(message)
        if match:
            return template.format(*match.groups())
    return message


class ArgumentParser(argparse.ArgumentParser):
    """-h の説明と引数の誤りの文を日本語にする。引数の誤りは終了コード 2 で終える。"""

    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        argparse.ArgumentParser.__init__(self, *args, **kwargs)
        self.add_argument("-h", "--help", action="help", help="この使い方を表示して終わる")

    def error(self, message):
        # type: (str) -> None
        self.exit(2, "エラー: 引数の誤り: {}（--help で使い方を表示）\n".format(translate_argparse(message)))
