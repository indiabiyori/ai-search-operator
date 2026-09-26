# -*- coding: utf-8 -*-
"""
compare_runs.py - 観測の集計と、変更の前と後の比較（ai-search-operator）

normalize_observations.py が作った observations.csv を読み、次のどちらかを Markdown で出す。

  集計:  python3 compare_runs.py --period 2026-10-01,2026-10-08 [--workspace ai-search]
  比較:  python3 compare_runs.py --before 2026-10-01 --after 2026-10-29 [--targets P003,P004 --controls P001]
  実験:  python3 compare_runs.py --experiment ai-search/experiments/E001.md

入力:
  - <workspace>/observations.csv（必須。--observations で変えられる）
  - observations.csv と同じフォルダの observations.run.json と citations.csv（あれば使う）
  - <workspace>/entities.csv（あれば競合の表示名に使う）
  - 実験の記録（--experiment。先頭の欄に対象・対照のプロンプト、ラウンド、primary_group などを書く）

指標:
  - mention（言及率）: own_mentioned が 1 の回答 / valid_mention が 1 の回答
  - citation（引用率）: own_cited が 1 の回答 / valid_citation が 1 の回答
  - error（誤った説明の率）: accuracy が 誤りあり / accuracy が 誤りなし か 誤りあり で reviewed_by が human の回答。
    Claude の下書き（claude-draft）は人が確かめるまで分母に入れず、件数だけを別に示す
  - display（AI の回答の表示率）: status が 記録済み / status が 記録済み か AI の回答なし
  率は必ず「k/n（xx.x%）」の形で出す。集計は service・surface・login・mode・region・language の組ごとに分け、
  組をまたいで合算しない（--group-by で変えられる）。

前後の比較の判定（mention と citation だけ）:
  1. 組ごと・指標ごとに、両方の期間で有効な回答の数が同じで、--min-repeats（既定 3）件以上ある
     プロンプトだけを比べる。届かないプロンプトは理由を付けて一覧にし、比較から外す。
  2. プロンプトごとに差 d = 後の率 − 前の率 を求め、上がった・下がった・同じに分ける。
  3. 上がった件数と下がった件数の合計 m について、両側の正確な符号検定（二項分布、成功確率 1/2）で
     p 値を求める。m が 6 未満なら判定不能（6件すべてが同じ向きのときに初めて p < 0.05 になる）。
     p < α で上がった件数が多ければ改善シグナル、下がった件数が多ければ悪化シグナル、
     それ以外は「明確な変化を検出せず」（変化がないという意味ではない）。
     min_effect があり、差の平均の絶対値が届かなければ「明確な変化を検出せず」。
  4. 対照のプロンプトがあれば、対照で調整した差（対象の差の平均 − 対照の差の平均）を求める。
     シグナルでも、調整した差が逆向きかゼロ（または min_effect に届かない）なら判定不能にする。
  5. 実験の記録の primary_group と primary_metric の1つの判定だけを確認的な結論とし、
     ほかの組・指標はすべて探索的と明記する。実験の記録なしの比較はすべて探索的。
  率の差・差の平均・対照で調整した差は分数（fractions.Fraction）で厳密に計算し、min_effect との比較と
  符号の判定も厳密に行う（調整した差がちょうど 0 なら判定不能、差の平均がちょうど min_effect なら届いた）。
  表示では小数第3位で四捨五入し、丸めると同じに見える値は桁を増やして示す。

確認的な判定を出さない場合（事前に決めた条件を、結果を見てから変えられないようにする）:
  - 実験の記録に primary_group か primary_metric がない
  - 実験の記録に target_prompts がない（--targets で補っても出さない。対象は変更前に決めて書く）
  - コマンドラインで記録と違う値を指定した（--before、--after、--targets、--controls、--alpha、--min-effect）
  - 記録の空の欄（baseline_rounds、after_rounds、control_prompts など）をコマンドラインで補った。
    都合のよい変更後のラウンドや対照を、結果を見てから選べてしまうため
  - --min-repeats を既定（3）から変えた。実験の記録にはこの欄がないので、既定の値を事前の条件とみなす
  - --group-by を既定から変えた（primary_group と組が対応しない）
  control_prompts が空のまま（対照を置かない実験）は、事前の条件どおりなので確認的な判定を出し、
  「対照がないため、サービス側の変動と区別できない」と添える。

primary_group の書き方:
  service/surface/login/mode/region/language を / で区切る。mode には表示モデル名（例:
  GPT-5 Thinking/検索あり）を書くことがあり / を含みうるので、前から3つと後ろから2つを取り、
  残りを mode とみなす。

有効な回答がない組:
  new_round.py のひな形は mode が空なので、未記入のひな形だけの組ができる。有効な回答（と AI の回答
  なし）が1件もない組は、判定・集計の表から外して「有効な回答がない組」の節にまとめる。組の有無、
  観測した日数、モードの違いの警告も、有効な回答だけで確かめる。

observed_at の日付:
  normalize_observations.py と同じく、文中の 2026-10-29、2026/10/29、2026-10-1 のような形を日付として読む。

プロンプトを単位にする理由:
  同じプロンプトを繰り返し尋ねた回答どうしは独立ではない。回答を1件ずつ独立の試行として数えると、
  繰り返しの回数を増やすだけで見かけの確かさが上がってしまう。そこで、プロンプトごとの率の差を1つの
  観測として扱い、回答全体での信頼区間は出さない。

前後で件数をそろえる理由:
  符号検定は「変化がなければ、上がる確率と下がる確率は等しい」ことを前提にする。前と後で有効な回答の
  数が違うと、率の刻み（1/3 と 1/4 など）が変わり、変化がなくても上がりやすい・下がりやすい
  プロンプトができて、この前提が崩れる。

シグナルの意味:
  改善シグナル・悪化シグナルは、施策と整合的な変化が見えたという意味で、施策が原因だとは示さない。
  AI サービス側の変更でも同じ変化は起きうる。たとえば料金ページを直した週に、AI サービスが検索の
  仕組みを変えると、料金を尋ねないプロンプトでも自社の引用が増えることがある。対照のプロンプトは、
  その区別を助けるためにある。

出力:
  報告（Markdown）は -o のファイルか標準出力に、どちらも UTF-8 で書く。標準出力の文字コードが cp932
  （Windows でパイプやファイルにつないだとき）でも UTF-8 のバイト列を書くので、cp932 にない文字で落ちない。
  -o と --details-csv の出力先は、読み込みの前に確かめる（既存のフォルダ、親がファイル → 終了コード 2）。

終了コード: 0 は成功、2 は入力や引数の誤り（読めない CSV を含む）、1 は想定外のエラー。
要約と警告は標準エラー出力に出す。
"""
import argparse
import csv
import datetime
import json
import math
import os
import re
import sys
import traceback
from decimal import Decimal
from fractions import Fraction

sys.dont_write_bytecode = True  # スキルのフォルダに __pycache__ を残さない
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ai_search_common import (  # noqa: E402
    ArgumentParser,
    BRANDED_VALUES,
    ID_RE,
    STAGES,
    VERSION,
    InputError,
    log,
    normalize_text,
    parse_front_matter,
    parse_id_list,
    read_csv,
    read_text,
    split_list,
    write_csv,
)

JUDGED_METRICS = ("mention", "citation")
VERDICTS = ("改善シグナル", "悪化シグナル", "明確な変化を検出せず", "判定不能")
DEFAULT_GROUP_BY = ("service", "surface", "login", "mode", "region", "language")
MIN_CHANGED = 6
DEFAULT_ALPHA = 0.05
DEFAULT_MIN_REPEATS = 3

METRIC_LABELS = {
    "mention": "自社の言及",
    "citation": "自社の引用",
    "error": "誤った説明（人が確認済み）",
    "display": "AI の回答の表示",
}
REQUIRED_COLUMNS = (
    "round", "prompt_id", "observed_at", "service", "surface", "login", "mode", "region", "language",
    "status", "valid_mention", "valid_citation", "own_mentioned", "own_cited", "accuracy", "reviewed_by",
)
DETAIL_FIELDS = ["group", "metric", "set", "prompt_id", "before_k", "before_n", "after_k", "after_n", "diff",
                 "status"]

SIGNAL_NOTE = "改善シグナルは、施策と整合的な変化が見えたという意味で、原因を示すものではない。悪化シグナルも同じ。"
MULTIPLE_NOTE = ("複数の指標や組を同時に見ると、偶然の差をシグナルと判定しやすくなる。"
                 "確認的な判定は事前に決めた1組・1指標だけ")
NO_CHANGE_NOTE = "「明確な変化を検出せず」は、変化がないという意味ではない。"
RATE_NOTE = "率は「件数/分母（割合）」で示す。回答どうしは独立ではない（同じプロンプトの繰り返しを含む）ので信頼区間は出さない。"

# observed_at の日付。normalize_observations.py と同じく、区切りは - か /、月と日は1〜2桁で、文中から探す
_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
# entities_sha256 は observations.run.json の値（16進 64 桁）か、その先頭 12 桁以上
_SHA_RE = re.compile(r"^[0-9a-f]{12,64}$")
# プロンプトの ID の区切りに誤って使われやすい文字（日本語の読点、全角・半角のカンマなど）
_ID_SEPARATOR_HINT_CHARS = "、，､・；;"
_REASON_ONE_SIDE = "片方の期間にしかない"
_REASON_N_DIFFER = "前後で有効な回答の数が違う"
_REASON_NOT_OBSERVED = "この組で観測がない"


# ---------------------------------------------------------------------------
# 判定の中心（計算）
#
# 率の差・差の平均・対照で調整した差は fractions.Fraction で厳密に計算する。float で計算すると、
# 対象と対照がちょうど同じだけ動いた（調整した差が 0）のに 5.55e-17 になってシグナルが残ったり、
# 差の平均がちょうど min_effect なのに「届かない」と判定されたりする。float にするのは表示のときだけ。
# ---------------------------------------------------------------------------

def _exact(value):
    # type: (object) -> Fraction
    """数値を Fraction にする。float は表示どおりの10進数（repr）として読む（0.1 → 1/10）。"""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        return Fraction(repr(value))
    return Fraction(value)


def _sign_test_exact(improved, worsened):
    # type: (int, int) -> Fraction
    """両側の正確な符号検定の p 値（Fraction）。差が出たプロンプトがなければ 1。"""
    n = improved + worsened
    if n == 0:
        return Fraction(1)
    k = min(improved, worsened)
    # 整数どうしの分数にするので、m が大きくても float への変換であふれない
    tail = Fraction(sum(math.comb(n, i) for i in range(k + 1)), 2 ** n)
    return min(Fraction(1), 2 * tail)


def sign_test_p(improved, worsened):
    # type: (int, int) -> float
    """両側の正確な符号検定の p 値。差が出たプロンプトがなければ 1.0。"""
    return float(_sign_test_exact(improved, worsened))


def _median(values):
    # type: (list) -> object
    """中央値。空なら None。Fraction の一覧なら Fraction で返す。"""
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _is_one(value):
    # type: (object) -> bool
    return str(value or "").strip() == "1"


def metric_value(row, metric):
    # type: (dict, str) -> object
    """1件の回答の指標の値（1 か 0）。分母に入れない回答は None。"""
    if metric == "mention":
        if not _is_one(row.get("valid_mention")):
            return None
        return 1 if _is_one(row.get("own_mentioned")) else 0
    if metric == "citation":
        if not _is_one(row.get("valid_citation")):
            return None
        return 1 if _is_one(row.get("own_cited")) else 0
    if metric == "error":
        if not _is_one(row.get("valid_mention")) or row.get("reviewed_by") != "human":
            return None
        accuracy = row.get("accuracy")
        if accuracy == "誤りあり":
            return 1
        if accuracy == "誤りなし":
            return 0
        return None
    if metric == "display":
        status = row.get("status")
        if status == "記録済み":
            return 1
        if status == "AI の回答なし":
            return 0
        return None
    raise ValueError("未知の指標です: {}".format(metric))


def count_metric(rows, metric):
    # type: (list, str) -> tuple
    """(分子, 分母)。"""
    k = n = 0
    for row in rows:
        value = metric_value(row, metric)
        if value is not None:
            k += value
            n += 1
    return k, n


def per_prompt(rows, metric):
    # type: (list, str) -> dict
    """
    prompt_id → (k, n)。metric_value が None の行は数えない。
    行はあるが有効な回答が1件もないプロンプトは (0, 0) として残す（外した理由を正しく示すため）。
    """
    out = {}
    for row in rows:
        pid = row.get("prompt_id", "")
        if not pid:
            continue
        k, n = out.get(pid, (0, 0))
        value = metric_value(row, metric)
        if value is not None:
            k, n = k + value, n + 1
        out[pid] = (k, n)
    return out


def judge(before, after, alpha=DEFAULT_ALPHA, min_repeats=DEFAULT_MIN_REPEATS, min_effect=None):
    # type: (dict, dict, float, int, object) -> dict
    """
    プロンプトごとの (k, n) の前後から判定する。返り値のキー: verdict, reason, improved, worsened, tied,
    m, p（float）, mean_diff, median_diff, eligible, excluded（(prompt_id, 理由) の一覧）, diffs。
    diffs・mean_diff・median_diff は Fraction（厳密な値）。min_effect との比較と符号の判定も厳密に行う。
    """
    eligible, excluded, diffs = [], [], {}
    for pid in sorted(set(before) | set(after)):
        b, a = before.get(pid), after.get(pid)
        if b is None or a is None:
            excluded.append((pid, _REASON_ONE_SIDE))
        elif b[1] != a[1]:
            excluded.append((pid, "{}（前 {} 件、後 {} 件）".format(_REASON_N_DIFFER, b[1], a[1])))
        elif b[1] < min_repeats or b[1] == 0:
            excluded.append((pid, "有効な回答が {} 件未満（{} 件）".format(min_repeats, b[1])))
        else:
            eligible.append(pid)
            diffs[pid] = Fraction(a[0], a[1]) - Fraction(b[0], b[1])
    improved = sum(1 for d in diffs.values() if d > 0)
    worsened = sum(1 for d in diffs.values() if d < 0)
    tied = len(diffs) - improved - worsened
    m = improved + worsened
    p_exact = _sign_test_exact(improved, worsened)
    mean_diff = sum(diffs.values(), Fraction(0)) / len(diffs) if diffs else None
    median_diff = _median(list(diffs.values()))
    if m < MIN_CHANGED:
        verdict = "判定不能"
        reason = "差が出たプロンプトが {} 件（判定には {} 件以上が必要）".format(m, MIN_CHANGED)
    elif p_exact < _exact(alpha) and improved != worsened:
        verdict = "改善シグナル" if improved > worsened else "悪化シグナル"
        reason = ""
        if min_effect is not None and abs(mean_diff) < _exact(min_effect):
            verdict = "明確な変化を検出せず"
            reason = "差の平均 {} が最小効果 {} に届かない".format(*_fmt_against(mean_diff, min_effect))
    else:
        verdict = "明確な変化を検出せず"
        reason = "方向がそろっていない（p={}）。変化がないという意味ではない".format(_fmt_p(p_exact))
    return {"verdict": verdict, "reason": reason, "improved": improved, "worsened": worsened, "tied": tied,
            "m": m, "p": float(p_exact), "mean_diff": mean_diff, "median_diff": median_diff,
            "eligible": eligible, "excluded": excluded, "diffs": diffs}


def apply_control(target, control, min_effect=None):
    # type: (dict, object, object) -> dict
    """
    対照のプロンプトの判定で、対象の判定を補正する。返り値のキー: verdict, reason, control_mean_diff,
    adjusted_diff（Fraction）。調整した差の符号と min_effect との比較は厳密に行う（ちょうど 0 なら判定不能）。
    """
    out = {"verdict": target["verdict"], "reason": target["reason"],
           "control_mean_diff": None, "adjusted_diff": None}
    signal = target["verdict"] in ("改善シグナル", "悪化シグナル")
    if control is None or not control["eligible"] or control["mean_diff"] is None:
        if signal:
            out["reason"] = "対照がないため、サービス側の変動と区別できない"
        return out
    out["control_mean_diff"] = control["mean_diff"]
    adjusted = None
    if target["mean_diff"] is not None:
        adjusted = _exact(target["mean_diff"]) - _exact(control["mean_diff"])
    out["adjusted_diff"] = adjusted
    if signal:
        sign = 1 if target["verdict"] == "改善シグナル" else -1
        if adjusted is None or sign * adjusted <= 0:
            out["verdict"] = "判定不能"
            out["reason"] = "対照も同じ程度に動いた（対照で調整した差 {}）。サービス側の変動の可能性".format(
                _fmt_diff(adjusted if adjusted is not None else Fraction(0)))
        elif min_effect is not None and abs(adjusted) < _exact(min_effect):
            out["verdict"] = "判定不能"
            out["reason"] = "対照で調整した差 {} が最小効果 {} に届かない（対照も動いた。サービス側の変動の可能性）".format(
                *_fmt_against(adjusted, min_effect))
        else:
            out["reason"] = "対照で調整しても同じ向き（調整した差 {}）".format(_fmt_diff(adjusted))
    return out


# ---------------------------------------------------------------------------
# 入力の読み込み
# ---------------------------------------------------------------------------

def _parse_date(value):
    # type: (str) -> object
    """
    文中の最初の日付（2026-10-29、2026/10/29、2026-10-1 など）を date にする。なければ None。
    日付があるとみなす形は normalize_observations.py の observed_at の確認と同じ。
    """
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _check_ids(ids, where):
    # type: (list, str) -> None
    """プロンプトの ID が ID_RE に合うかを確かめる。合わなければ InputError（区切りの誤りのヒント付き）。"""
    bad = [pid for pid in ids if not ID_RE.match(pid)]
    if not bad:
        return
    hint = ""
    if any(ch in pid for pid in bad for ch in _ID_SEPARATOR_HINT_CHARS):
        hint = "。ID の区切りは半角のカンマ（,）か空白にしてください（「、」や全角の「，」では区切れません）"
    raise InputError("{}: プロンプトの ID は英数字で始まり、英数字・ハイフン・下線だけにしてください: {}{}".format(
        where, ", ".join(bad), hint))


def _parse_primary_group(raw, path):
    # type: (str, str) -> tuple
    """
    primary_group（service/surface/login/mode/region/language）を6要素のタプルにする。
    mode には表示モデル名（例: GPT-5 Thinking/検索あり）を書くことがあり、/ を含みうる。
    service・surface・login は決まった値、region・language は短い符号なので / を含まない。
    そこで、前から3つと後ろから2つを取り、残りをそのまま mode とする。
    """
    n = len(DEFAULT_GROUP_BY)
    if len(raw.split("/")) < n:
        raise InputError("{}: primary_group は {} を / で区切った {} つの値にしてください: {}".format(
            path, "/".join(DEFAULT_GROUP_BY), n, raw))
    head = raw.split("/", 3)
    tail = head[3].rsplit("/", 2)
    return tuple(part.strip() for part in head[:3] + tail)


def _parse_float(value, name, default):
    # type: (str, str, object) -> object
    value = (value or "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        raise InputError("{} は数値で書いてください: {}".format(name, value))


def _check_alpha(alpha, where):
    # type: (float, str) -> None
    if not 0.0 < alpha < 1.0:
        raise InputError("{}: alpha は 0 より大きく 1 より小さい値にしてください: {}".format(where, alpha))


def _check_min_effect(min_effect, where):
    # type: (object, str) -> None
    if min_effect is not None and not 0.0 <= min_effect <= 1.0:
        raise InputError("{}: min_effect は 0 以上 1 以下にしてください（率の差）: {}".format(where, min_effect))


def parse_experiment(path):
    # type: (str) -> dict
    """
    実験の記録（experiments/E001.md）の先頭の欄を読む。返り値のキー: id, targets, controls,
    baseline_rounds, after_rounds, primary_metric（なければ None）, primary_group（6要素のタプルか None）,
    alpha, min_effect（なければ None）, entities_sha256, changed_on など。
    """
    if not os.path.isfile(path):
        raise InputError("実験の記録がありません: {}".format(path))
    try:
        text = read_text(path)
    except OSError as exc:
        raise InputError("{}: 実験の記録を読めません（{}）".format(path, exc))
    meta, _body, errors = parse_front_matter(text)
    if errors:
        raise InputError("{}: 実験の記録の先頭の欄を読めません: {}".format(path, " / ".join(errors)))
    metric = meta.get("primary_metric", "")
    if metric and metric not in JUDGED_METRICS:
        raise InputError("{}: primary_metric は {} のどちらかにしてください: {}".format(
            path, " / ".join(JUDGED_METRICS), metric))
    group = None
    group_raw = meta.get("primary_group", "")
    if group_raw:
        group = _parse_primary_group(group_raw, path)
    targets = parse_id_list(meta.get("target_prompts", ""))
    controls = parse_id_list(meta.get("control_prompts", ""))
    _check_ids(targets, "{} の target_prompts".format(path))
    _check_ids(controls, "{} の control_prompts".format(path))
    alpha = _parse_float(meta.get("alpha", ""), "{} の alpha".format(path), DEFAULT_ALPHA)
    _check_alpha(alpha, path)
    min_effect = _parse_float(meta.get("min_effect", ""), "{} の min_effect".format(path), None)
    _check_min_effect(min_effect, path)
    changed_on = meta.get("changed_on", "")
    if changed_on and _parse_date(changed_on) is None:
        raise InputError("{}: changed_on は YYYY-MM-DD の形にしてください: {}".format(path, changed_on))
    return {
        "path": path,
        "id": meta.get("id", ""),
        "status": meta.get("status", ""),
        "hypothesis": meta.get("hypothesis", ""),
        "targets": targets,
        "controls": controls,
        "baseline_rounds": parse_id_list(meta.get("baseline_rounds", "")),
        "after_rounds": parse_id_list(meta.get("after_rounds", "")),
        "primary_metric": metric or None,
        "primary_group": group,
        "alpha": alpha,
        "min_effect": min_effect,
        "entities_sha256": meta.get("entities_sha256", "").strip().lower(),
        "changed_on": changed_on,
    }


def _read_csv_checked(path):
    # type: (str) -> tuple
    """
    read_csv で読み、読めないときは InputError（終了コード 2）にする。Python 3.9 の csv は、NUL 文字を
    含む行（壊れたファイルや、BOM のない UTF-16 のファイル）で csv.Error を出す。csv.Error は
    ValueError の下位クラスではないので、ここで個別に捕まえる。
    """
    try:
        return read_csv(path)
    except (csv.Error, OSError, ValueError) as exc:
        raise InputError("{}: CSV として読めません（{}）。ファイルが壊れていないか、UTF-8 か Shift_JIS（cp932）で"
                         "保存されているかを確かめてください".format(path, exc))


def load_observations(path):
    # type: (str) -> list
    """observations.csv を読む。ないとき・読めないとき・列が足りないときは InputError。"""
    if not os.path.isfile(path):
        raise InputError("observations.csv がありません: {}。先に normalize_observations.py を実行してください".format(
            path))
    fields, rows = _read_csv_checked(path)
    missing = [name for name in REQUIRED_COLUMNS if name not in fields]
    if missing:
        raise InputError("{}: 列が足りません: {}（normalize_observations.py で作り直してください）".format(
            path, ", ".join(missing)))
    return rows


def load_run_info(path, warnings):
    # type: (str, list) -> object
    """observations.run.json を読む。ない・読めないときは None（警告を足す）。"""
    if not os.path.isfile(path):
        warnings.append("observations.run.json がないため、判定のもとにした entities.csv の版を確かめられない")
        return None
    try:
        with open(path, encoding="utf-8-sig") as f:
            info = json.load(f)
    except (ValueError, OSError) as exc:
        warnings.append("observations.run.json を読めない（{}）".format(exc))
        return None
    return info if isinstance(info, dict) else None


def load_competitor_names(path, warnings=None):
    # type: (str, object) -> list
    """
    entities.csv の競合を (entity_id, name) の一覧で返す。なければ空。表示名に使うだけなので検証はせず、
    読めないときは警告を足して空を返す（集計そのものは続ける）。
    """
    if not os.path.isfile(path):
        return []
    try:
        _fields, rows = read_csv(path)
    except (csv.Error, OSError, ValueError) as exc:
        if warnings is not None:
            warnings.append("{} を読めないため、競合の表示名を出していない（{}）".format(path, exc))
        return []
    return [(row.get("entity_id", ""), row.get("name", "")) for row in rows
            if row.get("kind") == "competitor" and row.get("entity_id")]


def load_citations(path):
    # type: (str) -> object
    """citations.csv を読む。なければ None。読めなければ InputError。"""
    if not os.path.isfile(path):
        return None
    _fields, rows = _read_csv_checked(path)
    return rows


# ---------------------------------------------------------------------------
# 表示の補助
# ---------------------------------------------------------------------------

_MAX_PLACES = 6


def _round_half_up(value, places):
    # type: (object, int) -> Decimal
    """小数第 places 位で四捨五入した Decimal（厳密な値から丸める。-0 は 0 にする）。"""
    exact = _exact(value)
    rounded = int(abs(exact) * 10 ** places + Fraction(1, 2))  # 0 以上なので int は切り捨て
    if exact < 0:
        rounded = -rounded
    return Decimal(rounded).scaleb(-places)


def _places_for(value, places=3):
    # type: (object, int) -> int
    """0 でない値が places 桁で 0 に丸まるときは、0 と区別できるまで桁を増やす（最大 6 桁）。"""
    exact = _exact(value)
    while exact != 0 and places < _MAX_PLACES and _round_half_up(exact, places) == 0:
        places += 1
    return places


def format_rate(k, n):
    # type: (int, int) -> str
    """「k/n（xx.x%）」。割合は小数第1位で四捨五入する。"""
    if not n:
        return "{}/{}（分母なし）".format(k, n)
    pct = _round_half_up(Fraction(k * 100, n), 1)
    return "{}/{}（{:.1f}%）".format(k, n, pct)


def _fmt_diff(value, places=None):
    # type: (object, object) -> str
    """差の表示（符号付き、既定は小数第3位）。"""
    if value is None:
        return "-"
    places = _places_for(value) if places is None else places
    return "{:+.{p}f}".format(_round_half_up(value, places), p=places)


def _fmt_p(value):
    # type: (object) -> str
    return "{:.3f}".format(_round_half_up(value, 3))


def _fmt_plain(value, places=None):
    # type: (object, object) -> str
    """CSV 用・しきい値の表示用（符号を付けない。負の数は - で始まる数値として書く）。"""
    if value is None:
        return ""
    places = _places_for(value) if places is None else places
    return "{:.{p}f}".format(_round_half_up(value, places), p=places)


def _fmt_against(value, threshold):
    # type: (object, object) -> tuple
    """
    値としきい値（min_effect）を並べて示す (値, しきい値) の文字列。丸めると同じに見えるのに厳密には
    違うとき（0.09975 と 0.1 など）は、違いが見えるまで桁を増やす。
    """
    exact, limit = abs(_exact(value)), _exact(threshold)
    places = _places_for(value)
    while (places < _MAX_PLACES and exact != limit
           and _round_half_up(exact, places) == _round_half_up(limit, places)):
        places += 1
    return _fmt_diff(value, places), _fmt_plain(limit, places)


def _cell(text):
    # type: (object) -> str
    """Markdown の表のセル。| と改行を無害にする。"""
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def group_key(row, group_by):
    # type: (dict, tuple) -> tuple
    return tuple(row.get(name, "") for name in group_by)


def group_label(key):
    # type: (tuple) -> str
    return " / ".join(value if value else "（空）" for value in key)


def _group_rows(rows, group_by):
    # type: (list, tuple) -> dict
    groups = {}
    for row in rows:
        groups.setdefault(group_key(row, group_by), []).append(row)
    return groups


def _run_info_line(info):
    # type: (object) -> str
    if not info:
        return "判定のもとにした一覧: observations.run.json がないため確かめられない"
    sha = str(info.get("entities_sha256") or "")[:12] or "不明"
    return "判定のもとにした一覧: entities.csv の SHA-256 先頭12桁 {}（{} {}、{}）".format(
        sha, info.get("script") or "normalize_observations.py", info.get("version") or "版不明",
        info.get("generated_at") or "作成日時不明")


def _error_breakdown(rows):
    # type: (list) -> tuple
    """(誤りあり, 人が確かめた分母, 未確認, Claude の下書きのみ)。未確認は自社の言及がある有効な回答で数える。"""
    k, n = count_metric(rows, "error")
    unreviewed = draft = 0
    for row in rows:
        if not _is_one(row.get("valid_mention")) or metric_value(row, "error") is not None:
            continue
        accuracy = row.get("accuracy", "")
        if row.get("reviewed_by") == "claude-draft" and accuracy in ("誤りなし", "誤りあり"):
            draft += 1
        elif _is_one(row.get("own_mentioned")) and accuracy != "該当なし":
            unreviewed += 1
    return k, n, unreviewed, draft


def _error_text(rows):
    # type: (list) -> str
    k, n, unreviewed, draft = _error_breakdown(rows)
    return "{}、未確認 {} 件、Claude の下書きのみ {} 件".format(format_rate(k, n), unreviewed, draft)


def _row_date(row):
    # type: (dict) -> object
    return _parse_date(row.get("observed_at", ""))


def _dates(rows):
    # type: (list) -> set
    """有効な回答の観測日（observed_at に日付があるものだけ）。"""
    return set(d for d in (_row_date(r) for r in rows if _is_one(r.get("valid_mention"))) if d is not None)


def _undated_count(rows):
    # type: (list) -> int
    return sum(1 for r in rows if _is_one(r.get("valid_mention")) and _row_date(r) is None)


def _check_rounds(rows, rounds, label):
    # type: (list, list, str) -> None
    present = set(r.get("round", "") for r in rows)
    missing = [name for name in rounds if name not in present]
    if missing:
        hint = ""
        if any(ch in name for name in missing for ch in _ID_SEPARATOR_HINT_CHARS):
            hint = "。ラウンドの区切りは半角のカンマ（,）か空白にしてください"
        raise InputError("{}のラウンドが observations.csv にありません: {}（normalize_observations.py の --rounds で"
                         "除いていないか確かめてください）{}".format(label, ", ".join(missing), hint))


def _is_valid(row):
    # type: (dict) -> bool
    """言及率の分母に入る有効な回答か（未記入のひな形、エラーなどは入らない）。"""
    return _is_one(row.get("valid_mention"))


def _is_observed(row):
    # type: (dict) -> bool
    """組の表に出す回答か。有効な回答と、AI の回答が表示されなかった回答（表示率に使う）。"""
    return _is_valid(row) or row.get("status") == "AI の回答なし"


def _split_empty_groups(groups):
    # type: (dict) -> tuple
    """
    組を (表に出す組, 有効な回答がない組) に分ける。new_round.py のひな形は mode が空なので、未記入の
    ひな形だけの組（mode が空の組）ができる。この組は観測を表さないので、判定や集計の表に出さない。
    """
    kept, empty = {}, {}
    for key, g_rows in groups.items():
        (kept if any(_is_observed(r) for r in g_rows) else empty)[key] = g_rows
    return kept, empty


def _parse_group_by(value):
    # type: (object) -> tuple
    if value is None:
        return DEFAULT_GROUP_BY
    names = parse_id_list(value)
    if not names:
        raise InputError("--group-by に列の名前を書いてください（使える列: {}）".format(", ".join(DEFAULT_GROUP_BY)))
    bad = [name for name in names if name not in DEFAULT_GROUP_BY]
    if bad:
        raise InputError("--group-by に使えない列があります: {}（使える列: {}）".format(
            ", ".join(bad), ", ".join(DEFAULT_GROUP_BY)))
    return tuple(names)


def _check_output_path(path, flag):
    # type: (object, str) -> None
    """
    出力先を書き始める前に確かめる。既存のフォルダを指したとき、親のフォルダの途中にファイルが
    あるときは InputError（終了コード 2）。読み込みや計算の前に呼び、途中まで書いた出力を残さない。
    """
    if not path:
        return
    full = os.path.abspath(path)
    if os.path.isdir(full):
        raise InputError("{} にフォルダが指定されています。ファイルの名前まで書いてください: {}".format(flag, path))
    parent = os.path.dirname(full)
    while not os.path.exists(parent):
        upper = os.path.dirname(parent)
        if upper == parent:
            break
        parent = upper
    if not os.path.isdir(parent):
        raise InputError("{} の出力先のフォルダを作れません（{} はファイルです）: {}".format(flag, parent, path))


def _write_file(path, flag, writer):
    # type: (str, str, object) -> None
    """フォルダを作ってから writer(path) で書く。書けなければ InputError。"""
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            os.makedirs(folder)
        writer(path)
    except OSError as exc:
        raise InputError("{} の出力先に書けません: {}（{}）".format(flag, path, exc))


def _write_stdout(text):
    # type: (str) -> None
    """
    標準出力に UTF-8 で書く。Windows で標準出力をパイプやファイルにつなぐと、Python の標準出力の文字コードは
    cp932 になり、cp932 にない文字（仮説の — など）で UnicodeEncodeError になる。そこで、文字コードの層を
    通さずに UTF-8 のバイト列を書く（-o で書くファイルと同じ UTF-8 になる）。
    """
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # 標準出力が差し替えられている（テストなど）
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _write_output(text, path):
    # type: (str, object) -> None
    """報告を -o のファイル（UTF-8）か標準出力に書く。"""
    if path:
        def writer(target):
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        _write_file(path, "-o", writer)
        log("報告を書きました: {}".format(path))
    else:
        _write_stdout(text)


def _warnings_section(warnings):
    # type: (list) -> list
    lines = ["", "## 警告", ""]
    if warnings:
        lines += ["- " + _cell(w) for w in warnings]
    else:
        lines.append("なし")
    return lines


def _dedupe(items):
    # type: (list) -> list
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# 集計（--period）
# ---------------------------------------------------------------------------

def _exclusion_text(rows):
    # type: (list) -> str
    counts = {}
    for row in rows:
        if _is_one(row.get("valid_mention")) and _is_one(row.get("valid_citation")):
            continue
        reasons = [part.strip() for part in (row.get("exclusion_reason") or "").split(";") if part.strip()]
        for reason in reasons or ["理由の記載なし"]:
            counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return "なし"
    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return "、".join("{} {} 件".format(reason, n) for reason, n in items)


def _source_order_text(rows):
    # type: (list) -> str
    first = middle = later = body_only = 0
    for row in rows:
        if metric_value(row, "citation") != 1:
            continue
        order = (row.get("own_first_source_order") or "").strip()
        if not order.isdigit():
            body_only += 1
        elif int(order) == 1:
            first += 1
        elif int(order) <= 3:
            middle += 1
        else:
            later += 1
    return "1番目 {} / 2〜3番目 {} / 4番目以降 {} / 本文のリンクだけ {}".format(first, middle, later, body_only)


def _competitor_lines(rows, competitors):
    # type: (list, list) -> list
    ids = [cid for cid, _name in competitors]
    names = dict(competitors)
    extra = set()
    for row in rows:
        for column in ("competitors_mentioned", "competitors_cited"):
            extra.update(split_list(row.get(column, "")))
    ids += sorted(cid for cid in extra if cid not in names)
    if not ids:
        return ["競合: entities.csv に競合がなく、回答にも競合の言及・引用がない"]
    mention_rows = [r for r in rows if metric_value(r, "mention") is not None]
    citation_rows = [r for r in rows if metric_value(r, "citation") is not None]
    lines = ["| 競合 | 言及 | 引用 |", "|---|---|---|"]
    for cid in ids:
        label = "{}（{}）".format(cid, names[cid]) if names.get(cid) else cid
        k_m = sum(1 for r in mention_rows if cid in split_list(r.get("competitors_mentioned", "")))
        k_c = sum(1 for r in citation_rows if cid in split_list(r.get("competitors_cited", "")))
        lines.append("| {} | {} | {} |".format(_cell(label), format_rate(k_m, len(mention_rows)),
                                                format_rate(k_c, len(citation_rows))))
    return lines


def _ordered_values(values, preferred):
    # type: (set, tuple) -> list
    out = [v for v in preferred if v in values]
    out += sorted(v for v in values if v not in preferred and v)
    if "" in values:
        out.append("")
    return out


def _breakdown_lines(rows):
    # type: (list) -> list
    lines = ["| 区分 | 言及 | 引用 |", "|---|---|---|"]
    for column, preferred, prefix in (("stage", STAGES, "段階: "), ("branded", BRANDED_VALUES, "")):
        values = set(r.get(column, "") for r in rows)
        for value in _ordered_values(values, preferred):
            subset = [r for r in rows if r.get(column, "") == value]
            if column == "stage":
                label = prefix + (value or "（未設定）")
            else:
                label = value or "指名・非指名: （未設定）"
            lines.append("| {} | {} | {} |".format(
                _cell(label), format_rate(*count_metric(subset, "mention")),
                format_rate(*count_metric(subset, "citation"))))
    return lines


def _host_lines(rows, citations):
    # type: (list, object) -> list
    if citations is None:
        return ["entities.csv にない出典のホスト: citations.csv がないため出していない"]
    valid_files = set(r.get("answer_file", "") for r in rows if metric_value(r, "citation") is not None)
    n = len(valid_files)
    hosts = {}
    for c in citations:
        if c.get("entity_kind") != "other" or c.get("answer_file", "") not in valid_files:
            continue
        host = c.get("host", "")
        if host:
            hosts.setdefault(host, set()).add(c.get("answer_file", ""))
    lines = ["entities.csv にない出典のホスト（上位10。競合の追加候補）:", ""]
    if not hosts:
        return lines + ["なし"]
    ranked = sorted(hosts.items(), key=lambda item: (-len(item[1]), item[0]))[:10]
    lines += ["| ホスト | 引用した回答 |", "|---|---|"]
    lines += ["| {} | {} |".format(_cell(host), format_rate(len(files), n)) for host, files in ranked]
    return lines


def render_period(rows, rounds, group_by, run_info, competitors, citations, warnings):
    # type: (list, list, tuple, object, list, object, list) -> str
    """--period の Markdown。"""
    groups, empty_groups = _split_empty_groups(_group_rows(rows, group_by))
    valid = sum(1 for r in rows if _is_one(r.get("valid_mention")))
    prompts = set(r.get("prompt_id") for r in rows if r.get("prompt_id"))
    lines = [
        "# AI 検索の観測の集計",
        "",
        "- 対象のラウンド: " + ", ".join(rounds),
        "- 回答: {} 件（有効 {} 件） / プロンプト: {} 件 / 組: {}".format(len(rows), valid, len(prompts), len(groups)),
        "- " + RATE_NOTE + "組をまたいで合算しない。",
        "- 「出典が不明」の回答は、引用率の分母からだけ外す。",
        "- 誤った説明の「未確認」は、自社の言及がある有効な回答のうち、人も Claude もまだ正誤を書いていないもの。",
        "- 組の分け方: " + " / ".join(group_by),
        "- " + _run_info_line(run_info),
    ]
    if empty_groups:
        lines.append("- 有効な回答がない組: {}（組の数に入れず、「有効な回答がない組」の節にまとめた）".format(
            len(empty_groups)))
    for key in sorted(groups):
        g_rows = groups[key]
        g_valid = sum(1 for r in g_rows if _is_one(r.get("valid_mention")))
        g_prompts = set(r.get("prompt_id") for r in g_rows if r.get("prompt_id"))
        lines += [
            "",
            "## " + group_label(key),
            "",
            "- 回答: {} 件（有効 {} 件） / プロンプト: {} 件".format(len(g_rows), g_valid, len(g_prompts)),
            "",
            "| 指標 | 件数 |",
            "|---|---|",
            "| {} | {} |".format(METRIC_LABELS["mention"], format_rate(*count_metric(g_rows, "mention"))),
            "| {} | {} |".format(METRIC_LABELS["citation"], format_rate(*count_metric(g_rows, "citation"))),
            "| {} | {} |".format(METRIC_LABELS["error"], _error_text(g_rows)),
            "| {} | {} |".format(METRIC_LABELS["display"], format_rate(*count_metric(g_rows, "display"))),
            "",
            "分母に入れなかった回答: " + _exclusion_text(g_rows),
            "",
            "出典の並び順（自社が引用された回答のうち。並び順は重要度を表すとは限らない）: " + _source_order_text(g_rows),
            "",
        ]
        lines += _competitor_lines(g_rows, competitors)
        lines += ["", "段階別、指名・非指名別:", ""]
        lines += _breakdown_lines(g_rows)
        lines.append("")
        lines += _host_lines(g_rows, citations)
    lines += _empty_groups_section(empty_groups)
    lines += _warnings_section(warnings)
    return "\n".join(lines) + "\n"


def _empty_groups_section(empty_groups, counts=None):
    # type: (dict, object) -> list
    """
    有効な回答がない組の節（なければ空）。未記入のひな形は mode などが空のため、本来の組とは別の組に
    なる。記入すれば本来の組に入る。counts（組 → 件数の文）を渡すと、回答数の代わりにそれを示す。
    """
    if not empty_groups:
        return []
    lines = ["", "## 有効な回答がない組", "",
             "未記入のひな形・エラー・回答拒否などの回答だけの組。判定と集計の表には入れていない。"
             "new_round.py のひな形は mode が空なので、記入すると本来の組に移る。", ""]
    for key in sorted(empty_groups):
        g_rows = empty_groups[key]
        count = (counts or {}).get(key) or "回答 {} 件".format(len(g_rows))
        lines.append("- {}: {}（{}）".format(_cell(group_label(key)), count, _cell(_exclusion_text(g_rows))))
    return lines


def period_warnings(rows, group_by):
    # type: (list, tuple) -> list
    warnings = []
    for key, g_rows in sorted(_group_rows(rows, group_by).items()):
        dates = _dates(g_rows)
        if len(dates) == 1:
            warnings.append("{}: 期間の回答がすべて同じ日（{}）のもの。日による変動を見分けられない".format(
                group_label(key), next(iter(dates)).isoformat()))
        undated = _undated_count(g_rows)
        if undated:
            warnings.append("{}: observed_at に日付がない有効な回答が {} 件（観測した日の確認から外した）".format(
                group_label(key), undated))
    return warnings


# ---------------------------------------------------------------------------
# 比較（--before / --after / --experiment）
# ---------------------------------------------------------------------------

def _judge_set(b_rows, a_rows, ids, metric, alpha, min_repeats, min_effect):
    # type: (list, list, list, str, float, int, object) -> tuple
    """プロンプトの集合 ids について判定する。(判定, 前の (k, n) の辞書, 後の辞書)。"""
    id_set = set(ids)
    before = per_prompt([r for r in b_rows if r.get("prompt_id") in id_set], metric)
    after = per_prompt([r for r in a_rows if r.get("prompt_id") in id_set], metric)
    result = judge(before, after, alpha=alpha, min_repeats=min_repeats, min_effect=min_effect)
    missing = [(pid, _REASON_NOT_OBSERVED) for pid in ids if pid not in before and pid not in after]
    if missing:
        result["excluded"] = sorted(result["excluded"] + missing)
    return result, before, after


def compare_groups(before_rows, after_rows, targets, controls, metrics, group_by, alpha, min_repeats,
                   min_effect):
    # type: (list, list, list, list, list, tuple, float, int, object) -> list
    """組ごと・指標ごとの判定の一覧。有効な回答がない組（未記入のひな形だけの組など）は判定しない。"""
    b_groups = _group_rows(before_rows, group_by)
    a_groups = _group_rows(after_rows, group_by)
    empty = empty_compare_groups(before_rows, after_rows, group_by)[0]
    results = []
    for key in sorted(set(b_groups) | set(a_groups)):
        if key in empty:
            continue
        b_rows = b_groups.get(key, [])
        a_rows = a_groups.get(key, [])
        observed = set(r.get("prompt_id") for r in b_rows + a_rows if r.get("prompt_id"))
        target_ids = list(targets) if targets else sorted(observed - set(controls))
        target_set = set(target_ids)
        b_target = [r for r in b_rows if r.get("prompt_id") in target_set]
        a_target = [r for r in a_rows if r.get("prompt_id") in target_set]
        for metric in metrics:
            target, t_before, t_after = _judge_set(b_rows, a_rows, target_ids, metric, alpha, min_repeats,
                                                   min_effect)
            control = c_before = c_after = None
            if controls:
                control, c_before, c_after = _judge_set(b_rows, a_rows, controls, metric, alpha, min_repeats,
                                                        min_effect)
            final = apply_control(target, control, min_effect)
            results.append({
                "key": key, "metric": metric, "target": target, "control": control, "final": final,
                "sets": {"target": (target, t_before, t_after), "control": (control, c_before, c_after)},
                "before_count": count_metric(b_target, metric), "after_count": count_metric(a_target, metric),
            })
        results.append({
            "key": key, "metric": None,
            "error": (_error_text(b_target), _error_text(a_target)),
            "display": (format_rate(*count_metric(b_target, "display")),
                        format_rate(*count_metric(a_target, "display"))),
        })
    return results


def empty_compare_groups(before_rows, after_rows, group_by):
    # type: (list, list, tuple) -> tuple
    """比較で、どちらの期間にも有効な回答がない組。(組 → 回答の一覧, 組 → 「前 n 件、後 m 件」)。"""
    b_groups = _group_rows(before_rows, group_by)
    a_groups = _group_rows(after_rows, group_by)
    combined = {}
    for key in set(b_groups) | set(a_groups):
        combined[key] = b_groups.get(key, []) + a_groups.get(key, [])
    empty = _split_empty_groups(combined)[1]
    counts = dict((key, "前 {} 件、後 {} 件".format(len(b_groups.get(key, [])), len(a_groups.get(key, []))))
                  for key in empty)
    return empty, counts


def detail_rows(results):
    # type: (list) -> list
    """--details-csv の行。"""
    out = []
    for res in results:
        if res["metric"] is None:
            continue
        for set_name in ("target", "control"):
            result, before, after = res["sets"][set_name]
            if result is None:
                continue
            reasons = dict(result["excluded"])
            pids = sorted(set(before) | set(after) | set(reasons))
            for pid in pids:
                b = before.get(pid)
                a = after.get(pid)
                out.append({
                    "group": "/".join(res["key"]),
                    "metric": res["metric"],
                    "set": set_name,
                    "prompt_id": pid,
                    "before_k": "" if b is None else b[0],
                    "before_n": "" if b is None else b[1],
                    "after_k": "" if a is None else a[0],
                    "after_n": "" if a is None else a[1],
                    "diff": _fmt_plain(result["diffs"].get(pid)),
                    "status": "比較した" if pid in result["diffs"] else reasons.get(pid, ""),
                })
    return out


def _same_group(key, primary):
    # type: (tuple, tuple) -> bool
    if len(key) != len(primary):
        return False
    return all(normalize_text(a).strip() == normalize_text(b).strip() for a, b in zip(key, primary))


def compare_warnings(before_rows, after_rows, results, group_by, experiment, run_info, before_rounds,
                     after_rounds):
    # type: (list, list, list, tuple, object, object, list, list) -> list
    """
    仕様 7.4 の「報告に必ず添える警告」。組の有無・観測した日・モードの違いは、有効な回答（valid_mention が 1）
    だけで確かめる。未記入のひな形（mode が空）や記録の失敗は観測を表さないので、誤った警告のもとになる。
    """
    warnings = []
    before_valid = [r for r in before_rows if _is_valid(r)]
    after_valid = [r for r in after_rows if _is_valid(r)]
    b_groups = _group_rows(before_valid, group_by)
    a_groups = _group_rows(after_valid, group_by)
    for key in sorted(set(b_groups) | set(a_groups)):
        label = group_label(key)
        b_rows = b_groups.get(key, [])
        a_rows = a_groups.get(key, [])
        if not b_rows or not a_rows:
            warnings.append("{}: この組は有効な回答が{}の期間にしかない（比較できない）".format(
                label, "前" if b_rows else "後"))
            continue
        b_dates, a_dates = _dates(b_rows), _dates(a_rows)
        if b_dates and a_dates and len(b_dates) != len(a_dates):
            warnings.append("{}: 前と後で観測した日数が違う（前 {} 日、後 {} 日）".format(
                label, len(b_dates), len(a_dates)))
        for name, dates in (("前", b_dates), ("後", a_dates)):
            if len(dates) == 1:
                warnings.append("{}: {}の期間の回答がすべて同じ日（{}）のもの。日による変動を見分けられない".format(
                    label, name, next(iter(dates)).isoformat()))
        undated = _undated_count(b_rows) + _undated_count(a_rows)
        if undated:
            warnings.append("{}: observed_at に日付がない有効な回答が {} 件（観測した日数の確認から外した）".format(
                label, undated))
    # モードの違い（mode 以外の組の値が同じ有効な回答どうしで比べる）
    others = tuple(name for name in group_by if name != "mode")
    b_modes, a_modes = {}, {}
    for rows, modes in ((before_valid, b_modes), (after_valid, a_modes)):
        for row in rows:
            modes.setdefault(group_key(row, others), set()).add(row.get("mode", ""))
    for key in sorted(set(b_modes) & set(a_modes)):
        if b_modes[key] != a_modes[key]:
            warnings.append("{}: 前と後でモードの種類が違う（前: {}、後: {}）".format(
                group_label(key) if key else "全体",
                ", ".join(sorted(m or "（空）" for m in b_modes[key])),
                ", ".join(sorted(m or "（空）" for m in a_modes[key]))))
    # 外したプロンプト
    for res in results:
        if res["metric"] is None:
            continue
        for set_name, set_label in (("target", "対象"), ("control", "対照")):
            result = res["sets"][set_name][0]
            if result is None:
                continue
            one_side = sum(1 for _pid, reason in result["excluded"] if reason == _REASON_ONE_SIDE)
            differ = sum(1 for _pid, reason in result["excluded"] if reason.startswith(_REASON_N_DIFFER))
            if one_side or differ:
                warnings.append("{} / {} / {}: 片方の期間にしかないプロンプト {} 件、前後で有効な回答の数が違う"
                                "プロンプト {} 件（「外したプロンプト」を参照）".format(
                                    group_label(res["key"]), METRIC_LABELS[res["metric"]], set_label,
                                    one_side, differ))
    if experiment:
        warnings += _experiment_warnings(before_rows, after_rows, experiment, run_info, before_rounds,
                                         after_rounds)
    return warnings


def _experiment_warnings(before_rows, after_rows, experiment, run_info, before_rounds, after_rounds):
    # type: (list, list, dict, object, list, list) -> list
    warnings = []
    changed = _parse_date(experiment.get("changed_on", ""))
    if changed is not None:
        for rows, rounds, name in ((before_rows, before_rounds, "変更前"), (after_rows, after_rounds, "変更後")):
            for round_name in rounds:
                # 未記入のひな形などの無効な回答は、観測した日を表さないので見ない
                dates = [_row_date(r) or _parse_date(round_name) for r in rows
                         if r.get("round") == round_name and _is_one(r.get("valid_mention"))]
                dates = [d for d in dates if d is not None]
                wrong = sum(1 for d in dates if (d > changed if name == "変更前" else d < changed))
                same = sum(1 for d in dates if d == changed)
                if wrong:
                    warnings.append("{}のラウンド {} に、changed_on（{}）より{}の回答が {} 件ある".format(
                        name, round_name, changed.isoformat(), "後" if name == "変更前" else "前", wrong))
                if same:
                    warnings.append("{}のラウンド {} に、changed_on（{}）と同じ日の回答が {} 件ある"
                                    "（反映の前か後か区別できない）".format(name, round_name, changed.isoformat(), same))
    else:
        warnings.append("実験の記録に changed_on がないため、ラウンドが変更の前か後かを確かめられない")
    recorded = experiment.get("entities_sha256", "")
    current = str((run_info or {}).get("entities_sha256") or "").strip().lower()
    if not recorded:
        warnings.append("実験の記録に entities_sha256 がないため、表記ゆれの一覧（entities.csv）を変えたかを確かめられない")
    elif not _SHA_RE.match(recorded):
        # 1 桁や 4 桁の値でも前方一致してしまうので、短い値・16進でない値は照合しない
        warnings.append("実験の記録の entities_sha256 の形式が不正（{}）。observations.run.json の entities_sha256"
                        "（16進 64 桁）をそのまま写す（短くするなら先頭 12 桁以上）。表記ゆれの一覧を変えたかを"
                        "確かめられない".format(recorded[:70]))
    elif not current:
        warnings.append("observations.run.json に entities_sha256 がないため、実験の記録の entities_sha256 と比べられない")
    elif not current.startswith(recorded):
        warnings.append("実験の記録の entities_sha256（{}）と observations.run.json の値（{}）が違う。"
                        "表記ゆれの一覧を変えたので、過去の判定も変わっている".format(recorded[:12], current[:12]))
    return warnings


def _results_table(group_results, confirm):
    # type: (list, object) -> list
    lines = [
        "| 指標 | 前 | 後 | 比較した | 外した | 上がった | 下がった | 同じ | 差の平均 | 差の中央値 | m | p "
        "| 対照の差の平均 | 調整した差 | 判定 | 理由 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for res in group_results:
        target, final = res["target"], res["final"]
        tag = "（確認的）" if res is confirm else "（探索的）"
        lines.append("| {} |".format(" | ".join(_cell(v) for v in (
            METRIC_LABELS[res["metric"]], format_rate(*res["before_count"]), format_rate(*res["after_count"]),
            len(target["eligible"]), len(target["excluded"]), target["improved"], target["worsened"],
            target["tied"], _fmt_diff(target["mean_diff"]), _fmt_diff(target["median_diff"]), target["m"],
            _fmt_p(target["p"]), _fmt_diff(final["control_mean_diff"]), _fmt_diff(final["adjusted_diff"]),
            final["verdict"] + tag, final["reason"] or "-"))))
    return lines


def _excluded_lines(results):
    # type: (list) -> list
    lines = []
    for res in results:
        if res["metric"] is None:
            continue
        for set_name, set_label in (("target", "対象"), ("control", "対照")):
            result = res["sets"][set_name][0]
            if result is None or not result["excluded"]:
                continue
            by_reason = {}
            for pid, reason in result["excluded"]:
                by_reason.setdefault(reason, []).append(pid)
            parts = ["{}: {}".format(reason, ", ".join(pids)) for reason, pids in sorted(by_reason.items())]
            lines.append("- {} / {} / {}: {}".format(group_label(res["key"]), METRIC_LABELS[res["metric"]],
                                                     set_label, _cell("。".join(parts))))
    return lines or ["なし"]


def render_compare(results, ctx, warnings):
    # type: (list, dict, list) -> str
    """比較の Markdown。"""
    experiment = ctx["experiment"]
    confirm = ctx["confirm"]
    lines = ["# AI 検索の前後比較", ""]
    lines.append("- 変更前のラウンド: " + ", ".join(ctx["before_rounds"]))
    lines.append("- 変更後のラウンド: " + ", ".join(ctx["after_rounds"]))
    if experiment:
        exp_line = "- 実験の記録: {}（{}）".format(experiment.get("id") or "ID なし", experiment["path"])
        if experiment.get("hypothesis"):
            exp_line += "。仮説: " + experiment["hypothesis"]
        lines.append(exp_line)
        if experiment.get("changed_on"):
            lines.append("- 本番に反映した日: " + experiment["changed_on"])
    if ctx["targets"]:
        lines.append("- 対象のプロンプト: {}（{} 件）".format(", ".join(ctx["targets"]), len(ctx["targets"])))
    else:
        lines.append("- 対象のプロンプト: 指定なし（各組で観測した、対照以外のすべてのプロンプト）")
    if ctx["controls"]:
        lines.append("- 対照のプロンプト: {}（{} 件）".format(", ".join(ctx["controls"]), len(ctx["controls"])))
    else:
        lines.append("- 対照のプロンプト: なし")
    lines.append("- 条件: α {}、最小の繰り返し {} 件、最小効果 {}、差が出たプロンプトが {} 件未満なら判定不能".format(
        ctx["alpha"], ctx["min_repeats"],
        "なし" if ctx["min_effect"] is None else _fmt_plain(ctx["min_effect"]), MIN_CHANGED))
    lines.append("- 組の分け方: " + " / ".join(ctx["group_by"]))
    lines.append("- " + _run_info_line(ctx["run_info"]))
    for note in ctx["notes"]:
        lines.append("- " + note)

    judged = [r for r in results if r["metric"] is not None]
    lines += ["", "## 結論", ""]
    if ctx["confirm_label"]:
        if confirm is not None:
            final = confirm["final"]
            text = "- 確認的な判定（{}）: {}".format(ctx["confirm_label"], final["verdict"])
            if final["reason"]:
                text += "。" + final["reason"]
            lines.append(text)
        else:
            lines.append("- 確認的な判定（{}）: 判定不能。この組の有効な回答が、指定したラウンドにない".format(
                ctx["confirm_label"]))
        lines.append("- そのほかの組・指標の結果はすべて探索的。")
    elif experiment:
        lines.append("- 確認的な判定: 出さない（{}）。すべて探索的な比較として扱う。".format(ctx["no_confirm_reason"]))
    else:
        lines.append("- すべて探索的な比較（実験の記録なし）。確認的な判定は、変更前に決めた実験の記録"
                     "（--experiment の primary_group と primary_metric）の1つだけで出す。")
    counts = [(v, sum(1 for r in judged if r["final"]["verdict"] == v and r is not confirm)) for v in VERDICTS]
    lines.append("- 探索的な判定の内訳（組×指標）: " + "、".join("{} {}".format(v, n) for v, n in counts))
    lines.append("- " + SIGNAL_NOTE)

    lines += ["", "## 組ごとの判定"]
    by_group = {}
    for res in results:
        by_group.setdefault(res["key"], []).append(res)
    for key in sorted(by_group):
        group_results = by_group[key]
        lines += ["", "### " + group_label(key), ""]
        judged_here = [r for r in group_results if r["metric"] is not None]
        lines += _results_table(judged_here, confirm)
        other = [r for r in group_results if r["metric"] is None][0]
        lines += [
            "",
            "| 判定しない指標（件数だけ） | 前 | 後 |",
            "|---|---|---|",
            "| {} | {} | {} |".format(METRIC_LABELS["error"], other["error"][0], other["error"][1]),
            "| {} | {} | {} |".format(METRIC_LABELS["display"], other["display"][0], other["display"][1]),
        ]
    lines += ["", "前・後の k/n は、対象のプロンプトの有効な回答すべての件数。判定は「比較した」プロンプトだけで行う。"
              "差はプロンプトごとの率の差（後 − 前）。p は、上がったプロンプトと下がったプロンプトの数に対する"
              "両側の正確な符号検定の値。"]

    lines += ["", "## 外したプロンプト", ""]
    lines += _excluded_lines(results)
    lines += _empty_groups_section(ctx["empty_groups"], ctx["empty_counts"])
    lines += _warnings_section(warnings)
    lines += [
        "",
        "## 注記",
        "",
        "- " + MULTIPLE_NOTE + "。",
        "- " + NO_CHANGE_NOTE,
        "- " + SIGNAL_NOTE,
        "- 誤った説明の率と AI の回答の表示率は、前後で分母がそろわないので判定しない。",
    ]
    return "\n".join(lines) + "\n"


def _merge_list(cli, recorded, flag, field, notes, overrides):
    # type: (object, list, str, str, list, list) -> list
    """
    コマンドラインの一覧と実験の記録の一覧を合わせる。コマンドラインを優先する。
    記録と違う値を指定したときだけでなく、記録が空の欄をコマンドラインで埋めたときも、事前に決めた
    条件ではないので overrides に入れる（確認的な判定を出さない）。
    """
    if not cli:
        return list(recorded)
    if not recorded:
        notes.append("実験の記録の {} が空のため、{} の値を使った。事前に決めた条件ではないので、"
                     "確認的な判定は出さない".format(field, flag))
        overrides.append(flag)
    elif set(cli) != set(recorded):
        notes.append("コマンドラインの指定を実験の記録より優先した: {}（記録の {}: {}）".format(
            flag, field, ", ".join(recorded)))
        overrides.append(flag)
    return list(cli)


def _merge_value(cli, recorded, flag, field, notes, overrides):
    # type: (object, object, str, str, list, list) -> object
    if cli is None or cli == recorded:
        return recorded
    notes.append("コマンドラインの指定を実験の記録より優先した: {} {}（記録の {}: {}）".format(
        flag, cli, field, "空" if recorded is None else recorded))
    overrides.append(flag)
    return cli


def run_compare(args, rows, run_info, group_by, warnings):
    # type: (argparse.Namespace, list, object, tuple, list) -> tuple
    experiment = parse_experiment(args.experiment) if args.experiment else None
    before = parse_id_list(args.before) if args.before is not None else []
    after = parse_id_list(args.after) if args.after is not None else []
    targets = parse_id_list(args.targets) if args.targets is not None else []
    controls = parse_id_list(args.controls) if args.controls is not None else []
    _check_ids(targets, "--targets")
    _check_ids(controls, "--controls")
    alpha, min_effect = args.alpha, args.min_effect
    min_repeats = DEFAULT_MIN_REPEATS if args.min_repeats is None else args.min_repeats
    notes, overrides = [], []
    if experiment:
        before = _merge_list(before, experiment["baseline_rounds"], "--before", "baseline_rounds", notes, overrides)
        after = _merge_list(after, experiment["after_rounds"], "--after", "after_rounds", notes, overrides)
        targets = _merge_list(targets, experiment["targets"], "--targets", "target_prompts", notes, overrides)
        controls = _merge_list(controls, experiment["controls"], "--controls", "control_prompts", notes, overrides)
        alpha = _merge_value(alpha, experiment["alpha"], "--alpha", "alpha", notes, overrides)
        min_effect = _merge_value(min_effect, experiment["min_effect"], "--min-effect", "min_effect", notes,
                                  overrides)
        if min_repeats != DEFAULT_MIN_REPEATS:
            # 実験の記録には最小の繰り返しの欄がないので、既定の値を事前に決めた条件とみなす
            notes.append("コマンドラインの指定を実験の記録より優先した: --min-repeats {}（実験の記録には欄がないので、"
                         "既定の {} を事前に決めた条件とみなす）".format(min_repeats, DEFAULT_MIN_REPEATS))
            overrides.append("--min-repeats")
    if alpha is None:
        alpha = DEFAULT_ALPHA
    if not before:
        raise InputError("変更前のラウンドを --before で指定してください（実験の記録なら baseline_rounds に書く。"
                         "記録の空の欄をコマンドラインで補うと、確認的な判定は出さない）")
    if not after:
        raise InputError("変更後のラウンドを --after で指定してください（実験の記録なら after_rounds に書く。"
                         "記録の空の欄をコマンドラインで補うと、確認的な判定は出さない）")
    both = [name for name in before if name in after]
    if both:
        raise InputError("同じラウンドが変更前と変更後の両方にあります: {}".format(", ".join(both)))
    overlap = [pid for pid in targets if pid in controls]
    if overlap:
        raise InputError("同じプロンプトが対象と対照の両方にあります: {}".format(", ".join(overlap)))
    _check_rounds(rows, before, "変更前")
    _check_rounds(rows, after, "変更後")

    metrics = list(JUDGED_METRICS) if args.metric in (None, "all") else [args.metric]
    confirm_label = None
    no_confirm_reason = ""
    primary_metric = experiment["primary_metric"] if experiment else None
    primary_group = experiment["primary_group"] if experiment else None
    if experiment:
        if not primary_metric or not primary_group:
            no_confirm_reason = "実験の記録に primary_group か primary_metric がない"
        elif not experiment["targets"]:
            no_confirm_reason = ("実験の記録に対象のプロンプト（target_prompts）がない。対象は変更前のラウンドの前に"
                                 "決めて書く")
        elif overrides:
            no_confirm_reason = "コマンドラインで実験の記録の条件を変えたか、空の欄を補った: {}".format(
                ", ".join(overrides))
        elif group_by != DEFAULT_GROUP_BY:
            no_confirm_reason = "--group-by を既定から変えたため、primary_group と組が対応しない"
        else:
            confirm_label = "{}、{}".format(group_label(primary_group), METRIC_LABELS[primary_metric])
            if primary_metric not in metrics:
                metrics.append(primary_metric)
                notes.append("--metric で選んでいないが、実験の primary_metric（{}）を加えた".format(primary_metric))
            metrics = [m for m in JUDGED_METRICS if m in metrics]

    before_set, after_set = set(before), set(after)
    before_rows = [r for r in rows if r.get("round") in before_set]
    after_rows = [r for r in rows if r.get("round") in after_set]
    results = compare_groups(before_rows, after_rows, targets, controls, metrics, group_by, alpha,
                             min_repeats, min_effect)
    confirm = None
    if confirm_label:
        for res in results:
            if res["metric"] == primary_metric and _same_group(res["key"], primary_group):
                confirm = res
                break
    warnings += compare_warnings(before_rows, after_rows, results, group_by, experiment, run_info, before, after)
    # どの回答にもない ID（打ち間違い）。組ごとの「この組で観測がない」だけでは気づきにくい
    seen = set(r.get("prompt_id") for r in before_rows + after_rows)
    for ids, set_label in ((targets, "対象"), (controls, "対照")):
        unknown = [pid for pid in ids if pid not in seen]
        if unknown:
            warnings.append("{}のプロンプトのうち、指定したラウンドのどの回答にもない ID: {}（打ち間違いでないか"
                            "確かめる）".format(set_label, ", ".join(unknown)))
    empty_groups, empty_counts = empty_compare_groups(before_rows, after_rows, group_by)
    ctx = {
        "experiment": experiment, "confirm": confirm, "confirm_label": confirm_label,
        "no_confirm_reason": no_confirm_reason, "before_rounds": before, "after_rounds": after,
        "targets": targets, "controls": controls, "alpha": alpha, "min_repeats": min_repeats,
        "min_effect": min_effect, "group_by": group_by, "run_info": run_info, "notes": notes,
        "empty_groups": empty_groups, "empty_counts": empty_counts,
    }
    text = render_compare(results, ctx, _dedupe(warnings))
    judged = [r for r in results if r["metric"] is not None]
    summary = "比較しました: 組 {} 件、判定 {} 件（{}）".format(
        len(set(r["key"] for r in results)), len(judged),
        "確認的な判定: {}".format(confirm["final"]["verdict"]) if confirm else "すべて探索的")
    return text, summary, results


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------

def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = ArgumentParser(
        prog="compare_runs.py",
        description="observations.csv から、ラウンド群の集計（--period）か、変更の前と後の比較"
                    "（--before と --after、または --experiment）を Markdown で出す。",
        epilog="例:\n"
               "  python3 compare_runs.py --period 2026-10-01,2026-10-08\n"
               "  python3 compare_runs.py --before 2026-10-01,2026-10-08 --after 2026-10-29 "
               "--targets P003,P004 --controls P001,P002 --metric citation\n"
               "  python3 compare_runs.py --experiment ai-search/experiments/E001.md --details-csv details.csv\n"
               "\n"
               "判定は プロンプトごとの率の差 と 符号検定 で行い、差が出たプロンプトが {} 件未満なら判定不能。\n"
               "改善シグナルは施策と整合的な変化が見えたという意味で、原因を示すものではない。".format(MIN_CHANGED),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", default="ai-search", help="観測データのフォルダ（既定: ai-search。作業フォルダの中の ai-search/）")
    parser.add_argument("--observations", help="observations.csv の場所（既定: <workspace>/observations.csv）")
    parser.add_argument("--period", help="集計するラウンド（カンマ区切り）")
    parser.add_argument("--before", help="変更前のラウンド（カンマ区切り）")
    parser.add_argument("--after", help="変更後のラウンド（カンマ区切り）")
    parser.add_argument("--experiment", help="実験の記録（experiments/E001.md）。条件をここから読む")
    parser.add_argument("--targets", help="対象のプロンプト ID（既定: 対照以外のすべて）")
    parser.add_argument("--controls", help="対照のプロンプト ID")
    parser.add_argument("--metric", choices=("mention", "citation", "all"),
                        help="判定する指標（既定: all = mention と citation）")
    parser.add_argument("--alpha", type=float, help="有意水準（既定: {}）".format(DEFAULT_ALPHA))
    parser.add_argument("--min-repeats", type=int,
                        help="比較に使うプロンプトの、各期間の有効な回答の最小数（既定: {}。--experiment で既定から"
                             "変えると確認的な判定を出さない）".format(DEFAULT_MIN_REPEATS))
    parser.add_argument("--min-effect", type=float, help="実務上の最小効果（プロンプトごとの率の差の平均。既定: なし）")
    parser.add_argument("--group-by", help="組の分け方（カンマ区切り。既定: {}）".format(",".join(DEFAULT_GROUP_BY)))
    parser.add_argument("-o", "--output", help="Markdown の出力先（既定: 標準出力）")
    parser.add_argument("--details-csv", help="プロンプトごとの比較表の CSV の出力先（比較のときだけ）")
    return parser


def run(args):
    # type: (argparse.Namespace) -> int
    period_mode = args.period is not None
    compare_mode = any(v is not None for v in (args.before, args.after, args.experiment))
    if period_mode and compare_mode:
        raise InputError("--period と、--before / --after / --experiment は同時に使えません")
    if not period_mode and not compare_mode:
        raise InputError("--period か、--before と --after（または --experiment）を指定してください")
    if period_mode and (args.targets is not None or args.controls is not None or args.details_csv):
        raise InputError("--targets、--controls、--details-csv は比較（--before / --after か --experiment）で使います")
    if args.alpha is not None:
        _check_alpha(args.alpha, "--alpha")
    _check_min_effect(args.min_effect, "--min-effect")
    if args.min_repeats is not None and args.min_repeats < 1:
        raise InputError("--min-repeats は 1 以上にしてください: {}".format(args.min_repeats))
    group_by = _parse_group_by(args.group_by)
    # 出力先は読み込みの前に確かめる（報告を書いたあとで CSV の出力先の誤りに気づく、を防ぐ）
    _check_output_path(args.output, "-o")
    _check_output_path(args.details_csv, "--details-csv")
    if args.output and args.details_csv and (
            os.path.normcase(os.path.abspath(args.output)) == os.path.normcase(os.path.abspath(args.details_csv))):
        raise InputError("-o と --details-csv に同じファイルが指定されています: {}".format(args.output))

    obs_path = args.observations or os.path.join(args.workspace, "observations.csv")
    rows = load_observations(obs_path)
    base_dir = os.path.dirname(os.path.abspath(obs_path))
    warnings = []
    run_info = load_run_info(os.path.join(base_dir, "observations.run.json"), warnings)

    if period_mode:
        rounds = parse_id_list(args.period)
        if not rounds:
            raise InputError("--period に集計するラウンドを書いてください")
        _check_rounds(rows, rounds, "--period ")
        round_set = set(rounds)
        selected = [r for r in rows if r.get("round") in round_set]
        warnings += period_warnings(selected, group_by)
        competitors = load_competitor_names(os.path.join(args.workspace, "entities.csv"), warnings)
        citations = load_citations(os.path.join(base_dir, "citations.csv"))
        text = render_period(selected, rounds, group_by, run_info, competitors, citations, _dedupe(warnings))
        summary = "集計しました: ラウンド {} 件、回答 {} 件、組 {} 件".format(
            len(rounds), len(selected), len(_split_empty_groups(_group_rows(selected, group_by))[0]))
        results = None
    else:
        text, summary, results = run_compare(args, rows, run_info, group_by, warnings)

    # ファイルの出力を先に書き、標準出力は最後に書く（書けなかったときに、報告だけが出て終わらないように）
    if results is not None and args.details_csv:
        details = detail_rows(results)
        _write_file(args.details_csv, "--details-csv", lambda target: write_csv(target, DETAIL_FIELDS, details))
        log("プロンプトごとの比較表を書きました: {}（{} 行）".format(args.details_csv, len(details)))
    _write_output(text, args.output)
    log(summary)
    for warning in _dedupe(warnings):
        log("警告: " + warning)
    return 0


def main(argv=None):
    # type: (object) -> int
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except InputError as exc:
        log("エラー: {}".format(exc))
        return 2
    except Exception as exc:  # noqa: BLE001  想定外のエラーは終了コード 1
        log("想定外のエラー（compare_runs.py {}）: {}: {}".format(VERSION, type(exc).__name__, exc))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
