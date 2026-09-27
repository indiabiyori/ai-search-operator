---
type: regex
flags: i
pattern: 'chatgpt[\s\S]{0,300}?(?:[^\d/]3\s*件?\s*[/／]\s*6(?![\d/])|[^\d]6\s*件中\s*3\s*件)'
---
chatgpt の組の自社の引用が 3/6（6件中3件）と書かれていれば合格。

言及の分母 7件から、出典が不明（sources_status が 不明）の1件をさらに外す。sources_status が なし の回答は分母に入る（引用なし）。kakuu-coffee-fan.example は自社のドメインではないので、引用に数えない。
