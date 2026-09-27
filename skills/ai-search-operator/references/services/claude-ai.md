# Claude（`claude`）の観測条件

Claude で観測するときの条件だけを書いた。ラウンドの決まり、回答ファイルの書き方、status と sources_status、集計といった共通の手順は [03-observation.md](../03-observation.md) にあり、このファイルと合わせて読む。

事実は、2026-09-26 に各社の公式資料で確認できた範囲に限る。本文の「資料1」などは、末尾の「資料」の番号を指す。確認日から3か月以上たっていたら、各社のヘルプで確かめ直す。

## 公式資料で確認できたこと

| 項目 | 2026-09-26 に公式資料で確認できたこと |
|---|---|
| ログインなし | アカウントの作成には対応地域の電話番号による SMS 認証が要り、省略できない（資料1）。ログインせずに使えるという公式の記述は見つからなかった |
| ウェブ検索（従来の画面） | 入力欄の左下の「+」から「Web search」を選んでオンにする。無料プランでも使える（資料2・3） |
| ウェブ検索（新しい画面） | 2026年9月16日に発表された新しい画面には検索のトグルがなく、Claude が役立つと判断したときに検索する。新しい画面が届く時期はアカウントごとに違う（資料4・9） |
| 検索の指示 | 確実に検索させるには、プロンプトに「Search the web」などを入れるよう案内されている（資料3） |
| シークレットチャット | 全プランで使え、既存のメモリを使わず、履歴にも残らない。ただし、プロフィールの情報（personal preferences など）には Claude がアクセスできる（資料5） |
| 指示の設定 | 「Instructions for Claude」はすべての会話に適用される（資料6） |
| 出典の表示 | ウェブ検索を使った応答には、出典の引用（citations）とソースへのリンクが付くと説明されている。見た目の形は説明されていない（資料3） |
| 地域・言語 | 表示言語の設定と関係なく、話しかけた言語で応答する（資料7）。地域に合わせた結果を求められたときは、IP アドレスから推定した位置を使うことがある（資料3） |
| 規約の要点 | Consumer Terms（2025年10月8日発効）は、規約で認められた範囲を超えるクロール・スクレイピング・収集と、API キー経由などを除く、ボットやスクリプトなど自動化された手段でのアクセスを禁じている（資料8） |

## 観測するときの手順

- ログインし、プロジェクトの外で、右上のゴーストアイコンからシークレットチャットを始める。`login` は `あり（記憶オフ）` にする。
- 観測の間は「Instructions for Claude」を空にする。
- どちらの画面で尋ねたかを brief.md に書く。`mode` は、従来の画面で Web search をオンにしたら `検索あり`、新しい画面では `自動` にする。
- プロンプトに検索の指示は足さない。足すと他のサービスと質問文がそろわなくなる。足すなら、足す文を brief.md に書いて全回答で同じにし、`mode` を `検索指示あり` にする。
- シークレットチャットは履歴に残らないので、閉じる前に回答と出典を写す。

## 最初の観測で確かめること

- シークレットチャットの中でウェブ検索のトグルを使えるか（新しい画面でも、シークレットチャットは従来の画面で開く、と資料4・5にある）
- 出典がどんな形で、どういう順に表示されるか
- コピーボタンで出典の URL が残るか。共有リンクに出典が残るか

## 資料

1. https://support.claude.com/en/articles/8287232-verify-your-phone-number
2. https://claude.com/pricing
3. https://support.claude.com/en/articles/10684626-enable-and-use-web-search
4. https://support.claude.com/en/articles/16761823-claude-cowork-and-chat-are-one-claude
5. https://support.claude.com/en/articles/12260368-use-incognito-chats
6. https://support.claude.com/en/articles/10185728-understanding-claude-s-personalization-features
7. https://support.claude.com/en/articles/10769299-how-to-use-claude-in-your-preferred-language
8. https://www.anthropic.com/legal/consumer-terms
9. https://claude.com/blog/cowork-is-now-claude
