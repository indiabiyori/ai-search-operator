# -*- coding: utf-8 -*-
"""
全スクリプトに共通のテスト。

- --help が終了コード 0 で、使い方（usage）を表示する
- python -S（site-packages を読まない）でも --help が動く。標準ライブラリだけで動くことの確認。
  環境変数 PYTHONPATH と PYTHONHOME は除いて実行する（それらから第三者のパッケージを読めてしまうため）
- python -I（スクリプトのフォルダを sys.path に入れない起動）でも --help が動く。
  スクリプトが自分で同じフォルダを sys.path に入れて、共通処理を読んでいることの確認
- -B を付けずに --help を実行してもバイトコードを書かない（スクリプト自身が sys.dont_write_bytecode を
  設定していることの確認）。スキルのフォルダを一時フォルダに写して、その写しで確かめる。
  バイトコードの置き場所は -X pycache_prefix で一時フォルダに決め、写しの中と合わせて調べる
- import しているのが標準ライブラリと ai_search_common だけである（ast で調べる。importlib.import_module と
  __import__ による動的な import も認めない）

スクリプトがまだないときは skip せず失敗にする（作り忘れを見逃さないため）。
"""
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# python3 -m unittest tests.<モジュール名> でリポジトリのルートから実行しても helpers を読めるようにする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

# コマンドとして使うスクリプト（共通処理の ai_search_common.py は除く）
SCRIPT_NAMES = ("new_round", "normalize_observations", "compare_runs", "ai_robots_check")

# import してよい名前（ドットの前の部分）。Python 3.9 には sys.stdlib_module_names がないので、
# スクリプトが使いそうな標準ライブラリの名前をここに並べる。足りなければ標準ライブラリであることを確かめて足す
ALLOWED_IMPORTS = frozenset([
    "__future__", "argparse", "ast", "base64", "bisect", "calendar", "codecs", "collections", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "decimal", "difflib", "email", "enum", "errno", "fnmatch",
    "fractions", "functools", "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib", "io",
    "ipaddress", "itertools", "json", "locale", "logging", "math", "mimetypes", "ntpath", "operator", "os",
    "pathlib", "platform", "posixpath", "pprint", "random", "re", "select", "shlex", "shutil", "signal",
    "socket", "socketserver", "ssl", "stat", "statistics", "string", "struct", "subprocess", "sys",
    "tempfile", "textwrap", "threading", "time", "traceback", "types", "typing", "unicodedata", "urllib",
    "uuid", "warnings", "zipfile", "zlib",
    # 同じフォルダの共通処理
    "ai_search_common",
])

# 動的な import に使う関数の名前。ast の import 文の検査では見つからないので、呼び出しとして探す
DYNAMIC_IMPORT_FUNCS = frozenset(["import_module", "__import__"])


def script_path(name, scripts_dir=None):
    return os.path.join(scripts_dir or helpers.SCRIPTS, name + ".py")


def clean_env(**extra):
    """PYTHON で始まる環境変数（PYTHONPATH、PYTHONHOME、PYTHONDONTWRITEBYTECODE など）を除いた環境。"""
    env = dict((key, value) for key, value in os.environ.items() if not key.upper().startswith("PYTHON"))
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def run_python(args, cwd=None, env=None):
    """Python を clean_env() で実行する（helpers.run_script と違い -B を付けない）。"""
    return subprocess.run([sys.executable] + list(args), cwd=cwd, env=env if env is not None else clean_env(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8")


def imported_names(path):
    """ファイルの中のすべての import（関数の中や try の中も含む）の名前の先頭の部分を返す。"""
    with open(path, "rb") as f:
        tree = ast.parse(f.read(), filename=path)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # 相対 import はスクリプトとして実行すると動かないので許さない
                names.append("." * node.level + (node.module or ""))
            else:
                names.append(node.module.split(".")[0])
    return names


def dynamic_imports(path):
    """importlib.import_module(...) や __import__(...) の呼び出しを「名前（n 行目）」の一覧で返す。"""
    with open(path, "rb") as f:
        tree = ast.parse(f.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in DYNAMIC_IMPORT_FUNCS:
            found.append("動的な import: {}（{} 行目）".format(func.id, node.lineno))
        elif isinstance(func, ast.Attribute) and func.attr in DYNAMIC_IMPORT_FUNCS:
            found.append("動的な import: .{}（{} 行目）".format(func.attr, node.lineno))
    return found


def disallowed_imports(path):
    names = sorted(set(name for name in imported_names(path) if name not in ALLOWED_IMPORTS))
    return names + dynamic_imports(path)


def bytecode_in(root):
    """root の下の __pycache__ フォルダと .pyc / .pyo ファイルの一覧。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        found.extend(os.path.join(dirpath, d) for d in dirnames if d == "__pycache__")
        found.extend(os.path.join(dirpath, f) for f in filenames if f.endswith((".pyc", ".pyo")))
    return found


def module_bytecode_in(prefix, names):
    """pycache_prefix のフォルダの下から、names のモジュールのバイトコード（<名前>.cpython-XY.pyc）を探す。"""
    found = []
    for dirpath, _dirnames, filenames in os.walk(prefix):
        found.extend(os.path.join(dirpath, f) for f in filenames
                     if f.endswith((".pyc", ".pyo")) and f.split(".")[0] in names)
    return found


def run_without_B(script, cwd, prefix):
    """
    -B を付けずに Python を実行する。バイトコードの置き場所を -X pycache_prefix で prefix に決めておく。
    macOS の /usr/bin/python3（3.9）は既定で pycache_prefix が ~/Library/Caches/com.apple.python になっていて、
    ソースの横に __pycache__ を作らない。置き場所を決めておけば、どの Python でも同じように確かめられる。
    """
    return run_python(["-X", "pycache_prefix=" + prefix, script, "--help"], cwd=cwd)


class _ScriptChecks(object):
    """スクリプトごとのテスト。script に名前を入れた TestCase と組み合わせて使う。"""

    script = ""

    def setUp(self):
        # 作業フォルダの外（スクリプトと別のフォルダ）から実行しても、同じフォルダの共通処理を読めることも確かめる
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_script_exists(self):
        path = script_path(self.script)
        self.assertTrue(os.path.isfile(path), "スクリプトがありません: {}".format(path))

    def test_help(self):
        self.assert_script_exists()
        proc = helpers.run_script(self.script, ["--help"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage", proc.stdout)

    def test_help_without_site_packages(self):
        # PYTHONPATH と PYTHONHOME を除いた環境で -S。ScriptsFolderTest の前提の確認と同じ環境にする
        self.assert_script_exists()
        proc = run_python(["-S", "-B", script_path(self.script), "--help"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage", proc.stdout)

    def test_help_in_isolated_mode(self):
        # -I はスクリプトのフォルダを sys.path に入れない（3.11 以上の -P や PYTHONSAFEPATH=1 と同じ状況）。
        # -I は PYTHONIOENCODING も読まないので、-X utf8 で入出力を UTF-8 にする
        self.assert_script_exists()
        proc = run_python(["-I", "-X", "utf8", "-B", script_path(self.script), "--help"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage", proc.stdout)

    def test_help_does_not_write_bytecode(self):
        # 利用者は -B を付けずに実行する。スキルのフォルダの写しで実行し、__pycache__ ができないことを確かめる
        # （本物のスキルのフォルダでは試さない。失敗したときに __pycache__ を残してしまうため）
        self.assert_script_exists()
        copy = os.path.join(self.tmp, "skill")
        shutil.copytree(helpers.SKILL_DIR, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        scripts = os.path.join(copy, "scripts")
        names = set(os.path.splitext(n)[0] for n in os.listdir(scripts) if n.endswith(".py"))
        work = os.path.join(self.tmp, "work")
        os.makedirs(work)
        prefix = os.path.join(self.tmp, "pycache-prefix")
        proc = run_without_B(script_path(self.script, scripts), work, prefix)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(bytecode_in(copy) + module_bytecode_in(prefix, names), [],
                         "{}.py を -B なしで実行するとバイトコードが残ります。import の前に "
                         "sys.dont_write_bytecode = True を置いてください".format(self.script))

    def test_imports_standard_library_only(self):
        self.assert_script_exists()
        self.assertEqual(disallowed_imports(script_path(self.script)), [],
                         "標準ライブラリと ai_search_common 以外の import があります")


class NewRoundCliTest(_ScriptChecks, unittest.TestCase):
    script = "new_round"


class NormalizeObservationsCliTest(_ScriptChecks, unittest.TestCase):
    script = "normalize_observations"


class CompareRunsCliTest(_ScriptChecks, unittest.TestCase):
    script = "compare_runs"


class AiRobotsCheckCliTest(_ScriptChecks, unittest.TestCase):
    script = "ai_robots_check"


class ScriptsFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_python_S_hides_site_packages(self):
        # 前提の確認: -S のテストと同じ環境・同じ起動のしかたで、site-packages が sys.path に入らないこと
        # （入るなら -S のテストは意味がない）
        code = "import sys; print([p for p in sys.path if 'site-packages' in p or 'dist-packages' in p])"
        proc = run_python(["-S", "-B", "-c", code], cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "[]")

    def test_runner_ignores_pythonpath(self):
        # PYTHONPATH に第三者のパッケージがある環境でも、-S のテストはそれを読まない
        third = os.path.join(self.tmp, "third")
        os.makedirs(third)
        with open(os.path.join(third, "fakethird.py"), "w", encoding="utf-8") as f:
            f.write("VALUE = 1\n")
        code = "import importlib.util; print(importlib.util.find_spec('fakethird') is not None)"
        work = os.path.join(self.tmp, "work")
        os.makedirs(work)
        with mock.patch.dict(os.environ, {"PYTHONPATH": third}):
            plain_env = dict(os.environ)
            cleaned = run_python(["-S", "-B", "-c", code], cwd=work)  # clean_env() はこの時点の環境から作る
        # 対照: 環境をそのまま渡すと読めてしまう
        plain_env.pop("PYTHONHOME", None)
        plain = run_python(["-S", "-B", "-c", code], cwd=work, env=plain_env)
        self.assertEqual(plain.stdout.strip(), "True", plain.stderr)
        self.assertEqual(cleaned.stdout.strip(), "False", cleaned.stderr)

    def test_bytecode_is_written_without_B(self):
        # 前提の確認: test_help_does_not_write_bytecode と同じ起動のしかたで、dont_write_bytecode を設定しない
        # スクリプトなら、import したモジュールのバイトコードが見つかること（見つからないならそのテストは意味がない）
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        with open(os.path.join(src, "mod_a.py"), "w", encoding="utf-8") as f:
            f.write("X = 1\n")
        with open(os.path.join(src, "main_a.py"), "w", encoding="utf-8") as f:
            f.write("import mod_a\n")
        prefix = os.path.join(self.tmp, "pycache-prefix")
        proc = run_without_B(os.path.join(src, "main_a.py"), src, prefix)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotEqual(bytecode_in(src) + module_bytecode_in(prefix, {"mod_a"}), [])

    def test_dynamic_imports_are_detected(self):
        path = os.path.join(self.tmp, "dyn.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("import importlib\n"
                    "from importlib import import_module\n"
                    "importlib.import_module('fakethird')\n"
                    "import_module('fakethird2')\n"
                    "__import__('fakethird3')\n")
        found = disallowed_imports(path)
        self.assertEqual(len(found), 3, found)
        self.assertTrue(all("動的な import" in item for item in found), found)
        # 通常の標準ライブラリの import だけなら何も出ない
        with open(path, "w", encoding="utf-8") as f:
            f.write("import os\nimport importlib.util\nfrom urllib.parse import urlsplit\n")
        self.assertEqual(disallowed_imports(path), [])

    def test_every_script_imports_standard_library_only(self):
        # 上の4本のほか、共通処理とあとから足したスクリプトも調べる
        names = sorted(n for n in os.listdir(helpers.SCRIPTS) if n.endswith(".py"))
        self.assertIn("ai_search_common.py", names)
        for name in names:
            with self.subTest(script=name):
                self.assertEqual(disallowed_imports(os.path.join(helpers.SCRIPTS, name)), [])


if __name__ == "__main__":
    unittest.main()
