#!/usr/bin/env bash
# 評価の実行ごとの空の作業フォルダに、このケースの架空の観測データを ai-search/ として写す。
# claude plugin eval は、--scaffold を付けたときだけ、作業フォルダを cwd にしてこのスクリプトを
# bash で起動する。fixtures/ は ai-search/ の中身そのもの（.gitignore の ai-search/ に
# 当たらないよう、リポジトリではこの名前で置いている）。
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ai-search
cp -R "$case_dir/fixtures/." ai-search/
