# ai-search-operator

[![test](https://github.com/indiabiyori/ai-search-operator/actions/workflows/test.yml/badge.svg)](https://github.com/indiabiyori/ai-search-operator/actions/workflows/test.yml)

English: [README.en.md](README.en.md)

AI 検索で自社がどう扱われているかを、Claude Code で観測するためのスキルです。ChatGPT や Google の AI モードなどの回答に、自社の名前が出るか（言及）、自社のページが出典に挙がるか（引用）を記録し、手を打った結果を件数で判定します。回答はユーザーが画面で尋ねて貼り付け、言及と引用の判定、集計、前後の比較はスクリプトが受け持ちます。自分用に作ったものを、そのまま公開しています。

AI の回答は、同じ質問でも尋ねるたびに変わります。昨日の回答に出ていた社名が、今日は消えていることもあります。1回見ただけでは、自社の名前が出たのが施策のおかげなのか、たまたまなのかを区別できません。そこで、決めた質問を同じ条件で繰り返し尋ね、回答を1件ずつファイルに残すことにしました。質問をすべて、決めたサービスで決めた回数ずつ尋ねる1回分の観測を「ラウンド」と呼び、率はいつも「何件中何件」の形で出します。

中身は、Claude が作業ごとに読む手順書8本、記入用のひな形5つ、AI クローラー34件の一覧です。付属のスクリプトは4本で、どれも Python の標準ライブラリだけで動き、659件のテストで挙動を確かめています。

自社や担当先のブランドについて、AI の回答を継続して追いたい Web 担当者、制作会社、フリーランスを想定しています。スクリプトは Claude が実行するので、Python の知識は要りません。キーワード調査や記事の執筆のような通常の SEO は、姉妹スキルの [seo-operator](https://github.com/indiabiyori/seo-operator) が受け持ちます。使い始めるだけなら「インストール」と「最初の一歩」を読めば足ります。ほかの節は、必要になったときに開いてください。

## 観測していない率は出さず、件数が足りなければ「判定不能」と返します

AI に「うちの会社は AI 検索でどのくらい言及されている？」と聞くと、記録を1件も見ていないのに、もっともらしい率で答えることがあります。ai-search-operator は SKILL.md の決まりの1番目で、記録した回答とレポートの実測にない数字を出すことを禁じています。

たとえば観測の記録がないまま言及率を聞かれたら、「言及率は20%前後です」とは答えず、次のように返すよう指示しています。

> 観測の記録がないので、言及率は出せません。尋ねる質問を prompts.csv に書き、new_round.py で回答ファイルのひな形を作ります。ChatGPT で毎回新しい会話を開いて各3回尋ね、回答と出典を貼ってください（[要追加: 2026-10-01 のラウンドの観測]）。

`[要追加: ○○]` は、手元にないデータを入れる場所の印です。推定した内容や、確かめが要る箇所には `[要確認: ○○]` を付けます。どちらの印も、データが入るか確認が取れるまでは、確定した事実として扱いません。

変更の前と後を比べるときも、率が上がって見えるだけでは改善と呼びません。次の表は、架空の回答24件（4問 × 1サービス × 3回を、変更の前と後で1ラウンドずつ）を compare_runs.py にかけた出力の一部です（列を一部省いています）。

| 指標 | 前 | 後 | 上がった | 下がった | 同じ | 判定 | 理由 |
|---|---|---|---|---|---|---|---|
| 自社の引用 | 4/12（33.3%） | 7/12（58.3%） | 3 | 0 | 1 | 判定不能（探索的） | 差が出たプロンプトが 3 件（判定には 6 件以上が必要） |

自社の引用は 4/12 から 7/12 に増えましたが、率が動いたプロンプトは3問しかありません。判定では、プロンプトごとに前後の率を比べ、上がった数と下がった数の偏りを両側の符号検定で確かめます。率が動いたのが5問以下では、全部が同じ向きに動いても p が 0.05 を下回りません。p は、変化がなくても偶然これだけ偏る確率です。下回るのは早くても、6問すべてが同じ向きに動いたとき（p = 0.03125）です。判定の結果は、改善シグナル、悪化シグナル、明確な変化を検出せず、判定不能の4つのどれかです。改善シグナルが出ても、施策が原因だとは断定しません。表の「探索的」は、変更の前に実験の記録で決めておいた比較ではない、という印です。

ほかに、次の決まりも守らせています。

- 率は `k/n（xx.x%）` の形で書き、どのラウンドの、どの条件の組（サービス、画面か API か、ログイン状態、モード、地域、言語）かを添える。条件の違う回答は合算しない
- AI の回答が出なかった、エラーになった、まだ貼っていない、といった回答を「言及なし」として数えない
- 独自の「AI 可視性スコア」や、推定の引用シェアを作らない
- llms.txt や構造化データで「引用される」「○%上がる」と約束しない
- プロンプトの言い回しごとにページを量産する、AI に向けた隠しテキストを埋め込む、といった操作に当たる施策は、はっきり指摘して代案を出す

## インストール

Claude Code ならプラグインとして入れるのがいちばん手軽です。なお、Windows ではまだ一度も動かしていません。

### Claude Code にプラグインとして入れる

ターミナルで次の2行を実行します。

```bash
claude plugin marketplace add indiabiyori/ai-search-operator
claude plugin install ai-search-operator@ai-search-operator
```

`claude plugin list` を実行し、`ai-search-operator@ai-search-operator` が enabled と表示されれば入っています。Claude Code の入力欄からは、`/plugin` コマンドでも入れられます。

### Claude Code に手でフォルダを置く

リポジトリを取得し、`skills/ai-search-operator` フォルダを `~/.claude/skills/` の下に置きます。

```bash
git clone https://github.com/indiabiyori/ai-search-operator.git
mkdir -p ~/.claude/skills
cp -R ai-search-operator/skills/ai-search-operator ~/.claude/skills/
ls ~/.claude/skills/ai-search-operator/SKILL.md   # このパスが表示されれば完了
```

git を使わない場合は、GitHub のリポジトリのページで Code → Download ZIP を選んで展開し、中の `skills/ai-search-operator` フォルダを同じ場所に置いてください。

### claude.ai（Web・Cowork）では zip をアップロードする

1. 上と同じ方法でリポジトリを取得し、`skills/ai-search-operator` フォルダを zip に圧縮する。zip を開いたとき、一番上に `ai-search-operator` フォルダが来る形にする
2. Settings → Capabilities で「Code execution and file creation」を有効にする（Team・Enterprise プランでは組織の設定で管理者が有効にする）
3. Customize → Skills の「+」→「+ Create skill」→「Upload a skill」で zip を選ぶ

ネットワークが制限された環境では、`ai_robots_check.py --url` が対象のサイトに届かないことがあります。その場合は、ブラウザで開いた robots.txt の内容を Claude に渡してください。Claude がファイルに保存し、`--file` で判定します。

### Python は 3.9 以上があれば足ります

Python が要るのは、回答ファイルのひな形づくり、集計と前後の比較、robots.txt の判定です。プロンプトセットの設計や、Search Console・Bing・GA4 のレポートの読み方は、Python がなくても頼めます。

スクリプトは Python 3.9 以上の標準ライブラリだけで動きます。uv も pip も要らず、入れるパッケージはありません。macOS では、コマンドライン・デベロッパ・ツールに含まれる `/usr/bin/python3`（3.9）でそのまま動きます。

```bash
python3 --version   # 3.9 以上と表示されれば準備は済んでいる
```

### 更新と削除

プラグインで入れた場合は、次の2行で更新し、Claude Code を再起動します。

```bash
claude plugin marketplace update ai-search-operator
claude plugin update ai-search-operator@ai-search-operator
```

削除するときは `claude plugin uninstall ai-search-operator@ai-search-operator` を実行します。手で置いた場合は、`~/.claude/skills/ai-search-operator` を新しいものに置き換えるか、削除してください。

## 最初の一歩: 表記ゆれと質問を決めてから、1ラウンド目を観測する

サイトごとに作業用のフォルダを1つ作り、そこで Claude Code を開いて、次のように頼みます。

```
ai-search-operator で初回セットアップをして
```

Claude は作業フォルダに `ai-search/` を作り、`brief.md`、`entities.csv`、`prompts.csv` をひな形からコピーします。brief.md には、事業と目標、正しい事実の一覧（値ごとに出典と確認日）、観測の条件の決まりを書きます。entities.csv は自社と競合の表記ゆれ・除外語・ドメインの一覧です。スクリプトはこの一覧だけを頼りに、言及と引用を数えます。中黒や法人格、空白の有無の違いは自動ではそろえないので、「架空珈琲」「カクウ・コーヒー」「kakuu coffee」（例は架空）のような書き方を1つずつ並べておきます。

どのファイルも、自分で書き込むか、Claude の質問（1回5問以内）に答えて埋めるかを選べます。答えなかった項目は `[要追加]` のまま残ります。seo-operator の `seo/site-brief.md` があれば、事業と CV の定義はそちらから読みます。競合は、最初の観測で AI が実際に挙げた企業から選ぶので、この時点で決めきらなくてかまいません。

次に、AI に尋ねる質問の集合（プロンプトセット）を決めます。

```
顧客が AI に尋ねそうな質問で、プロンプトセットを作って
```

質問は、認知・比較・購入・サポートの段階と、社名を含むかどうか（指名・非指名）の組み合わせで並べ、Claude が prompts.csv に書きます。Search Console のクエリや問い合わせの内容を渡せば、質問の出どころに使います。一度観測に使った質問の文は直さず、言い回しを変えるときは新しい ID にします。前後の比較は、同じ ID の質問どうしでしかできないためです。

質問が決まったら、1ラウンド目の観測に入ります。

```
1ラウンド目の観測を始めたい。ChatGPT と Google の AI モードで、各3回
```

まず new_round.py が、質問 × サービス × 回数の数だけ回答ファイルのひな形を作ります（`ai-search/answers/<ラウンド>/<サービス>/<プロンプトID>-<回数>.md`）。ここからは手作業です。毎回新しい会話を開き、ファイルの `prompt` の文を尋ねて、回答を `## 回答` の下に、出典の URL を `## 出典` の下に貼ります。3回は2日以上に分けて尋ねます。AI の回答が出なかったときやエラーのときは、空のままにせず `status` に書いてください。

貼り終えて「集計して」と頼むと、Claude が normalize_observations.py と `compare_runs.py --period` を実行し、条件の組ごとの言及率・引用率を k/n で報告します。1ラウンドの集計は現状の把握までです。施策の効果を判定するには、変更の前と後のラウンドを、事前に決めた条件でそろえる必要があります（手順書 [06-experiments.md](skills/ai-search-operator/references/06-experiments.md)）。

robots.txt の判定やクローラーの方針の相談は、セットアップなしでも進められます。ただし事業の目標がわからないうちは、施策の優先度は暫定になります。

## 頼めること

| やりたいこと | スキルがすること |
|---|---|
| 今の言及率・引用率を知りたい | 回答ファイルを CSV にし、条件の組ごとに言及率・引用率・誤った説明の率を k/n で出す。競合ごとの言及と引用、出典の並び順の分布、entities.csv にない出典のホスト（競合の追加候補）も一覧にする |
| 何を AI に尋ねて調べるか決めたい | 段階と指名・非指名の組み合わせで、プロンプトセットを作る。質問の出どころは Search Console のクエリ、問い合わせ、営業に届く質問、Bing のグラウンディング クエリ（AI が回答の材料を探すときに使った語句） |
| 競合ばかり引用される | 競合や第三者が引用され、自社が引用されないプロンプトを抜き出す。引用されたページを種類（公式、比較メディア、レビュー、Q&A など）で分け、自社のページに足りない情報を仮説として挙げる |
| AI が自社を間違って説明する | 回答の正誤を brief.md の事実と照らして Claude が下書きし、人が確かめる。誤りを古い情報・他社との混同・存在しない商品や機能・誤った数値に分け、訂正の経路（公式情報の明記、登録情報の修正、AI サービスへのフィードバック）を示す。どれも効果は約束しない |
| GPTBot などを拒否すべきか決めたい | robots.txt をクローラーごとに判定し、方針 A〜D（すべて許可、学習用だけ拒否、AI 関連をすべて拒否、Google の AI 機能だけ除外）の得るものと失うものを並べる。robots.txt では止まらない経路（Search Console の検索の生成 AI 設定、ユーザー操作に伴う取得、CDN・WAF）の確かめ方も示す |
| 施策の効果を確かめたい | 施策で動きうる対象のプロンプトと、動かないはずの対照のプロンプト、判定する指標、条件の組を変更の前に決めて実験の記録に書く。前後の比較は4つの判定のどれかで出す |
| Search Console・Bing・GA4 の AI 関連のデータを読みたい | 生成 AI パフォーマンス レポート、Bing Webmaster Tools の AI Performance、GA4 の「AI アシスタント」チャネルが、それぞれ何を数えているかを整理し、足し合わせずに観測ログと並べる |
| 何から手をつけるか決めたい | 施策を影響度（1〜5）÷ 工数（1〜5）の大きい順に並べ、担当（このスキルか、seo-operator のどの手順書か）を書く |

全体の一覧は [SKILL.md](skills/ai-search-operator/SKILL.md) の振り分け表にあります。

## seo-operator との分担: ページを直す作業は渡す

ai-search-operator が受け持つのは、観測と、引用されるために足りないものの特定までです。どのプロンプトで、どの情報源が引用され、自社のどのページに何が欠けているかを突き止めたら、そこから先は seo-operator に渡します。ページの書き直しも、構造化データや内部リンクの修正も、seo-operator の手順書で扱います。

| seo-operator | ai-search-operator |
|---|---|
| クロール、インデックス、canonical | AI クローラーの許可・拒否と、引用される条件 |
| キーワード、検索意図 | AI に尋ねられる質問の集合（プロンプトセット） |
| 順位、クリック、CTR | ブランドの言及率、引用率、誤った説明の率 |
| Search Console の通常の検索データ | 生成 AI パフォーマンス レポート、Bing の AI Performance |
| 検索結果の上位ページとの比較 | AI の回答が引用している情報源との比較 |
| コンテンツ、内部リンクの改善 | 引用ギャップ、誤った説明、エンティティ情報の改善点の特定 |
| SEO 施策の効果測定 | 複数の AI サービスでの繰り返しの観測と判定 |

渡すときは、対象 URL、足りないもの、根拠（どのプロンプトのどの回答か）を書き、渡す先を seo-operator の手順書の名前で示します。seo-operator を入れていない環境でも、同じ内容を箇条書きで示すだけにし、SEO の作業手順をこちらで書き直すことはしません。逆向きに、seo-operator の `seo/site-brief.md`（事業と CV の定義）と Search Console のクエリ（プロンプトの候補）は、このスキルが読みます。

seo-operator 1.1.0 にも、AI 検索での引用対策を扱う手順書（09-ai-search.md）があります。両方を入れていると、同じ依頼でどちらのスキルが呼ばれるかが分かれることがあるので、観測や判定を頼むときは「ai-search-operator で」と名前を添えてください。

## 付属スクリプトは4本。どれも標準ライブラリだけで動く

| スクリプト | 読むもの | 出すもの |
|---|---|---|
| `new_round.py` | prompts.csv（active が yes の行か、`--prompts` で指定した ID） | 回答ファイルのひな形（プロンプト × サービス × 回数）と、1ラウンドの記録数。既存のファイルは上書きしない |
| `normalize_observations.py` | `answers/` の回答ファイル、entities.csv、prompts.csv | observations.csv（1行＝1回答）、citations.csv（1行＝1出典）、observations.run.json（スクリプトの版と、entities.csv・prompts.csv の SHA-256 など） |
| `compare_runs.py` | observations.csv と、実験の記録（任意） | Markdown の報告。`--period` はラウンドの集計、`--before` と `--after`（または `--experiment`）は前後の判定。`--details-csv` でプロンプトごとの比較表も出す |
| `ai_robots_check.py` | robots.txt（`--url` で取得するか、`--file` で手元のファイルを読む） | AI クローラーごと・パスごとの許可・拒否の表と、分類（学習、AI 検索、ユーザー操作に伴う取得など）ごとの要約 |

もう1本の `ai_search_common.py` は、4本が共通で使う処理（CSV の読み書き、表記の正規化など）で、直接は実行しません。

言及は回答の欄だけで探し、回答の中の URL は照合の前に消します。URL に含まれる社名を、言及として数えないためです。引用は、自社のドメインの URL が出典の欄か本文のリンクにあることを指し、その出典が自社についての主張を裏付けているかまでは判定しません。`utm_` などの追跡用のパラメータは外してから照合します。短縮 URL や、行き先のわからないリダイレクト用の URL は、どの会社のものとも決めずに「行き先不明」として別に数えます。

`ai_robots_check.py` は robots.txt を取得するだけで、AI クローラーの User-Agent は名乗りません（使うのは `ai-search-operator/1.0.0` で始まる User-Agent）。ユーザー名やパスワードを含む URL は取得しません。内部アドレスに解決されるホストに接続するのは、`--allow-private` を付けたときだけです（リダイレクト先も同じ）。取得に失敗したときの扱いは RFC 9309 に合わせていて、4xx は robots.txt がないものとして全許可、5xx やタイムアウトは全拒否です。429 は RFC と Google で扱いが違うため、「不定（429）」として両方の扱いを注記します。CDN・WAF の設定は調べないので、管理画面とログで確かめてください（手順は [05-crawler-policy.md](skills/ai-search-operator/references/05-crawler-policy.md)）。

自分で動かす場合は、作業フォルダ（`ai-search/` がある場所）で次のように実行します。オプションはそれぞれ `--help` で確かめられます。

```bash
python3 <スキルのフォルダ>/scripts/new_round.py --round 2026-10-01 --services chatgpt,google-ai-mode --repeats 3 --mode 検索あり
python3 <スキルのフォルダ>/scripts/normalize_observations.py
python3 <スキルのフォルダ>/scripts/compare_runs.py --period 2026-10-01
python3 <スキルのフォルダ>/scripts/ai_robots_check.py --url https://kakuu-coffee.example --paths /,/pricing/
```

`<スキルのフォルダ>` は、手で置いた場合は `~/.claude/skills/ai-search-operator` です。ラウンド名とドメインは架空の例です。

## 観測の手間は「プロンプト数 × サービス数 × 回数」で決まる

1ラウンドで記録する回答の数は、次の式で決まります。

```text
記録数 = プロンプト数 × サービス数 × 回数
```

1件ごとに新しい会話を開き、回答と出典を貼るので、手間は記録数にほぼ比例します。1件にかかる時間はサービスや回答の長さで変わるため、このスキルは目安の時間を決めていません。最初のラウンドで測って brief.md に書いておくと、次のラウンドの規模を決めやすくなります。

サービスを増やすと記録数は増えますが、集計は条件の組ごとに分かれるので、1つの組の件数は増えません。前後の比較で判定の力を決めるのも、回答の件数よりプロンプトの数です。実験をするなら、1サービス・1モードに絞ってプロンプトを増やすほうが判定しやすくなります（規模の決め方は [02-prompt-set.md](skills/ai-search-operator/references/02-prompt-set.md)）。

## AI サービスの回答は自動で集めない

ChatGPT、Claude、Copilot の利用規約は、ボットやスクレイパーなどの自動の手段による取得を禁じています。Google も、robots.txt などに反する自動の手段でのアクセスを禁じています。その robots.txt は、www.google.com では `/search` を、gemini.google.com では `/app/` と `/chat/` を拒否しています。このスキルは画面の自動操作もスクレイピングもせず、ユーザーが画面で尋ねて貼り付けた回答だけを扱います。自動で取った回答が、人が画面で見る回答と同じになる保証がないことも、手作業にした理由です。

### Perplexity は、観測の対象にするかを自分で決めてください

Perplexity の[利用規約](https://www.perplexity.ai/hub/legal/terms-of-service)の 5.2(i) は、自動の手段による監視・抽出・コピー・収集に加えて、同じ目的で手作業を行うことも禁じています。5.2(a) は、サービスで得た情報のコピーも禁じています。画面で尋ねて回答を貼るこのスキルのやり方でも、規約に触れるおそれがあります。

そのため、Perplexity はスキルの既定の例に入れていません。`new_round.py` はサービスの値として `perplexity` を受け付けますが、観測の対象に入れるかは、規約を読んだうえで利用者が判断してください。各社の規約は 2026-09-26 に確かめた内容で、詳しくは手順書 [03-observation.md](skills/ai-search-operator/references/03-observation.md) の付録にあります。

## 動作環境とテスト

テスト659件は、2026-09-27 に macOS の5つの Python（3.9.6 の `/usr/bin/python3`、3.9.25、3.11.15、3.13.13、3.14.7）ですべて通りました。GitHub Actions でも、main への push と pull request のたびに、Ubuntu 24.04 の Python 3.9 と 3.13 で同じテストを回します。Python 3.10 と 3.12、Windows では、まだ動かしていません。

入れておくだけなら、毎回のセッションに加わるのはスキルの説明文（日本語と英語で約890字）だけです。`claude plugin details` の推定では約490トークンですが、日本語を含むため、実際にはこれより多くなることがあります。依頼したときは、SKILL.md（約11,000字）と、依頼に合った手順書（1本で約14,000〜35,000字。関係するほかの手順書は必要な節だけ）を読み込みます。

テストの実行方法は [tests/README.md](tests/README.md) にあります。スキルが呼ばれる範囲と、率を観測の記録からだけ出すことを確かめる評価も、[evals/](evals/) に5件あります。モデルの利用量を使うので CI には入れず、`claude plugin eval` で手で回します。

## できないこと・まだ入れていないこと

- AI サービスの回答を自動では集められません。画面の自動操作はしない方針で、API による収集もまだ入れていません。回答ファイルの `surface` に `api` を用意してあるのは、あとで API の結果も同じ CSV に入れられるようにするためです。
- Search Console の生成 AI パフォーマンス レポートと、Bing の AI Performance のエクスポートを読むスクリプトはまだありません。実物のエクスポートで列名や文字コードを確かめてから追加します。それまでは、手順書 [07-platform-reports.md](skills/ai-search-operator/references/07-platform-reports.md) にある、画面とエクスポートを手で読む手順を使います。
- 回答の内容が正しいかは、スクリプトでは判定しません。Claude が下書きし、人が確かめた回答だけを、誤った説明の率に数えます。
- 日本語のサイト・ブランドを前提にしています。回答の言語の既定は `ja`、地域の既定は `JP` です。
- 数字を作らないといった決まりは SKILL.md の指示で守らせているもので、スクリプトのテストは Claude の答え方を確かめていません。出どころのわからない率が出たら、「それはどのラウンドの何件中何件？」と聞き返してください。

## ライセンスと出典

MIT ライセンスです（[LICENSE](LICENSE)）。

手順書（`skills/ai-search-operator/references/`）と AI クローラーの一覧（[data/ai-crawlers.csv](skills/ai-search-operator/data/ai-crawlers.csv)）にある各社の仕様や規約の記述は、各社の公式資料を要約したものです。出典の URL と確認日を添えてあります。このうち [Google 検索セントラルのドキュメント](https://developers.google.com/search/docs?hl=ja)は、Google が [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja) で、コードサンプルを [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0) で公開しています。

不具合の報告や質問は [Issues](https://github.com/indiabiyori/ai-search-operator/issues) にお寄せください。

版 1.0.0（最終更新 2026-09-27）。手順書と AI クローラーの一覧は、2026-09-26 に各社の公式資料で確かめた内容です。
