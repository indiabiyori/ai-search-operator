# -*- coding: utf-8 -*-
"""テストの共通処理。対象のスキルのフォルダは環境変数 AI_SEARCH_OPERATOR_DIR で切り替えられる。"""
import importlib.util
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("AI_SEARCH_OPERATOR_DIR", os.path.join(REPO, "skills", "ai-search-operator"))))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
FIXTURES = os.path.join(REPO, "tests", "fixtures")

sys.dont_write_bytecode = True  # スキルのフォルダに __pycache__ を残さない
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def load_script(name):
    """scripts/<name>.py をモジュールとして読み込む。"""
    path = os.path.join(SCRIPTS, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(name, args, cwd=None, python=None, extra_flags=()):
    """スクリプトを別プロセスで実行し、CompletedProcess を返す（標準出力と標準エラーは UTF-8 の文字列）。"""
    cmd = [python or sys.executable] + list(extra_flags) + ["-B", os.path.join(SCRIPTS, name + ".py")]
    cmd += list(args)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, encoding="utf-8")
