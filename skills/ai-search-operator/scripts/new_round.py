#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_round.py - 観測ラウンドの回答ファイルのひな形を作る

目的:
  1回の観測（ラウンド）で記録する回答ファイルを、プロンプト × サービス × 回数の数だけ作る。
  先頭の欄（round、prompt_id、prompt、service など）を埋め、本文には見出し（## 回答、## 出典）だけを置く。
  利用者は AI の回答と出典を貼り付け、observed_at を尋ねた日時に直す。mode は --mode で全ファイルに入れられる
  （付けなければ空。利用者が回答を貼るときに書く）。

入力:
  <ワークスペース>/prompts.csv（既定のワークスペースは実行したフォルダの ai-search）。
  active が yes の行を使う（--prompts があれば、その ID だけを使う）。active の値は大文字・小文字を区別しない。
  active の列がなければ全件を使う。yes / no 以外の値があれば入力エラーにする。
  次のときも入力エラーにする（終了コード 2）:
  - 使う prompt_id が 64 字を超える（回答ファイルの名前に使うため）
  - 使う prompt_id に、大文字・小文字だけが違うもの（P001 と p001）がある。Windows と macOS の既定の
    ファイルシステムでは同じファイル名になり、片方のファイルが作られないため
  - prompt に制御文字（NUL など。改行とタブは除く）がある
  - prompts.csv を CSV として読めない
  - --mode、--region、--language に UTF-8 で書けない文字がある（UTF-8 でない端末から渡したバイトなど。
    回答ファイルに書けないため、ファイルを1件も作らずに止める）

出力:
  <ワークスペース>/answers/<ラウンド>/<サービス>/<プロンプトID>-<回数>.md
  - 同じ名前のファイルがあれば上書きしない（作らなかった件数を表示する）。そのファイルの先頭の欄の
    round、prompt_id、surface、login、region、language（--mode を付けたときは mode も）が今回の指定と違えば
    警告する。ファイルの名前に条件（surface など）は入らないので、条件を変えて観測するときは別のラウンド名にする。
  - mode は --mode の値（付けなければ空）。「/」、「行頭か空白の直後の #」、制御文字を含む値は入力エラーにする
    （/ は compare_runs.py の primary_group の区切り、# は先頭の欄のコメントの印のため）。前後の空白は除く。
  - observed_at には、ラウンド名が日付（YYYY-MM-DD）ならその日付と空白を入れる。利用者は尋ねた日時に直す
    （1ラウンドを複数の日に分けるので、別の日に尋ねたら日付も直す）。日付でなければ空にする。
  - status と sources_status は空にする。空なら normalize_observations.py が回答と URL の有無から決めるので、
    ふつうは書き換えなくてよい。AI の回答が出なかった・拒否された・エラーになったときだけ書く。
  - ひな形の形は templates/answer.md と同じ（テストで一致を確かめている）。
  - フォルダをすべて作ってから回答ファイルを書く。フォルダを作れない（同じ名前の普通のファイルがある、
    権限がない など）ときは、回答ファイルを1件も作らずに入力エラーにする。

処理の要約と警告は標準エラー出力に出す。終了コード: 0 = 成功、2 = 入力・引数の誤り、1 = 想定外のエラー。
どのフォルダから実行しても、同じフォルダの ai_search_common.py を読む。スキルのフォルダに
__pycache__ を残さない。
"""
import argparse
import csv
import datetime
import errno
import os
import re
import sys
import traceback

sys.dont_write_bytecode = True  # スキルのフォルダに __pycache__ を残さない
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    # python -I や python -P で起動すると、スクリプトのフォルダは sys.path に入らない。
    # どの起動のしかたでも、同じフォルダの共通処理を読む
    sys.path.insert(0, _HERE)

from ai_search_common import (  # noqa: E402
    ID_RE,
    ArgumentParser,
    LOGINS,
    SERVICES,
    SURFACES,
    InputError,
    load_prompts,
    log,
    parse_front_matter,
    parse_id_list,
    read_text,
    workspace_hint,
)

# 回答ファイルの先頭の欄（この順番で書く）。templates/answer.md と同じ
ANSWER_FIELDS = (
    "round", "prompt_id", "prompt", "observed_at", "service", "surface", "mode", "login", "region",
    "repeat", "language", "status", "sources_status", "accuracy", "accuracy_note", "reviewed_by",
)
# 値を渡さなかった欄に入れる既定の値
ANSWER_DEFAULTS = {"surface": "web", "login": "なし", "region": "JP", "language": "ja", "accuracy": "未確認"}
ANSWER_BODY = "## 回答\n\n## 出典\n"

MAX_REPEATS = 20
# ラウンド名と prompt_id の長さの上限（フォルダ名・ファイル名に使うため）
MAX_NAME_LENGTH = 64
# 既存のファイルと今回の指定の違いを、1件ずつ表示する上限
MAX_LISTED = 10
# 既存のファイルと比べる欄。ファイルの名前に入らない条件と、大文字・小文字だけの違いで同じパスになりうる欄
COMPARE_FIELDS = ("round", "prompt_id", "surface", "login", "region", "language")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# region と language に使える値（空白、#、制御文字を含まない。# は先頭の欄でコメントとして扱われるため）
_TOKEN_RE = re.compile(r"[^\s#\x00-\x1f\x7f]*")
# 「行頭か空白」の直後の #。先頭の欄では、そこから後ろがコメントとして読み飛ばされる
_COMMENT_HASH_RE = re.compile(r"(^|\s)#")
# mode に入れてはいけない文字（改行・タブを含む制御文字と /）
_MODE_FORBIDDEN_RE = re.compile(r"[\x00-\x1f\x7f/]")
_NEWLINE_RE = re.compile(r"\s*[\r\n]+\s*")
# prompt に入れてはいけない制御文字（改行 \n \r とタブ \t は除く。改行は空白に置き換えて書く）
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

NEXT_STEPS = (
    "次の手順: 毎回新しい会話で prompt の文を尋ね、回答を ## 回答、出典の URL を ## 出典 に貼る。"
    "observed_at は尋ねた日時にする（開始日を入れてあるので、別の日に尋ねたら日付も直す）。"
    "mode が空なら、ラウンドの前に決めた表記を書く。貼り終えたら normalize_observations.py を実行する"
)

# OSError の理由（errno）を日本語で示す
_OS_REASONS = {
    errno.EEXIST: "同じ名前のファイルがあります",
    errno.ENOTDIR: "パスの途中に普通のファイルがあります",
    errno.EISDIR: "同じ名前のフォルダがあります",
    errno.EACCES: "権限がありません",
    errno.EPERM: "権限がありません",
    errno.ENAMETOOLONG: "名前が長すぎます",
    errno.ENOSPC: "ディスクの空きがありません",
    errno.EROFS: "読み取り専用の場所です",
}


def _os_reason(error):
    # type: (OSError) -> str
    """OSError の理由を短い文にする。対応表にない errno は OS の説明をそのまま使う。"""
    reason = _OS_REASONS.get(error.errno)
    if reason:
        return reason
    return error.strerror or str(error)


def _one_line(value):
    # type: (str) -> str
    """改行を空白1つに置き換える（先頭の欄は1行に1つの値しか書けないため）。"""
    return _NEWLINE_RE.sub(" ", value)


def build_answer(meta):
    # type: (dict) -> str
    """
    回答ファイルの中身を組み立てる。meta にない欄は ANSWER_DEFAULTS の値（なければ空）にする。
    ANSWER_FIELDS にない欄は書かない。空の欄は「key:」だけにし、後ろに空白を付けない。
    """
    lines = ["---"]
    for key in ANSWER_FIELDS:
        value = meta[key] if key in meta else ANSWER_DEFAULTS.get(key, "")
        value = _one_line("" if value is None else str(value))
        lines.append("{}: {}".format(key, value) if value else "{}:".format(key))
    lines.append("---")
    return "\n".join(lines) + "\n" + ANSWER_BODY


def _observed_date(round_name):
    # type: (str) -> str
    """ラウンド名が実在する日付（YYYY-MM-DD）なら、その日付と空白（時刻を書く場所）を返す。"""
    if not _DATE_RE.match(round_name):
        return ""
    try:
        datetime.datetime.strptime(round_name, "%Y-%m-%d")
    except ValueError:
        return ""
    return round_name + " "


def _select_prompts(prompts, prompt_ids):
    # type: (dict, list) -> list
    """使うプロンプトの ID を順番どおりに返す。"""
    if prompt_ids:
        unknown = [pid for pid in prompt_ids if pid not in prompts]
        if unknown:
            raise InputError("prompts.csv にない prompt_id が指定されました: {}".format(", ".join(unknown)))
        for pid in prompt_ids:
            active = prompts[pid].get("active")
            if active is not None and active.lower() != "yes":
                log("警告: {} は active が「{}」ですが、--prompts で指定されたので作ります".format(pid, active or "空"))
        return list(prompt_ids)
    rows = list(prompts.values())
    if rows and "active" not in rows[0]:
        log("警告: prompts.csv に active の列がないため、全件を使います")
        return [row["prompt_id"] for row in rows]
    invalid = ["{}（{}）".format(row["prompt_id"], row["active"] or "空") for row in rows
               if row["active"].lower() not in ("yes", "no")]
    if invalid:
        raise InputError("prompts.csv の active は yes か no にしてください: {}".format(", ".join(invalid)))
    selected = [row["prompt_id"] for row in rows if row["active"].lower() == "yes"]
    if not selected:
        raise InputError("prompts.csv に active が yes のプロンプトがありません（--prompts で ID を指定することもできます）")
    return selected


def _check_selected(prompts, selected):
    # type: (dict, list) -> None
    """使う prompt_id の長さ、大文字・小文字だけの違い、prompt の中身を確かめる。誤りは InputError。"""
    too_long = [pid for pid in selected if len(pid) > MAX_NAME_LENGTH]
    if too_long:
        raise InputError("prompts.csv の prompt_id は {} 字までにしてください（回答ファイルの名前に使うため）: {}".format(
            MAX_NAME_LENGTH, ", ".join(too_long)))
    groups = {}  # type: dict
    for pid in selected:
        groups.setdefault(pid.lower(), []).append(pid)
    same_file = [ids for ids in groups.values() if len(ids) > 1]
    if same_file:
        raise InputError(
            "大文字・小文字だけが違う prompt_id があります（Windows と macOS では同じファイル名になり、"
            "片方の回答ファイルが作られません）: {}。まだ観測に使っていないほうの ID を変えるか、"
            "--prompts で片方だけを選んでください".format(" / ".join(", ".join(ids) for ids in same_file)))
    empty = [pid for pid in selected if not prompts[pid]["prompt"]]
    if empty:
        raise InputError("prompts.csv の prompt が空です: {}".format(", ".join(empty)))
    control = []
    for pid in selected:
        found = sorted(set(_CONTROL_RE.findall(prompts[pid]["prompt"])))
        if found:
            control.append("{}（{}）".format(pid, ", ".join("U+{:04X}".format(ord(ch)) for ch in found)))
    if control:
        raise InputError("prompts.csv の prompt に制御文字があります（NUL など。改行とタブは使えます）: {}".format(
            ", ".join(control)))
    for pid in selected:
        _check_utf8("prompts.csv の {} の prompt".format(pid), prompts[pid]["prompt"], hint="")


# 引数に UTF-8 で書けない文字があるときの説明
_ARG_ENCODING_HINT = "端末の文字コードが UTF-8 でないときや、別の文字コードの文を貼ったときに起きます"


def _check_utf8(label, value, hint=_ARG_ENCODING_HINT):
    # type: (str, str, str) -> None
    """
    value を UTF-8 で書けるかを確かめる。書けなければ InputError。
    UTF-8 でない端末から渡したバイト（$'\\xff' など）は、Python の中で surrogate の文字（\\udcff）になり、
    回答ファイルに書こうとした時点で失敗する。ファイルを作る前に止める。
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InputError("{} に UTF-8 で書けない文字があります{}: {!r}".format(
            label, "（{}）".format(hint) if hint else "", value)) from None


def _check_mode(mode):
    # type: (str) -> str
    """--mode の値を確かめ、前後の空白を除いて返す。誤りは InputError。"""
    mode = (mode or "").strip()
    _check_utf8("--mode", mode)
    if _MODE_FORBIDDEN_RE.search(mode):
        raise InputError("--mode には「/」と制御文字を含めないでください（/ は compare_runs.py の primary_group の"
                         "区切りに使うため。モデル名を足すなら「検索あり・Think」のように ・ でつなぐ）: {!r}".format(mode))
    if _COMMENT_HASH_RE.search(mode):
        raise InputError("--mode に「行頭か空白の直後の #」を含めないでください（回答ファイルの先頭の欄では、そこから後ろが"
                         "コメントとして読み飛ばされるため）: {!r}".format(mode))
    return mode


def plan_round(prompts, round_name, services, repeats, prompt_ids,
               surface="web", login="なし", region="JP", language="ja", mode=""):
    # type: (dict, str, list, int, list, str, str, str, str, str) -> list
    """
    作る回答ファイルの一覧を返す。要素は (ワークスペースからの相対パス（/ 区切り）, 先頭の欄の辞書)。
    並びはプロンプト → サービス → 回数の順。引数の誤りは InputError にする。
    """
    # fullmatch にする（match だと末尾の改行を許してしまい、フォルダ名に入る）
    if not ID_RE.fullmatch(round_name or ""):
        raise InputError("--round は英数字で始まり、英数字・ハイフン・下線だけにしてください（例: 2026-10-01）: {}".format(
            round_name))
    if len(round_name) > MAX_NAME_LENGTH:
        raise InputError("--round は {} 字までにしてください（フォルダ名に使うため）: {} 字".format(
            MAX_NAME_LENGTH, len(round_name)))
    if not services:
        raise InputError("--services にサービスを1つ以上指定してください（{}）".format(", ".join(SERVICES)))
    unknown = [s for s in services if s not in SERVICES]
    if unknown:
        raise InputError("--services に使えないサービスがあります: {}（使えるもの: {}）".format(
            ", ".join(unknown), ", ".join(SERVICES)))
    if not isinstance(repeats, int) or not 1 <= repeats <= MAX_REPEATS:
        raise InputError("--repeats は 1〜{} の整数にしてください: {}".format(MAX_REPEATS, repeats))
    if surface not in SURFACES:
        raise InputError("--surface は {} のどれかにしてください: {}".format(" / ".join(SURFACES), surface))
    if login not in LOGINS:
        raise InputError("--login は {} のどれかにしてください: {}".format(" / ".join(LOGINS), login))
    for option, value in (("--region", region), ("--language", language)):
        _check_utf8(option, value)
        if not _TOKEN_RE.fullmatch(value):
            raise InputError("{} には空白、#、制御文字を含めないでください: {!r}".format(option, value))
    mode = _check_mode(mode)

    selected = _select_prompts(prompts, prompt_ids)
    _check_selected(prompts, selected)
    observed_at = _observed_date(round_name)
    plan = []
    for pid in selected:
        text = _one_line(prompts[pid]["prompt"])
        if text != prompts[pid]["prompt"]:
            log("警告: {} の prompt の改行を空白に置き換えて書きます".format(pid))
        if _COMMENT_HASH_RE.search(text):
            log("警告: {} の prompt に「行頭か空白の直後の #」があります。回答ファイルの先頭の欄では # から後ろが"
                "コメントとして読み飛ばされるため、normalize_observations.py が prompt の不一致を警告します。"
                "まだ観測に使っていないプロンプトなら # の前の空白を除き、使ったあとなら新しい ID で書き直してください".format(pid))
        for service in services:
            for n in range(1, repeats + 1):
                rel = "answers/{}/{}/{}-{}.md".format(round_name, service, pid, n)
                meta = {
                    "round": round_name, "prompt_id": pid, "prompt": text, "observed_at": observed_at,
                    "service": service, "surface": surface, "mode": mode, "login": login, "region": region,
                    "repeat": str(n), "language": language, "status": "", "sources_status": "",
                    "accuracy": "未確認", "accuracy_note": "", "reviewed_by": "",
                }
                plan.append((rel, meta))
    return plan


def compare_existing(path, meta):
    # type: (str, dict) -> list
    """
    既にある回答ファイルの先頭の欄を読み、COMPARE_FIELDS（meta の mode が空でなければ mode も）のうち
    今回の指定と違う欄を説明する文の一覧を返す。
    同じなら空の一覧。読めないときは、その理由を1つだけ入れて返す。
    """
    if not os.path.isfile(path):
        return ["普通のファイルではないため読めません"]
    try:
        text = read_text(path)
    except OSError as e:
        return ["読めません（{}）".format(_os_reason(e))]
    existing, _body, errors = parse_front_matter(text)
    if not existing:
        return ["先頭の欄を読めません（{}）".format(errors[0] if errors else "欄がありません")]
    out = []
    # mode は --mode を付けたときだけ比べる（付けなければ、利用者が記入した mode と比べても意味がない）
    fields = COMPARE_FIELDS + ("mode",) if meta.get("mode") else COMPARE_FIELDS
    for key in fields:
        old = existing.get(key, "")
        new = meta.get(key, "")
        if old == new:
            continue
        note = ""
        if key in ("round", "prompt_id") and old.lower() == new.lower():
            note = "。大文字・小文字だけが違う名前は、Windows と macOS では同じファイルになります"
        out.append("{}={}（今回の指定は {}{}）".format(key, old or "空", new or "空", note))
    return out


def _blocking_path(directory):
    # type: (str) -> str
    """directory を作るのを妨げるもの（パスの途中にある、フォルダでないもの）のパスを返す。なければ空。"""
    path = directory
    while path:
        if os.path.lexists(path):
            return "" if os.path.isdir(path) else path
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return ""


def _remove_quietly(path):
    # type: (str) -> None
    try:
        os.remove(path)
    except OSError:
        pass


def write_round(workspace, plan):
    # type: (str, list) -> tuple
    """
    回答ファイルを書く。既にあるファイルは上書きしない。
    (作った件数, 作らなかった件数, 違いの一覧) を返す。違いの一覧の要素は、既にあったファイルのうち
    先頭の欄が今回の指定と違うか読めないものの (ワークスペースからの相対パス, compare_existing の結果)。
    フォルダはファイルを書く前にすべて作る。フォルダやファイルを作れなければ InputError にする。
    """
    targets = [(rel, os.path.join(workspace, *rel.split("/")), meta) for rel, meta in plan]
    directories = []  # type: list
    for _rel, path, _meta in targets:
        directory = os.path.dirname(path)
        if directory not in directories:
            directories.append(directory)
    # 何かを作る前に、フォルダを作れるかを確かめる（途中まで書いたファイルを残さないため）
    for directory in directories:
        blocker = _blocking_path(directory)
        if blocker == directory:
            raise InputError("フォルダ {} を作れません。同じ名前のファイルがあります（回答ファイルは作っていません）".format(
                directory))
        if blocker:
            raise InputError("フォルダ {} を作れません。パスの途中の {} がフォルダではありません（回答ファイルは作っていません）".format(
                directory, blocker))
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as e:
            raise InputError("フォルダ {} を作れません: {}（回答ファイルは作っていません）".format(directory, _os_reason(e)))

    created = skipped = 0
    differences = []
    for rel, path, meta in targets:
        if os.path.lexists(path):
            skipped += 1
            diff = compare_existing(path, meta)
            if diff:
                differences.append((rel, diff))
            continue
        # ファイルを作る前にバイト列にする。UTF-8 で書けない文字があれば、ここで止まり、ファイルは残らない
        # （plan_round で確かめているので、ここで止まるのは想定外のとき。終了コード 1 になる）
        data = build_answer(meta).encode("utf-8")
        try:
            # "x" は、ファイルがあれば FileExistsError になる（確かめてから開くまでの間に作られても上書きしない）
            f = open(path, "xb")
        except FileExistsError:
            skipped += 1
            diff = compare_existing(path, meta)
            if diff:
                differences.append((rel, diff))
            continue
        except OSError as e:
            raise InputError("回答ファイル {} を作れません: {}（ここまでに {} 件作りました）".format(
                path, _os_reason(e), created))
        # 書きかけのファイルを残すと、次の実行で「既にある」とみなされ、利用者が消すまでひな形が作られない。
        # そのため、どんな理由で止まっても消す
        try:
            with f:
                f.write(data)
        except OSError as e:
            _remove_quietly(path)
            raise InputError("回答ファイル {} を書けません: {}（書きかけのファイルは消しました。ここまでに {} 件作りました）".format(
                path, _os_reason(e), created))
        except BaseException:  # 想定外のエラーや Ctrl+C の中断でも消してから伝える
            _remove_quietly(path)
            raise
        created += 1
    return created, skipped, differences


DESCRIPTION = """観測ラウンドの回答ファイルのひな形を作る。

prompts.csv の active が yes のプロンプト（--prompts があればその ID）について、
サービス × 回数の数だけ answers/<ラウンド>/<サービス>/<プロンプトID>-<回数>.md を作る。
同じ名前のファイルがあれば上書きしない。"""

EPILOG = """例:
  python3 new_round.py --round 2026-10-01 --services chatgpt,google-ai-mode --repeats 3 --mode 検索あり

作ったあと:
  各サービスで毎回新しい会話を開いて prompt の文を尋ね、回答の本文を ## 回答 に、出典の URL を ## 出典 に貼る。
  observed_at は尋ねた日時にする（開始日を入れてあるので、別の日に尋ねたら日付も直す）。
  --mode を付けなかったときは、mode にラウンドの前に決めた表記（例: 検索あり）を書く。
  AI の回答が出なかった・拒否された・エラーになったときは status に書く（AI の回答なし / 回答拒否 / エラー）。
  貼り終えたら normalize_observations.py を実行する。

条件を変えるとき:
  回答ファイルの名前に --surface、--login、--mode、--region、--language の値は入らない。
  同じラウンドで条件を変えて観測するときは、別のラウンド名にする。

終了コード: 0 = 成功、2 = 入力・引数の誤り、1 = 想定外のエラー"""

def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = ArgumentParser(prog="new_round.py", description=DESCRIPTION, epilog=EPILOG)
    parser.add_argument("--round", required=True, dest="round_name", metavar="ROUND",
                        help="ラウンドの名前。英数字で始まり、英数字・ハイフン・下線だけ（{} 字まで）。"
                             "開始日（例 2026-10-01）を勧める".format(MAX_NAME_LENGTH))
    parser.add_argument("--services", required=True,
                        help="観測するサービス（, 区切り）: " + ", ".join(SERVICES))
    parser.add_argument("--repeats", type=int, default=3,
                        help="1プロンプト・1サービスあたりの回数（1〜{}。既定 3）".format(MAX_REPEATS))
    parser.add_argument("--workspace", default="ai-search", help="観測データのフォルダ（既定 ai-search。作業フォルダの中の ai-search/）")
    parser.add_argument("--surface", default="web", help="画面か API か: {}（既定 web）".format(" / ".join(SURFACES)))
    parser.add_argument("--login", default="なし", help="ログインの状態: {}（既定 なし）".format(" / ".join(LOGINS)))
    parser.add_argument("--mode", default="",
                        help="全ファイルの mode に入れる値（例: 検索あり、検索あり・Think）。既定は空（回答を貼るときに書く）。"
                             "「/」と「空白の直後の #」は使えない")
    parser.add_argument("--region", default="JP", help="地域（既定 JP）")
    parser.add_argument("--language", default="ja", help="回答の言語の設定（既定 ja）")
    parser.add_argument("--prompts", default="",
                        help="使うプロンプトの ID（, 区切り）。既定は prompts.csv の active が yes の全件")
    return parser


def _load_prompts(path):
    # type: (str) -> dict
    """prompts.csv を読む。CSV として読めない・ファイルを読めないときは InputError にする。"""
    try:
        return load_prompts(path)
    except csv.Error as e:
        # Python 3.9 の csv は NUL で csv.Error を出す（3.13 は通すので、prompt の制御文字として plan_round で止める）
        detail = "NUL 文字があります" if "NUL" in str(e) else str(e)
        raise InputError("{} を CSV として読めません（{}）。NUL などの制御文字を除いてください".format(path, detail))
    except OSError as e:
        raise InputError("{} を読めません: {}".format(path, _os_reason(e)))


def run(args):
    # type: (argparse.Namespace) -> int
    prompts_path = os.path.join(args.workspace, "prompts.csv")
    if not os.path.isfile(prompts_path):
        hint = workspace_hint(prompts_path, "prompts.csv")
        if hint:
            raise InputError("{} がありません。{}".format(prompts_path, hint))
        raise InputError("{} がありません。先に prompts.csv を作ってください（templates/prompts.csv と手順書 02）".format(
            prompts_path))
    prompts = _load_prompts(prompts_path)
    services = parse_id_list(args.services)
    plan = plan_round(prompts, args.round_name, services, args.repeats, parse_id_list(args.prompts),
                      surface=args.surface, login=args.login, region=args.region, language=args.language,
                      mode=args.mode)
    created, skipped, differences = write_round(args.workspace, plan)

    n_prompts = len(plan) // (len(services) * args.repeats)
    round_dir = os.path.join(args.workspace, "answers", args.round_name)
    log("回答ファイルを {} 件作りました: {}".format(created, round_dir))
    log("既にあったので作らなかったファイル: {} 件（上書きしていません）".format(skipped))
    if differences:
        log("警告: 既にあったファイルのうち {} 件は、先頭の欄が今回の指定と違うか、読めません:".format(len(differences)))
        for rel, diff in differences[:MAX_LISTED]:
            log("  {}: {}".format(rel, "、".join(diff)))
        if len(differences) > MAX_LISTED:
            log("  ほか {} 件".format(len(differences) - MAX_LISTED))
        log("  ファイルの名前に条件（surface、login、mode、region、language）は入りません。"
            "条件を変えて観測するときは、別のラウンド名にしてください")
        if any(item.startswith("mode=空") for _rel, diff in differences for item in diff):
            log("  mode が空の既存のファイルは、--mode の値で上書きしていません。回答を貼るときに mode を書いてください")
    log("このラウンドの記録数: {} プロンプト × {} サービス × {} 回 = {} 件".format(
        n_prompts, len(services), args.repeats, len(plan)))
    log(NEXT_STEPS)
    return 0


def main(argv=None):
    # type: (list) -> int
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except InputError as e:
        log("エラー: {}".format(e))
        return 2
    except Exception as e:  # 想定外のエラーは原因を追えるように経緯も出す
        log("想定外のエラー: {}: {}".format(type(e).__name__, e))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
