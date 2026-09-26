# ai-search-operator のテスト

`ai-search-operator` スキルの回帰テスト。スクリプト4本（new_round.py、normalize_observations.py、compare_runs.py、ai_robots_check.py）と、共通処理の ai_search_common.py を確かめる。AI クローラーの一覧（data/ai-crawlers.csv）の形と中身も見る。

テストはスキル本体（`skills/ai-search-operator`）とは別に置いてある。claude.ai 用の zip には入らない。プラグインで入れるとリポジトリ全体がコピーされるが、スキルとして読み込まれるのは `skills/ai-search-operator` だけ。スクリプトか一覧を直したら、ここのテストを全件通してから使う。

## 前提

- Python 3.9 以上。パッケージも仮想環境も要らない。スクリプトもテストも、標準ライブラリだけで書いてある
- ai_robots_check.py の取得のテストは、127.0.0.1 にテスト用のサーバーを立てて行う。ホスト名の解決が要る場面は、テストの中で差し替える

## 実行

リポジトリのフォルダ（`tests/` の1つ上）で実行する。

```bash
python3 -B -m unittest discover -s tests
```

最後の行が `OK` なら合格。その直前の `Ran 548 tests` で件数を確かめる。手元では十数秒で終わる。1件ずつ名前を出したいときは `-v` を付ける（GitHub Actions はそうしている）。

`-B` を付けるのを勧める。付けなくてもテストは通る。ただ、unittest がテストのファイルを読み込むときに `tests/__pycache__` ができる（`.gitignore` で除外済み）。スキルのフォルダには、`-B` の有無にかかわらず `__pycache__` を作らない。スクリプトとテストの共通処理（helpers.py）が、どちらもバイトコードを書かない設定にしているため。

1つのファイルだけを回すときは、`-p` でファイル名を指定する。

```bash
python3 -B -m unittest discover -s tests -p test_compare.py
```

## テストする対象の切り替え

既定では、このリポジトリの `skills/ai-search-operator` をテストする。インストール済みのスキルなど、別のフォルダを試すときは、環境変数 `AI_SEARCH_OPERATOR_DIR` でスキルのフォルダを指定する。

```bash
AI_SEARCH_OPERATOR_DIR=~/.claude/skills/ai-search-operator python3 -B -m unittest discover -s tests
```

テストのデータ（`tests/fixtures/`）は、どちらの場合もこのリポジトリのものを使う。作業用のファイルは一時フォルダに作る。対象のフォルダには何も書き込まない。

## テストのデータは架空のもの

テストで使う会社名、ドメイン、回答はすべて架空のもの（架空珈琲、サンプル焙煎、テスト豆店、kakuu-coffee.example など）。実在のサイトについての AI の回答や、Search Console・Bing のレポートは入れない。`tests/fixtures/workspace/` は観測データのフォルダ（`ai-search/`）と同じ形で、entities.csv、prompts.csv、回答ファイル7件を置いてある。`tests/fixtures/ai-crawlers.csv` は判定のテストだけに使う短い一覧。

例外は test_crawlers_data.py で、スキルに同梱した本物の一覧（`data/ai-crawlers.csv`）を読んで確かめる。

## ファイルごとの対象

件数は、unittest が数えた 2026-09-27 時点のもの。

| ファイル | 件数 | 確かめること |
|---|---|---|
| test_normalize.py | 147 | normalize_observations.py。先頭の欄と見出しの解析、URL の抽出（Markdown のリンク、末尾の句読点、かっこ、追跡用のパラメータ、Google のリダイレクト、短縮 URL）、表記の照合（全角・半角、英数字の境界、除外語）、ドメインの照合（サブドメイン、いちばん長いドメインを優先）、ChatGPT の出典の表示を言及に数えないこと、observed_at の日付、警告 |
| test_robots.py | 120 | ai_robots_check.py。robots.txt の解釈（seo-operator v1.1.0 の audit.py のテストから移植）、代わりのグループに従うクローラー（Applebot など）、`*` のグループの警告、取得の結果ごとの扱い（2xx、3xx、4xx、429、5xx、タイムアウト、TLS のエラー）、内部アドレスの拒否 |
| test_compare.py | 118 | compare_runs.py。符号検定の p 値（既知の値との一致）、判定不能の境界（m=5 と m=6）、最小効果と対照で調整した差の境目（分数で厳密に計算）、確認的な判定と探索的な判定の切り替え、条件の組を合算しないこと、`claude-draft` を誤った説明の率の分母に入れないこと、報告の警告 |
| test_new_round.py | 56 | new_round.py。ひな形とテンプレートの一致、作るファイルの数（プロンプト × サービス × 回数）、既存のファイルを上書きしないこと、`--prompts` や `--mode` などの条件の反映、入力の誤りと書き込みの失敗を終了コード 2 にすること |
| test_crawlers_data.py | 43 | data/ai-crawlers.csv。列と category の値、トークンの重複と使えない文字、確認日と出典の URL。後半は本物の一覧を ai_robots_check.py に通し、一覧の説明と判定の結果が食い違わないかを見る |
| test_common.py | 39 | ai_search_common.py。表記の正規化（NFKC、大文字・小文字、空白、ダッシュ類）、CSV インジェクション対策と読み戻し、文字コード（BOM 付き UTF-8、UTF-16、CP932）と改行、先頭の欄の解析、entities.csv と prompts.csv の検査、率の丸め、日本語の使い方と引数の誤りの文 |
| test_cli.py | 25 | 4本のスクリプトに共通。`--help` が終了コード 0 で使い方を出すこと、`python -S`（site-packages を読まない）と `python -I` でも `--help` が動くこと、`-B` なしでもバイトコードを書かないこと、import しているのが標準ライブラリと ai_search_common だけであること |

helpers.py にテストは入っていない。対象のフォルダの切り替えと、スクリプトの読み込み・実行を受け持つ共通処理である。

## Python 3.9 での確認

スクリプトは Python 3.9 以上で動くように書いてある。macOS では、コマンドライン・デベロッパ・ツールを入れると `/usr/bin/python3`（3.9）が使える。パッケージも仮想環境もなしに、そのまま全件を回せる。

```bash
/usr/bin/python3 --version   # Python 3.9.6 など
/usr/bin/python3 -B -m unittest discover -s tests
```

3.9 と新しい版で動きが違う箇所もある。たとえば csv モジュールは、3.9 では NUL 文字を含む行でエラーを出し、3.13 では通す。こうした違いは、どちらの版で回しても両方の動きを確かめられるよう、テストの中で再現している。

## 未確認のこと

- Windows では実行していない。シンボリックリンク、ファイルの読み取りの権限、バイト列の引数を使うテストは、それらが使えない環境（Windows と、root 権限での実行）では skip する作りにしてある。ただし、Windows で skip が正しく働くかも確かめていない。
- Python 3.10 と 3.12 では実行していない。
- 最後に全件合格を確かめた環境: macOS の Python 3.9.6（`/usr/bin/python3`）、3.9.25、3.11.15、3.13.13、3.14.7（すべて 2026-09-27）。GitHub Actions では、main への push と pull request のたびに、Ubuntu の Python 3.9 と 3.13 で全件を回す（Actions の画面から手動でも回せる）。
- このテストは、Claude の答え方（率を観測の記録からだけ出す、など）を確かめない。答え方は `evals/` の評価で見る。評価はモデルの利用量を使うので、CI には入れず `claude plugin eval` で手で回す。
