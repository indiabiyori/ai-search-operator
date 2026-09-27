# Gemini（`gemini`）の観測条件

Gemini で観測するときの条件だけを書いた。ラウンドの決まり、回答ファイルの書き方、status と sources_status、集計といった共通の手順は [03-observation.md](../03-observation.md) にあり、このファイルと合わせて読む。

事実は、2026-09-26 に各社の公式資料で確認できた範囲に限る。本文の「資料1」などは、末尾の「資料」の番号を指す。確認日から3か月以上たっていたら、各社のヘルプで確かめ直す。

## 公式資料で確認できたこと

| 項目 | 2026-09-26 に公式資料で確認できたこと |
|---|---|
| ログインなし | 地域やデバイスの種類によっては、一部の機能をログインせずに使える。ログアウト中は、過去のチャット、パーソナライズされた回答、アプリ連携、モデルの切り替えが使えない（資料1） |
| アプリ | Android のモバイルアプリはログインが必須（資料1） |
| ウェブ検索 | 回答の一部は検索結果に基づき、すべての回答が検索に基づくわけではない（資料3）。Google 検索の公開情報は、ログアウト中でも使われる（資料2） |
| 検索の指定 | 通常のチャットで検索を必ず使わせる方法は、公式資料で見つからなかった |
| 一時チャット | パソコン版では「New chat」の横の「Temporary chat」から始め、パーソナライズされた回答が出ず、今後のパーソナライズにも使われない。個人の Google アカウントでのログインが要る（資料4。英語版ヘルプの記述） |
| パーソナル インテリジェンス | ツールの［パーソナル インテリジェンス］をオフにしたチャットもアクティビティに保存され、別のチャットのパーソナライズに使われるため、ヘルプは一時チャットを勧めている（資料5） |
| 出典の表示 | ソースがある回答では、回答の下か回答内に［ソース］ボタンが出て、押すと右側に関連リンクが並ぶ。［ソース］ボタンがない回答は、リンクを提供しなかったもの（資料6） |
| 過去のチャットの参照 | 過去のチャットを参照した回答には［以前のチャット］と表示される（資料7） |
| 地域・言語 | 表示言語はブラウザかデバイスの設定に従い、プロンプトは対応言語で理解して回答する（資料8）。位置情報は常に収集され、既定では IP アドレスかアカウントの住所から推定したおおよその地域が使われる（資料11） |
| 規約の要点 | Gemini アプリには Google 利用規約と「生成 AI の使用禁止に関するポリシー」が適用され（資料3）、Google 利用規約は robots.txt などの機械可読な指示に反した自動化された手段でのアクセスを禁じている（資料9）。gemini.google.com の robots.txt は `/app/` と `/chat/` を拒否している（資料10） |

## 観測するときの手順

- ログインせずに尋ね、`login` を `なし` にする。ログインしないと使えなければ、一時チャットで尋ねて `login` を `あり（記憶オフ）` にする。［パーソナル インテリジェンス］をオフにするだけでは、記憶は切れない。
- `mode` は `自動` にする。検索を必ず使わせる方法がないため。
- ［ソース］ボタンがない回答は、`sources_status` を `なし` にする。
- 回答に［以前のチャット］と表示されたら、記憶が切れていない。一時チャットで尋ねているかを確かめ、条件を見直す。

## 最初の観測で確かめること

- 日本からログインなしで使えるか。ログアウト中の回答に［ソース］ボタンが出るか
- ログアウト中にどのモデルが使われるか（画面に表示されれば `mode` に書く）
- 日本語の画面で、一時チャットのボタンが何と表示されるか
- 本文中に出典がどんな形で表示されるか
- 回答全体をコピーしたときに出典の URL が残るか

## 資料

1. https://support.google.com/gemini/answer/13275745?hl=ja&co=GENIE.Platform%3DDesktop
2. https://support.google.com/gemini/answer/13695044?hl=ja&co=GENIE.Platform%3DDesktop
3. https://support.google.com/gemini/answer/13594961?hl=ja
4. https://support.google.com/gemini/answer/13275745?hl=en&co=GENIE.Platform%3DDesktop
5. https://support.google.com/gemini/answer/16598406?hl=ja&co=GENIE.Platform%3DDesktop
6. https://support.google.com/gemini/answer/14143489?hl=ja&co=GENIE.Platform%3DDesktop
7. https://support.google.com/gemini/answer/13666746?hl=ja&co=GENIE.Platform%3DDesktop
8. https://support.google.com/gemini/answer/15984485?hl=ja&co=GENIE.Platform%3DDesktop
9. https://policies.google.com/terms?hl=ja
10. https://gemini.google.com/robots.txt
11. https://support.google.com/gemini/answer/13594961?hl=en
