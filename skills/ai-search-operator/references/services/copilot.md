# Copilot（`copilot`）の観測条件

Copilot で観測するときの条件だけを書いた。ラウンドの決まり、回答ファイルの書き方、status と sources_status、集計といった共通の手順は [03-observation.md](../03-observation.md) にあり、このファイルと合わせて読む。

事実は、2026-09-26 に各社の公式資料で確認できた範囲に限る。本文の「資料1」などは、末尾の「資料」の番号を指す。確認日から3か月以上たっていたら、各社のヘルプで確かめ直す。

## 公式資料で確認できたこと

| 項目 | 2026-09-26 に公式資料で確認できたこと |
|---|---|
| アカウント | Microsoft Copilot 補足使用条件（2026年8月18日発効）は、Copilot を使用するには Microsoft アカウントを持っている必要があると書いている。サインインを求める文言ではない（資料1） |
| サインインなし | サポート記事には「Sign in isn't required」とあり、サインインすると履歴などの機能が使えると書かれている（資料2）。使用条件との関係は読み方が分かれる |
| ウェブ検索 | 個人向けの Transparency Note によると、ウェブからのグラウンディングが要るかはシステムが判断する（資料3）。設定の「Web 検索」はオフにできるトグルで、毎回検索させる機能とは書かれていない（資料4） |
| 会話モード | 2025年7月の記事には会話モードの「Search」があるが（資料5）、2026年8月18日以降の新しいアプリに残っているかは確認できていない |
| メモリ | ［設定］→［個人用設定］の「保存されたメモリ」をオフにすると、新しいメモリを保存しなくなる。保存済みのメモリは消えない（資料6） |
| パーソナライズ | 「One shared experience」をオフにすると、Bing・Edge・MSN の利用状況を使ったパーソナライズが止まる。Edge 側は Edge の設定で別にオフにする（資料6） |
| 出典の表示 | ウェブにもとづく回答には、本文の下にハイパーリンク付きの引用が並ぶ（資料3）。回答の下の Sources ボタンで出典を確かめる手順は、職場・学校アカウント向けの記事にある（資料7） |
| 地域・言語 | 機能や動作は地域によって異なる場合があり（資料2）、地域を手で設定する方法は個人向けの公式資料で見つからなかった。提供されていない市場の例外に日本は含まれず、テキストの対応言語に日本語が含まれる（資料8） |
| 規約の要点 | 補足使用条件は、ボットやスクレイパーなどのツールやプログラムで Copilot にアクセスすることを禁じている（資料1）。Microsoft サービス規約は、明示的な許可がない限り、スクレイピングなどで AI サービスからデータを取り出すことを禁じている（資料9） |

## 観測するときの手順

- 補足使用条件がアカウントを持つことを求めているので、サインインして尋ねる案を既定にし、`login` を `あり（記憶オフ）` にする。
- 観測の前に「保存されたメモリ」をオフにし、保存済みのメモリを［管理］から削除する。「One shared experience」もオフにし、Edge を使うなら Edge の設定でも切る。
- `mode` は `自動` にする。
- 人が手で尋ねて結果を記録する観測がどこまで認められるかを明記した公式資料は、見つからなかった。補足使用条件を自分で読んでから始める。

## 最初の観測で確かめること

- 日本からサインインなしで使えるか
- 個人アカウントで一時チャットを使えるか
- 毎回検索させる操作があるか
- 個人向けのアプリで出典がどんな形で表示されるか
- コピーしたときに出典の URL が残るか

## 資料

1. https://www.microsoft.com/ja-jp/microsoft-copilot/for-individuals/termsofuse
2. https://support.microsoft.com/en-us/microsoft-365-copilot/what-s-the-difference-between-microsoft-copilot-free-and-copilot-in-microsoft-365
3. https://support.microsoft.com/en-us/privacy/microsoft-copilot/transparency-note
4. https://support.microsoft.com/ja-jp/privacy/microsoft-copilot/privacy-controls
5. https://support.microsoft.com/en-us/microsoft-copilot/conversation-modes-in-microsoft-copilot
6. https://support.microsoft.com/en-us/privacy/microsoft-copilot/privacy-controls
7. https://support.microsoft.com/en-us/microsoft-365-copilot/how-web-search-works-in-microsoft-365-copilot-chat-and-agents
8. https://support.microsoft.com/en-us/microsoft-copilot/supported-regions-and-languages-in-microsoft-copilot
9. https://www.microsoft.com/en-us/servicesagreement
