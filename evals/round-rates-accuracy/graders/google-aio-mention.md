---
type: regex
flags: i
pattern: '(?:google-aio|AI\s*による概要|AI\s*Overview)[\s\S]{0,300}?(?:[^\d/]5\s*件?\s*[/／]\s*6(?![\d/])|[^\d]6\s*件中\s*5\s*件)'
---
google-aio（Google の AI による概要）の組の自社の言及が 5/6（6件中5件）と書かれていれば合格。

9件のうち、AI の回答なし 2件と未記入 1件を分母から外す。本文に URL（https://kakuu-coffee.example/subscription）だけがある回答は、言及に数えない。
