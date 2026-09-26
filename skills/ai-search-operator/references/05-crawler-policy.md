# 05 AI クローラーの方針（robots.txt、検索の生成 AI 設定、CDN・WAF）

AI クローラーを robots.txt で許可するか拒否するかを決める手順。robots.txt では止まらない経路（Google の検索の生成 AI 設定、ユーザー起動のフェッチャー、CDN・WAF）も、同じ流れで確かめる。

## 1. 目的

- 今の robots.txt で、どの AI クローラーがどのパスで許可・拒否になっているかを、RFC 9309 に沿った判定（`ai_robots_check.py`）で示す。目で読んだ推測で済ませない。
- 学習、AI 検索での表示、ユーザー操作に伴う取得を分け、方針ごとに得るものと失うものを並べる。方針を決めるのは利用者で、Claude は選択肢と、あれば推奨1つを理由付きで示す。
- robots.txt で止まらないものを取り違えない。Google の AI 機能、ユーザー起動のフェッチャー、CDN・WAF の設定は、それぞれ別の画面とログで確かめる。
- クローラーの名前と用途は変わる前提で運用し、確認日の古い一覧のまま判断しない。一覧は `data/ai-crawlers.csv` が正本で、この手順書には一覧の表を載せない。

## 2. 必要な入力データ

| データ | 入手元（ツール → 画面 → 操作） | 必須/任意 | ないときの動き方 |
|---|---|---|---|
| 配信されている robots.txt | `ai_robots_check.py --url` で取得する。取得できなければ、ブラウザで `https://<ドメイン>/robots.txt` を開いて保存する | 必須 | 内容を貼ってもらい、`--file` で判定する。CMS・プラグイン・CDN が内容を書き足していることがあるので、サーバー上のファイルより配信されているものを優先する |
| AI クローラーの一覧 | スキルのフォルダの `data/ai-crawlers.csv`（列: operator, token, category, purpose, robots_control, block_effect, source_url, checked_on） | 必須（スキルに同梱） | checked_on から3か月以上たっていれば、判定の前に手順8で再確認する |
| 判定するパス | 主要なページの URL のパス（トップ、記事、料金、会員限定のページなど） | 任意 | `/` だけで判定し、報告にそう書く |
| 検索の生成 AI 設定 | Search Console →［設定］→［検索の生成 AI］ | Google の AI 機能を扱うなら必須 | 「未確認」と書く。未確認のまま、AI による概要に出ない原因を推測しない |
| CDN・WAF のボット対策の設定 | 利用中の CDN・WAF の管理画面 → ボット管理、AI ボットの設定、WAF のカスタムルール、レート制限 | 任意 | 「未確認」と書く。robots.txt で許可していても、CDN で遮断されていることがある |
| アクセスログ | CDN かサーバーのログ（UA、送信元 IP、応答コード、日時） | 任意 | クローラーが実際に取得できているかは確かめられない、と報告に書く |
| 事業の状況（学習に使われたくない資産、AI 経由の流入の価値） | `ai-search/brief.md`。seo-operator を使っていれば `seo/site-brief.md`。流入は GA4（読み方は 07-platform-reports.md） | 方針を決めるなら必須 | 方針の選択肢だけを並べ、決定は保留する。数値は `[要追加: GA4 の AI サービス経由のセッション数とキーイベント数]` とする |
| 観測の結果 | `ai-search/observations.csv` と `compare_runs.py --period` の出力（03-observation.md） | 任意 | AI の回答で引用されているかどうかを、方針の判断材料に入れない。推測で補わない |

## 3. 手順

1. 一覧の確認日を見る: `data/ai-crawlers.csv` の checked_on のうち最も古い日から3か月以上たっていれば、先に手順8の再確認を行う。`ai_robots_check.py` の報告の末尾にも、最も古い確認日が出る。
2. robots.txt を判定する: 下の「ai_robots_check.py の使い方」のコマンドを作業フォルダで実行する。報告は `ai-search/reports/` に保存する。`ai_robots_check.py` は出力先のフォルダを作らないので、`-o` を付ける前に `mkdir -p ai-search/reports` を実行する。`ai-search/` がまだなく、作ってよいという了承もなければ、フォルダを作らずに `-o` を外して実行し、標準出力の結果を示す（`ai-search/` はユーザーが明示したときだけ作る。SKILL.md の「初回セットアップ」）。
3. 判定を読む: 「判定の読み方」に沿って、分類（category）ごとに拒否しているトークンをまとめる。拒否が意図したものかを利用者に確かめ、わからないものは「未確認」と書く。意図的な拒否だと推測で書かない。
4. robots.txt ではない制御を確かめる: Google の検索の生成 AI 設定、ページ単位のスニペットの指定、Bing と Apple のメタタグを見る（「robots.txt ではない制御」）。ページ単位の指定の点検は seo-operator の 09-ai-search.md が詳しい。seo-operator が入っていなければ、Search Console の URL 検査とページのソースで `noindex` と `nosnippet` 系の指定を見る。
5. CDN・WAF を確かめる: 「CDN・WAF の確認」の手順で、管理画面の設定とログを見る。AI クローラーの UA を名乗ったリクエストで試さない。
6. 方針を決める: 決まっていなければ「クローラー方針のトレードオフ」の表を示し、利用者に選んでもらう。Claude が推奨を1つ示すのはよいが、理由と失うものを併記する。判断材料（学習に使われたくない資産、AI 経由の流入と CV、観測での引用の状況）がなければ `[要追加: ○○]` とする。
7. robots.txt を書き換える: 「robots.txt の記述例」と、その下の落とし穴を確かめて案を作る。反映したら `ai_robots_check.py` を再実行し、意図した判定になったかを確かめる。AI の回答での引用に効いたかを見たいときは、変更を実験として記録する（06-experiments.md。change_category は「クローラー」）。効果は約束しない。
8. 記録して再確認する: 判定の報告、変更日、理由、次の再確認日（確認日の3か月後）を残す。再確認は「再確認の手順」に従う。

### ai_robots_check.py の使い方

先に `python3 <スキルのディレクトリ>/scripts/ai_robots_check.py --help` で引数を確かめてから、作業フォルダで実行する。例のドメインは架空。

```bash
# 報告を ai-search/reports/ に保存するときは、先にフォルダを作る（ai_robots_check.py は作らない）
mkdir -p ai-search/reports

# 公開中のサイト。サイトの URL を渡すと /robots.txt を取得して判定する
python3 <スキルのディレクトリ>/scripts/ai_robots_check.py --url https://kakuu-coffee.example --paths /,/blog/,/menu/ -o ai-search/reports/robots-2026-09-26.md

# 取得できないときは、ブラウザで保存した robots.txt を読む
python3 <スキルのディレクトリ>/scripts/ai_robots_check.py --file robots.txt --paths /

# 表を CSV で出す（Excel で開くなら -o でファイルに書く。BOM 付き UTF-8 になる）
python3 <スキルのディレクトリ>/scripts/ai_robots_check.py --url https://kakuu-coffee.example --format csv -o ai-search/reports/robots-2026-09-26.csv
```

- `-o` の出力先のフォルダがないと、「エラー: 出力を書けません」と出て終了コード 2 で止まる。`ai-search/` がまだなく、作ってよいという了承もないときは、`mkdir` をせず `-o` を外して実行し、標準出力の結果を示す。
- 一覧は `data/ai-crawlers.csv` を読む。再確認で直した一覧を使うときは `--crawlers ai-search/ai-crawlers.csv` で差し替える。
- 取得には `ai-search-operator/<版>` という独自の UA を使い、AI クローラーを名乗らない。CDN がこの UA にブロック画面など別の応答を返すと、判定は配信されている robots.txt を表さない。ブラウザで見た内容と違えば、保存したファイルを `--file` で判定し直す。
- 取得する URL は http と https だけ。ユーザー名・パスワードを含む URL は取得しない。内部アドレス（プライベート IP など）に解決されるホストも取得しない。自社の検証環境を調べるときだけ `--allow-private` を付ける。
- 解釈は RFC 9309 に従う。UA の照合は大文字・小文字を区別せず、同じクローラーに一致するグループが複数あれば規則を合わせる。パスは最長一致で、同じ長さなら Allow を優先する。`*` と `$` に対応する。
- 調べるのは robots.txt だけ。CDN・WAF、メタタグ、Search Console の設定は見ないので、手順4と5を省かない。

### 判定の読み方

出力の列は operator, token, category, path, verdict, matched_group, matched_rule, note。verdict は次の5つのどれかになる。

| 判定（verdict） | 出る条件 | 読み方 |
|---|---|---|
| `許可` / `拒否` | robots.txt を取得して解釈できた | matched_group が適用したグループ、matched_rule が決め手のルール。matched_group が `User-agent: *` なら、そのクローラー向けのグループはない |
| `全許可（robots.txt なし）` | 429 以外の 4xx（401 と 403 を含む）。リダイレクトが5回を超えたときもここに入る（下の2つ目の注） | RFC 9309 と Google は「制限なし」として扱う。WAF が robots.txt への要求を 403 で断っている場合もここに入り、robots.txt に書いた拒否はクローラーに読まれない（ページの取得を WAF が止めているかは、別に確かめる） |
| `全拒否（取得できず）` | 5xx、タイムアウト、接続や TLS のエラー | RFC 9309 は全拒否とする。実際の扱いは運営ごとに違う（下の1つ目の注） |
| `不定（429）` | 429 | RFC 9309 では 4xx の一つなので全許可、Google はサーバーエラーとして扱う。どちらになるかはクローラーによる |

- 取得できないときの扱いは運営ごとに違う。Google は、robots.txt を取得できないと最初の12時間はサイトのクロールを止め、その後の30日は最後に取得できた版を使う（キャッシュがなければ制限なしとみなす）。Amazon は、取得できない robots.txt は存在しないものとして扱うと書いている。スクリプトは RFC 9309 に従って全拒否と出すだけなので、「各社がこのサイトを全拒否として扱う」とは読まない。どちらにしても、まずサーバーを直す。
- リダイレクトが5回を超えたときは、`全許可（robots.txt なし）` として出し、note に「リダイレクトが多すぎる」と書く。RFC 9309 の 2.3.1.2 はこの場合を unavailable（4xx と同じ全許可）とみなしてよいとし、Google も 404 として扱うため。robots.txt に書いた拒否は読まれていないので、リダイレクトの連鎖を短くする。
- `不定（429）` が出たら、CDN やサーバーのレート制限が robots.txt にもかかっていないかを確かめ、robots.txt を制限の対象から外す。Google は 429 をサーバーの過負荷の合図として扱う。
- category が `user` の行には「ユーザー操作に伴う取得のため、robots.txt が適用されない場合がある」という注記が付く（「ユーザー起動のフェッチャー」）。`control` の行には、クロールはせず学習などへの利用の可否を表すトークンだという注記が付く。
- 要約には、分類ごとに「n 件中 m 件が拒否（パス / で判定）」が出る。
- 警告は、特定のクローラー向けのグループがあって、`User-agent: *` の Disallow がそのグループに書かれていないときに出る（例: 「GPTBot 向けのグループがあるため、User-agent: * の Disallow: /admin/ は GPTBot に適用されません」）。

出典（2026-09-26 に確認）:

- RFC 9309 の 2.2.1 と 2.3.1: `https://www.rfc-editor.org/rfc/rfc9309`
- Google の robots.txt の仕様（英語版の最終更新日 2026-08-31）: `https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec`
- Google の HTTP ステータス コードの扱い（英語版の最終更新日 2026-02-04）: `https://developers.google.com/crawling/docs/troubleshooting/http-status-codes`
- Amazon: `https://developer.amazon.com/amazonbot`

### robots.txt ではない制御（2026-09-26 に確認）

#### Google の検索の生成 AI 設定

Google の AI による概要と AI モードは Googlebot が集めた検索のインデックスを使う。robots.txt で AI 機能から外そうとすると、Google 検索全体から外れてしまう。AI 機能だけを外す手段が、Search Console の［設定］→［検索の生成 AI］にある「検索の生成 AI 設定」。2026年8月31日に全世界のサイトへ提供された。

- 対象: AI による概要、AI モード、Google Discover の生成 AI 機能。
- 選択肢: 「含める」（すべてのプロパティの既定）、「除外する」、「親から設定を継承する」（親プロパティがあるときの既定）。子プロパティは親の設定を引き継ぐので、除外されていないかは親のプロパティでも確かめる。
- 除外すると: サイトへのリンクと内容が表示されず、AI の回答の根拠（グラウンディング）にも使われない。これらの機能からの表示回数と流入もなくなる。ほかのサイトの似た内容は表示されうる。
- 除外しても変わらないもの: ほかの検索結果でのランキングと掲載のシグナルには使われない。AI の学習には影響しない（学習は Google-Extended。次の節）。言語の理解など、Google 検索全体の改良には使われうる。検索から完全に外すなら `noindex`。
- 反映: 通常は数日。設定が有効になってから1〜2日で除外されるが、キャッシュの関係でもっとかかる内容もある。
- 表示の条件は、資料によって書き方が違う。最適化ガイド（Google 検索の生成 AI 機能向けにウェブサイトを最適化する。英語版の最終更新日 2026-07-10、日本語版は 2026-09-23）は、検索の技術要件に加えて、この設定で「含める」になっていることを表示の条件にしている。AI 機能とウェブサイトのページ（英語版の最終更新日 2025-12-10、日本語版は 2025-12-31）は「追加の技術要件はない」のままになっている。新しいガイドに合わせて、設定が「除外」になっていないかを確かめる。
- ページ単位の指定でも AI 機能で使われる情報を絞れるが、効き方は指定ごとに違う。`nosnippet` はそのページを AI による概要・AI モードの直接の入力に使わせないが、通常の検索結果のスニペットも消える。`max-snippet` は直接の入力に使う量を制限し、`data-nosnippet` は印を付けた部分をスニペットに使わせない。どちらもページを AI 機能から外すものではない。`noindex` は検索全体から外す。AI 機能とウェブサイトのページも、これらを表示する情報を「制限する」手段として挙げている。

出典（2026-09-26 に確認）:

- 検索の生成 AI 設定: `https://support.google.com/webmasters/answer/16908024?hl=ja`
- 最適化ガイド: `https://developers.google.com/search/docs/fundamentals/ai-optimization-guide`
- AI 機能とウェブサイト: `https://developers.google.com/search/docs/appearance/ai-features`
- robots メタタグ（英語版の最終更新日 2026-03-24、日本語版は 2026-03-25）: `https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag`

#### Bing（Copilot）

Copilot 専用の robots.txt のトークンはなく、Bing の資料が示す手段は robots メタタグ（X-Robots-Tag でもよい）だけ。`name="robots"` を `name="bingbot"` に替えると Bing だけに効く。

- `noindex`: Bing のインデックスに入れず、Microsoft の生成 AI の基盤モデルの学習にも使わない。タグを読むにはクロールが必要なので、robots.txt でそのページを拒否しない。
- `noarchive`: Chat と Copilot でリンクせず、学習にも使わない。
- `nocache`: Chat と Copilot では URL・タイトル・スニペットだけを表示し、学習にもその範囲だけを使う。`noarchive` と両方あれば `nocache` として扱う。
- Bing のガイドラインは、`nosnippet` と `data-nosnippet` が Copilot での引用の質を下げうること、`nocache` が引用の深さと回答の質を下げることを書いている。Bingbot を robots.txt で拒否したときに Copilot から外れるかを直接書いた文は、確認できていない。

出典: `https://www.bing.com/webmasters/help/robots-meta-tags-and-attributes-that-bing-supports-5198d240`、`https://www.bing.com/webmasters/help/webmaster-guidelines-30fba23a`（どちらも更新日の表示なし）。

#### Apple（Siri と検索の AI による回答）

Apple が Siri と検索の AI による回答から外す手段として示しているのは `nosnippet` のメタタグで、Applebot-Extended は基盤モデルの学習の制御だけを受け持つ。Apple だけに効かせるなら `<meta name="applebot" content="nosnippet">` か、X-Robots-Tag の `applebot: nosnippet` を使う。`name="robots"` はすべてのクローラーに向けた指定なので、そこに書くと Google などほかの検索のスニペットも消える。

出典: Apple（`https://support.apple.com/en-us/119829`、2026-09-04 公開）、Google の robots メタタグ（`https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag?hl=ja`、日本語版の最終更新日 2026-03-25）。

### Google-Extended の記述の食い違い（2026-09-26 に確認）

Google-Extended はクロールをしない制御用のトークンで、拒否しても AI による概要・AI モードでの表示は止まらない。共通クローラーのページは Google 検索への掲載に影響しないと書き、検索の生成 AI 設定のヘルプも表示の制御にはこの設定を案内しているので、この点に食い違いはない。資料の書き方が分かれるのは、検索の生成 AI 機能のモデルの学習に効くかどうか。

- 共通クローラーのページ（英語版の最終更新日 2026-07-14）: 対象は、Gemini アプリと Vertex AI API for Gemini を支える将来の Gemini モデルの学習と、Gemini アプリと Vertex AI（Grounding with Google Search）でのグラウンディング。Google 検索への掲載に影響せず、ランキングのシグナルにも使わない。
- 検索の生成 AI 設定のヘルプ: 「検索の生成 AI 機能で回答を生成するために使用されるモデルのトレーニングを制限するには、Google-Extended をご利用ください」とある。
- AI 機能とウェブサイトのページ（英語版の最終更新日 2025-12-10）: Google のほかのシステムでの学習とグラウンディングを制限する手段として Google-Extended を案内している。

検索の生成 AI 機能のモデルの学習に Google-Extended が効くかは、確認できていない。ヘルプは効くと読めるが、共通クローラーのページは Gemini アプリと Vertex AI しか挙げていない。報告では目的ごとに手段を分けて書く。

- AI による概要・AI モードでの表示を止めたい: 検索の生成 AI 設定で除外する。ページ単位なら `nosnippet` を使うが、通常の検索結果のスニペットも消える。
- 学習への利用を減らしたい: Google-Extended を拒否する。検索の生成 AI 機能のモデルへの効果は `[要確認: Google-Extended が検索の生成 AI 機能のモデルの学習に効くか（公式資料の記述が一致していない）]` と書き、「拒否すれば検索の AI の学習に使われない」と断定しない。
- 両方を組み合わせてもよい（方針 B と D）。

出典: `https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers`、`https://support.google.com/webmasters/answer/16908024?hl=ja`、`https://developers.google.com/search/docs/appearance/ai-features`。

### ユーザー起動のフェッチャー（2026-09-26 に確認）

ユーザーが AI に質問したり操作を頼んだりしたときに、その場でページを取りに来るアクセスを、ユーザー起動のフェッチャーと呼ぶ。自動の巡回（クロール）とは扱いを分ける運営が多く、robots.txt で拒否しても取得されることがある。`data/ai-crawlers.csv` では category が `user` の行で、robots_control の列に各社の説明がある。運営の説明は3通りに分かれる。

- 一般に robots.txt を無視する、または迂回することがあると説明: Google（Google-Agent、Google-GeminiNotebook）、Meta（meta-externalfetcher）、Perplexity（Perplexity-User）。
- 適用されない場合がある、またはすべてには従わない場合があると説明: OpenAI（ChatGPT-User）、Amazon（Amzn-User）。
- robots.txt で制御できると説明: Anthropic（Claude-User。Anthropic のボットは robots.txt を尊重すると書いている）、Mistral AI（MistralAI-User。どのサイトに取得を行えるかを制御する、という書き方で、順守するとは明記していない）。

拒否したときの影響は、ほとんどの運営が説明していない。OpenAI は、ChatGPT-User は検索に表示するかどうかの判断には使わないと書いている。

ブラウザを操作する型のエージェントには、robots.txt のトークンが公表されていないものがある。ChatGPT Work の Cloud browser について、OpenAI が示しているのは Web Bot Auth の署名と CDN ごとの識別名だけ。robots.txt のトークンはない。Claude in Chrome などほかのブラウザ操作のアクセスは、サイト運営者向けの UA の説明を確認できていない。ユーザー起動の取得を本当に止めたいなら robots.txt では足りず、CDN・WAF での遮断を検討することになる。その場合、利用者が自社のページを AI に読ませて質問する機会も失う。

出典:

- Google（英語版の最終更新日 2026-08-19）: `https://developers.google.com/crawling/docs/crawlers-fetchers/google-user-triggered-fetchers`
- OpenAI: `https://developers.openai.com/api/docs/bots`、`https://help.openai.com/en/articles/11845367-chatgpt-works-cloud-browser-allowlisting`
- Anthropic（2026-04-07 更新）: `https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler`
- Meta（2026-05-21 更新）: `https://developers.facebook.com/documentation/sharing/webmasters/web-crawlers`
- Amazon: `https://developer.amazon.com/amazonbot`
- Mistral AI: `https://docs.mistral.ai/robots`
- Perplexity: `https://docs.perplexity.ai/docs/resources/perplexity-crawlers`

### CDN・WAF の確認（UA を偽装しない）

robots.txt で許可していても、CDN・WAF がクローラーを遮断していれば取得されない。Google も AI 機能のページで、robots.txt と、CDN やホスティングの設定の両方でクロールを許可しておくよう書いている。逆に、robots.txt を直しても CDN の一括設定が別に動いていることがある。

CDN の設定が robots.txt と食い違う例として、Cloudflare の資料（2026-09-26 に確認）には次の2つがある。

- AI ボットの方針: Search・Agent・Training の分類ごとに、すべてのページで遮断・広告のあるページで遮断・許可を選べる（2026-07-01 更新）。2026-09-15 から新しいドメインの既定値を変え、Training と Agent に分類されたボットを広告のあるページで遮断し、Search は許可すると予告している。確認した時点でもページは予告の書き方のままで、実際に切り替わったかは確認できていない。Search と Training を兼ねる混合用途のクローラーは Training に分類され、学習を止める設定（従来の Block AI bots を含む）ではすべて遮断される。「Search は許可」でも、検索に使われるクローラーの一部は止まる。
- 管理された robots.txt: 有効にすると、既知の AI クローラー向けの Disallow を元の robots.txt の前に付け足して返し、robots.txt がなければ作って返す（2026-08-03 更新）。サーバー上のファイルと配信される内容が違うので、判定は `--url` で配信されている robots.txt に対して行う。

確かめる手順:

1. 管理画面を見る: ボット管理、AI ボットの一括設定、WAF のカスタムルール、レート制限、robots.txt を自動で作る・書き足す機能を開き、それぞれ有効・無効・未確認を記録する。項目の名前は CDN ごとに違い、変わることもあるので、利用中の CDN の公式ドキュメントで確かめる。
2. 配信されている robots.txt を判定する: 手順2の `--url` の結果を使う。ブラウザで開いた内容と比べ、違えば CDN が UA によって応答を変えている可能性がある。
3. ログで実際の応答を確かめる: CDN かサーバーのアクセスログから、クローラーの UA ごとに応答コード（200、403、429、503 など）を数える。UA は偽装されうるので、送信元 IP が運営の公開する IP 範囲に入るものだけを数える。IP 範囲の場所は `data/ai-crawlers.csv` の source_url のページに書かれている（例: OpenAI の `https://openai.com/gptbot.json`、Anthropic の `https://claude.com/crawling/bots.json`）。CDN のボット分析の画面を使うときは、何で識別しているかを確かめる。Cloudflare の AI Crawl Control は、無料プランでは UA で AI クローラーを識別すると書いている（2026-07-28 更新）。
4. Google については、Search Console の URL 検査で［公開 URL をテスト］を使うと、Google からの実際の取得の結果（クロールの許可、ページの取得）を見られる。取得に使われるのは Google-InspectionTool で、CDN が Googlebot と同じに扱うとは限らないので、ここで取得できても Googlebot が通る証明にはならない。遮断の手がかりとして使う。
5. 設定が意図と違えば CDN 側で直し、数日後にもう一度ログで確かめる。

AI クローラーの UA を名乗ったリクエストで確かめない理由は2つある。

- 結果が本物のクローラーの扱いを表さない。CDN は UA だけで本物のクローラーと判断しない。Cloudflare は検証済みのボットを、Web Bot Auth の署名、公開された IP 一覧と固定の UA、逆引き DNS のどれかで確かめる（2026-07-01 更新）。Bing、Common Crawl、You.com も、UA は偽装されやすいので IP や署名で確かめるよう勧めている。自分の PC から GPTBot を名乗っても、CDN から見れば「GPTBot を名乗る別のもの」になる。偽物として遮断されれば「遮断されている」と誤って結論し、未検証のボットを通す設定なら「通る」と誤って結論する。
- ログと統計を汚す。UA を名乗った自分のリクエストが、そのクローラーのアクセスとして記録に残る。Cloudflare の AI Crawl Control は無料プランでは UA で識別するので、自分の試験がそのままクローラーの要求数に数えられ、手順3のログの確認を狂わせる。`ai_robots_check.py` が独自の UA を使うのもこのためで、手作業の確認でも AI クローラーを名乗らない。

CDN で IP ごと遮断する方法にも注意がいる。クローラーが robots.txt を読めなくなるので、Anthropic と Cohere は、IP での遮断は確実なオプトアウトにならないことがあると書いている。Bing の `noindex` も、クロールできないと読まれない。

出典（2026-09-26 に確認）:

- Google の AI 機能とウェブサイト: `https://developers.google.com/search/docs/appearance/ai-features`
- Google の URL 検査: `https://support.google.com/webmasters/answer/9012289?hl=ja`
- Google の共通クローラー（Google-InspectionTool）: `https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers`
- Cloudflare: `https://developers.cloudflare.com/bots/additional-configurations/block-ai-bots/`、`https://developers.cloudflare.com/bots/additional-configurations/managed-robots-txt/`、`https://developers.cloudflare.com/bots/concepts/bot/verified-bots/`、`https://developers.cloudflare.com/ai-crawl-control/features/manage-ai-crawlers/`
- Bing: `https://www.bing.com/webmasters/help/which-crawlers-does-bing-use-8c184ec0`
- Common Crawl: `https://commoncrawl.org/ccbot`
- You.com: `https://you.com/docs/youbot`
- Anthropic: 上の「ユーザー起動のフェッチャー」の出典と同じ記事
- Cohere: `https://docs.cohere.com/docs/cohere-web-crawlers`

### クローラー方針のトレードオフ（事業判断）

表の分類は `data/ai-crawlers.csv` の category の値。どのトークンがどの分類かは CSV を見る。

| 方針 | 設定の例 | 得るもの | 失うもの・リスク |
|---|---|---|---|
| A. すべて許可 | AI クローラー向けの記述を書かない。CDN の AI ボットの一括遮断も無効にする | AI 検索・対話型の AI で参照・引用される機会を残す | 内容が各社のモデルの学習に使われうる |
| B. 学習用だけ拒否 | category が `training`・`control`・`dataset` の行を拒否し、`search` の行は許可する | 引用の機会を残しながら、学習への利用を減らす | 学習用のトークンの一部は、拒否すると学習以外の用途も止まる。止まらない AI の用途もある（下の「方針 B を選ぶときの注意」） |
| C. AI 関連をすべて拒否 | B に加えて `search` の行も拒否する | AI による利用を最小にする | ChatGPT の検索回答などに出なくなる。それでも Google の AI 機能、Copilot、ユーザー起動のフェッチャーは robots.txt では止まらないことがある（下の「方針 C を選ぶときの注意」） |
| D. Google の AI 機能だけ除外 | Search Console の検索の生成 AI 設定で「除外する」を選ぶ | 通常の検索結果を保ったまま、AI による概要・AI モードでの表示とグラウンディングを止める | これらの機能からの表示と流入がなくなる。学習には影響しない（学習も減らすなら Google-Extended を組み合わせる） |
| D の補助: ページ単位で絞る | ページに `nosnippet` か `max-snippet`、ページの一部に `data-nosnippet` を付ける | `nosnippet` のページは、AI による概要・AI モードの直接の入力に使われない | `nosnippet` は通常の検索結果のスニペットも消す。`max-snippet` と `data-nosnippet` は、使われる量や範囲を制限するだけで、ページを AI 機能から外すものではない |

方針 B を選ぶときの注意:

- Google-Extended を拒否すると、Gemini アプリと Vertex AI のグラウンディングにも使われなくなる（「Google-Extended の記述の食い違い」）。
- Applebot-Extended を拒否しても、Siri と検索の AI による回答には使われうる。止めるには Apple 向けの `nosnippet` を使う（「Apple（Siri と検索の AI による回答）」）。
- `training` の行にも、学習以外の用途を兼ねるものがある。Amazonbot は Amazon の製品の改善、meta-externalagent はインデックスによる製品の改善にも使われる。行ごとに block_effect と purpose を読んでから、拒否に入れるかを決める。
- 拒否の効果は今後集める内容に対するもので、すでに集めたデータの扱いは説明されていない（ClaudeBot、CCBot など）。

方針 C を選ぶときの注意:

- OAI-SearchBot を拒否したサイトは ChatGPT の検索回答に表示されなくなるが、ナビゲーション用のリンクとしては表示されうる（OpenAI のクローラー一覧 `https://developers.openai.com/api/docs/bots`、2026-09-26 に確認）。
- Google の AI 機能は Googlebot のインデックスを使うので、robots.txt では止まらない。方針 D を使う。
- Copilot には専用のトークンがない。Bing のメタタグを使う（「Bing（Copilot）」）。
- `user` の行は robots.txt が適用されない場合がある（「ユーザー起動のフェッチャー」）。

そのほかの分類:

- `other` の行は、用途が学習・AI 検索・ユーザー操作・通常の検索のどれにも当たらないもので、方針 A〜D には含めない。行ごとに purpose と block_effect を読んで決める。たとえば Google-CloudVertexBot は、サイト所有者が依頼した Vertex AI Agents 構築用のクロールで、Google 検索やほかの製品には影響しないと明記されている（Google の共通クローラーのページ、2026-09-26 に確認）。OAI-AdsBot は、ChatGPT に広告を出すなら許可が必須になる（「よくある失敗」）。
- `general-search` の行（Googlebot、Bingbot、Applebot など）は通常の検索のクローラー。AI への利用を止める目的で拒否すると、通常の検索にも影響する。Googlebot 宛ての指定は Google 検索全体に効き、Bing はクロールされないページはインデックスされないと書いている。

組み合わせと決め方:

- 方針は組み合わせてよい。B と D を同時に使えば、学習への利用を減らしつつ Google の AI 機能からも外れる。
- 決める前に、観測の結果（03-observation.md、04-citation-gap.md）で AI の回答に自社が引用されているか、AI 経由の流入が CV につながっているか（07-platform-reports.md）、学習に使われると損失の大きい資産（有料記事、会員限定の内容、独自のデータ）があるかを確かめる。材料がなければ `[要追加: ○○]` として、選択肢だけを示す。
- robots.txt は各社が尊重すると表明している取り決めで、強制力はない。Cloudflare の資料も、順守は任意で、技術的にアクセスを止めるものではないと書いている。強制したいなら CDN・WAF で遮断することになるが、上の「CDN・WAF の確認」の注意がそのまま当てはまる。

### robots.txt の記述例（方針 B）

前半のグループが学習用のクローラーの拒否、`User-agent: *` のグループは既存のルールの例。ここに挙げたのは主なトークンだけなので、実際には `data/ai-crawlers.csv` の category が `training`・`control`・`dataset` の行から選ぶ。Amazonbot のように用途が混ざる行は、purpose を読んでから入れるかを決める。

```text
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
User-agent: CCBot
Disallow: /

User-agent: *
Disallow: /admin/
```

書くときの落とし穴:

- 特定のクローラー向けのグループを作ると、そのクローラーは `User-agent: *` のグループを読まなくなる。RFC 9309 は「一致するグループがないときだけ `*` のグループに従う」とし、Google も特定のグループと `*` のグループは合わせないと書いている。検索用のクローラー向けにグループを足すときは、`*` に書いている Disallow（管理画面など）もそのグループに書く。`ai_robots_check.py` はこの抜けを警告する。
- 指定のないクローラーが、ほかのクローラー向けの指定に従うことがある。Applebot は、Applebot の指定がなく Googlebot の指定があれば Googlebot の指定に従う。Amzn-SearchBot も、指定がなくほかの検索用のボットを許可していれば、その指定に従う。Googlebot 向けに書いた規則が Apple や Amazon にも効くことを前提に書く。
- トークンは `data/ai-crawlers.csv` から写す。公式ページの表から写すと、ハイフンが別の文字になっていることがある（Perplexity のクローラー一覧の表の見出しでは、Perplexity-User のハイフンが U+2011 だった。2026-09-26 に確認）。
- 変更が反映されるまでの時間は運営ごとに違う。Google は robots.txt を通常24時間までキャッシュする。OpenAI は OAI-SearchBot の変更の反映に約24時間、Amazon は約24時間、DuckDuckGo は DuckAssistBot で72時間と書いている。Bing は robots.txt を少なくとも数時間キャッシュする。判定の直後に効果を確かめようとしない。
- 変更後は `ai_robots_check.py` を再実行して判定を保存し、変更日と理由を記録する。

出典（2026-09-26 に確認）:

- RFC 9309: `https://www.rfc-editor.org/rfc/rfc9309`
- Google の robots.txt の仕様: `https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec`
- Apple: `https://support.apple.com/en-us/119829`
- Amazon: `https://developer.amazon.com/amazonbot`
- OpenAI: `https://developers.openai.com/api/docs/bots`
- DuckDuckGo: `https://duckduckgo.com/duckduckgo-help-pages/results/duckassistbot`
- Bing: `https://www.bing.com/webmasters/help/how-to-create-a-robots-txt-file-cb7c31ec`
- Perplexity: `https://docs.perplexity.ai/docs/resources/perplexity-crawlers`

### 再確認の手順（確認日から3か月）

クローラーの名前、用途、資料の置き場所は、数か月単位で変わる。2026年だけでも次の変更があった。

- 3月20日: Google がユーザー起動のフェッチャー Google-Agent を資料に加えた。
- 7月16日: NotebookLM が Gemini Notebook になり、UA が Google-GeminiNotebook に変わった。
- 8月31日: Google が検索の生成 AI 設定を全サイトへ提供した。

OpenAI のクローラー一覧も、`platform.openai.com/docs/bots` から `developers.openai.com/api/docs/bots` へ移っている。旧 URL は転送されるが、移った時期は確認できていない。

1. `data/ai-crawlers.csv` の各行の source_url を開き、purpose、robots_control、block_effect が今も正しいかを確かめる。更新日が表示されている資料は、その日付も控える。
2. 各社の資料に新しいトークンが載っていないかを見る。Google はクローラーの資料の変更履歴（`https://developers.google.com/crawling/docs/changelog`）を公開している。Anthropic の記事の末尾には、大きな変更の通知を受け取る登録フォームがある。
3. この手順書の「robots.txt ではない制御」「Google-Extended の記述の食い違い」「CDN・WAF の確認」に書いた仕様も、出典の URL で確かめる。
4. 変わっていた行は、スキルのフォルダの一覧を直接書き換えず、`ai-search/ai-crawlers.csv` にコピーして直し、`--crawlers` で使う（スキルのフォルダは読み取り専用の環境があるため）。`ai-search/` がまだなければ、作ってよいかを先にユーザーに確かめる。変更前と変更後、出典の URL、確認日を報告に書く。
5. 確認できなかった行は推測で埋めず、報告に `[要確認: ○○（確認できなかった理由）]` と書く。

出典: Google の変更履歴（`https://developers.google.com/crawling/docs/changelog`）、OpenAI（`https://developers.openai.com/api/docs/bots`）、Anthropic（上の出典と同じ記事）。

## 4. そのまま使えるプロンプト

```text
ai-search-operator の 05-crawler-policy.md に従って、架空珈琲（架空のサイト https://kakuu-coffee.example）の AI クローラーの方針を整理してください。
- robots.txt: ai_robots_check.py を --url で実行してよい / {実行結果を貼る}
- 検索の生成 AI 設定: {含める / 除外 / 親から継承 / 未確認}
- CDN・WAF: {使っている CDN と、ボット対策の設定 / 未確認}
- 事業の状況: {例: 記事で集客して焙煎豆の定期便につなげている / 有料のレシピ記事がある}
- 気にしていること: {例: 学習には使われたくないが、ChatGPT の検索回答には出たい}
data/ai-crawlers.csv の確認日が3か月以上前なら、各社の公式資料で再確認してから判断してください。確認できなかったものは [要確認: ○○（理由）] と書いてください。
決めるのは私です。方針 A〜D ごとに得るものと失うものを並べ、推奨があれば理由を添えて1つ示し、選んだ方針の robots.txt の案を付けてください。
```

```text
05-crawler-policy.md の「CDN・WAF の確認」に沿って、{CDN の名前} で AI クローラーがどう扱われているかを確かめる手順を作ってください。
- アクセスログ: {UA・送信元 IP・応答コード・日時の抜粋 / まだない}
- 管理画面で見えている設定: {画面の項目名と値 / 未確認}
AI クローラーの UA を名乗ったリクエストで試す方法は使わないでください。ログは、送信元 IP が各社の公開する IP 範囲に入るものだけを数えてください。管理画面の項目名は、その CDN の公式ドキュメントで確かめてから書いてください。
```

```text
data/ai-crawlers.csv の各行を、source_url の公式資料で再確認してください。
- 用途（purpose）、robots.txt の扱い（robots_control）、拒否したときの影響（block_effect）が今も正しいか
- 公式資料に新しく載ったトークンがないか
変わっていた行は、変更前・変更後・出典の URL・確認日を表にしてください。確認できなかった行は推測で埋めず、[要確認: ○○] としてください。直した一覧は ai-search/ai-crawlers.csv に書き、ai_robots_check.py の --crawlers で使います。
```

## 5. 出力フォーマット

```markdown
### 結論
- 現状の方針: {A〜D / 混在}（根拠: ai_robots_check.py の判定、{YYYY-MM-DD}）
- 意図と違う設定: {なし / 例（架空）: CDN の一括遮断で OAI-SearchBot に 403 を返している}
- 決めること: {未決定の方針 / なし}

### robots.txt の判定（パス / で判定。一覧の確認日 {YYYY-MM-DD}）
- 取得の結果: {許可・拒否を判定できた / 全許可（robots.txt なし）/ 全拒否（取得できず）/ 不定（429）}（ステータス {コード}）
- 警告: {User-agent: * の Disallow が適用されないクローラー / なし}

| 分類 | 拒否 / 件数 | 拒否しているトークン | 注記 |
|---|---|---|---|
| 学習（training） | {m}/{n} | | |
| 制御用（control） | | | クロールはしない |
| 公開データセット（dataset） | | | |
| AI 検索・回答（search） | | | |
| ユーザー操作に伴う取得（user） | | | robots.txt が適用されない場合がある |
| 通常の検索（general-search） | | | |
| その他（other） | | | 方針 A〜D の対象外。行ごとに決める |

### robots.txt ではない制御と CDN・WAF
| 項目 | 状態 | 確かめた方法 |
|---|---|---|
| 検索の生成 AI 設定 | {含める / 除外 / 親から継承 / 未確認} | Search Console の［設定］→［検索の生成 AI］ |
| ページ単位の指定（noindex / nosnippet 系） | {なし / あり（URL）/ 未確認} | URL 検査、ページのソース |
| Bing のメタタグ（noarchive / nocache） | | ページのソース |
| CDN・WAF のボット対策 | {有効 / 無効 / 未確認}（設定の名前） | 管理画面、ログ（IP 範囲で確かめた件数） |

### 方針の選択肢（未決定の場合）
| 方針 | 設定 | 得るもの | 失うもの | 推奨と理由 |
|---|---|---|---|---|

### 変更案
- 変更後の robots.txt: {全文をコードブロックで示す}
- 反映の確認: 変更後に ai_robots_check.py を再実行し、ai-search/reports/robots-{YYYY-MM-DD}.md に保存する（ai-search/ がなければ、結果をこの報告に貼る）
- 記録: 変更日 {YYYY-MM-DD}、理由 {1行}、次の再確認日 {確認日 + 3か月}
- 未確認の点: {[要確認: ○○] の一覧}
```

## 6. よくある失敗

- Google-Extended や Googlebot の拒否で AI による概要を止めようとする: Google-Extended は Google 検索への掲載に影響しないので外れない。Googlebot を拒否すると通常の検索結果からも消える。外すには検索の生成 AI 設定を使う。ページ単位なら `nosnippet` で AI 機能の直接の入力から外せるが、通常の検索結果のスニペットも消える。`max-snippet` と `data-nosnippet` は量や範囲を制限するだけで、ページを外すことにはならない。
- Google-Extended を拒否すれば検索の AI の学習に使われない、と断定する: 公式資料の書き方がそろっていない。`[要確認: ○○]` を付けて、確認できている範囲だけを書く。
- 特定のクローラーのグループを追加して、既存の制限が外れる: そのクローラーは `User-agent: *` のグループを読まなくなる。必要な Disallow を追加したグループにも書き、`ai_robots_check.py` の警告で確かめる。
- Googlebot 向けのグループが Applebot にも効くことを見落とす: Applebot は、自分の指定がなければ Googlebot の指定に従う。Apple だけ扱いを変えたいなら Applebot のグループを書く。
- ユーザー起動のフェッチャーを robots.txt で止めたつもりになる: Google、Meta などは一般に無視する・迂回することがあると説明している。判定の note 列を読み、止まる保証がないことを報告に書く。
- AI クローラーの UA を名乗って CDN の設定を確かめる: CDN は IP や署名で本物を見分けるので、結果が本物の扱いを表さない。管理画面とログ（送信元 IP で確かめたもの）で確かめる。
- robots.txt に 403 や 429 を返しているのに気づかない: 403 は RFC 9309 と Google では「robots.txt なし」の全許可になり、robots.txt に書いた拒否が読まれない。429 は扱いがクローラーによって分かれる。robots.txt は、ボット対策とレート制限の対象から外す。
- サーバー上の robots.txt だけを見て判断する: CDN やプラグインが書き足して配信していることがある。`--url` で配信されている内容を判定する。
- AI ボットの一括遮断や IP での遮断で、止めたくない用途まで止める: `training` の行にも学習以外の用途を兼ねるものがあり、CDN の一括設定は robots.txt と別に動く。ChatGPT に広告を出しているなら、広告のランディングページの審査に OAI-AdsBot の許可が必須だと OpenAI は書いている（`https://help.openai.com/en/articles/20001243-advertiser-guidance-for-allowing-openai-web-crawlers`、2026-09-26 に確認）。IP での遮断は robots.txt も読めなくするので、確実なオプトアウトにならないことがある。
- 確認日から3か月以上たった一覧で判断する: 名前・用途・資料の場所は変わる。手順8で再確認してから判定する。
