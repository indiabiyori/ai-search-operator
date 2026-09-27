# Google の AI モード（`google-ai-mode`）と AI による概要（`google-aio`）の観測条件

Google の AI モードと AI による概要で観測するときの条件だけを書いた。ラウンドの決まり、回答ファイルの書き方、status と sources_status、集計といった共通の手順は [03-observation.md](../03-observation.md) にあり、このファイルと合わせて読む。

事実は、2026-09-26 に各社の公式資料で確認できた範囲に限る。本文の「資料1」などは、末尾の「資料」の番号を指す。確認日から3か月以上たっていたら、各社のヘルプで確かめ直す。

## 公式資料で確認できたこと

| 項目 | 2026-09-26 に公式資料で確認できたこと |
|---|---|
| ログインなし | AI による概要のヘルプは提供対象を「すべてのユーザー」とし、ログインの条件を書いていない（資料1）。AI モードのヘルプにあるログインが必要という記載は Gemini 3 Pro の節のもので、AI モード全体の条件としては書かれていない（資料2） |
| AI モードの開き方 | google.com/ai、検索結果の［AI モード］、Google アプリの AI モードのアイコンから開く（資料2） |
| AI の回答が出ない場合 | AI による概要は、システムが有用と判断したときだけ表示され、表示させる操作は案内されていない（資料3）。AI モードも、回答に十分な確信がないときは、AI の回答ではなくウェブリンクの一覧を表示することがある（資料2） |
| 追加の質問 | AI による概要の［もっと見る］から追加の質問をすると、AI モードの会話に移る（資料3） |
| パーソナライズ | ログアウト中でも検索関連のアクティビティで結果がカスタマイズされることがあり、止めるには「検索カスタマイズ」を無効にするか、プライベートに検索するよう案内されている（資料4）。ログイン中は「パーソナライズされたおすすめ表示」をオフにしても、現在地、言語、端末の種類、直近の検索の文脈は使われる（資料5） |
| 出典の表示 | 回答の本文のすぐ横にリンクが表示され、回答の末尾に次に読む先のリンクの提案が出ることがある（資料6、2026年5月6日の公式ブログ）。AI による概要と AI モードでは、回答とリンクの組み合わせが異なる場合がある（資料7） |
| 地域・言語 | 現在地は端末の位置情報、登録した住所、過去のアクティビティ、IP アドレスから推定され、どの方法で推定したかは検索結果ページの下部で確かめられる（資料8）。これは通常の検索結果の説明で、AI の回答が地域の設定で変わるかを明記した公式資料は見つからなかった |
| 規約の要点 | Google 利用規約（2026年7月30日発効）は robots.txt などに反した自動化された手段でのアクセスを禁じ（資料9）、www.google.com の robots.txt は `/search` を拒否している（資料10）。Google 検索のスパムに関するポリシーは、明示的な許可なく Google に自動でクエリを送ること（順位の確認のためのスクレイピングを含む）を機械生成トラフィックとしている（資料11） |

## 観測するときの手順

- 尋ねるたびにブラウザのプライベート ウィンドウを閉じて開き直し、ログインせずに尋ねる（`login` は `なし`）。直近の検索の文脈を持ち込まないため。
- `mode` は `検索あり` にする。
- AI による概要が表示されなかったとき、AI モードがリンクの一覧だけを表示したときは、`status` を `AI の回答なし` にする。
- `google-aio` の観測では、［もっと見る］から追加の質問をしない。
- `region` を書く前に、検索結果ページの下部の現在地を確かめる。

## 最初の観測で確かめること

- 日本でログインせずに AI モードを使えるか。プライベート ウィンドウで AI モードが動くか
- AI モードで新しい会話を始めるにはどう操作するか
- 出典のリンクが画面のどこに、どんな形で並ぶか
- コピーしたときに出典の URL が残るか

## 資料

1. https://support.google.com/websearch/answer/14901683?hl=en
2. https://support.google.com/websearch/answer/16011537?hl=ja&co=GENIE.Platform%3DDesktop （リンクの一覧を表示することがある点は英語版 https://support.google.com/websearch/answer/16011537?hl=en&co=GENIE.Platform%3DDesktop ）
3. https://support.google.com/websearch/answer/14901683?hl=ja
4. https://support.google.com/websearch/answer/17024959?hl=en
5. https://support.google.com/websearch/answer/17026260?hl=en
6. https://blog.google/products-and-platforms/products/search/explore-web-generative-ai-search/
7. https://developers.google.com/search/docs/appearance/ai-features?hl=ja
8. https://support.google.com/websearch/answer/179386?hl=en&co=GENIE.Platform%3DDesktop
9. https://policies.google.com/terms?hl=en-US
10. https://www.google.com/robots.txt
11. https://developers.google.com/search/docs/essentials/spam-policies?hl=ja
