---
type: regex
flags: i
pattern: '(?:google-aio|AI\s*による概要|AI\s*Overview)[\s\S]{0,300}?(?:[^\d/]4\s*件?\s*[/／]\s*5(?![\d/])|[^\d]5\s*件中\s*4\s*件)'
---
google-aio（Google の AI による概要）の組の自社の引用が 4/5（5件中4件）と書かれていれば合格。

言及の分母 6件から、出典が不明の1件をさらに外す。google.com/url?q= の転送 URL、サブドメイン（shop.kakuu-coffee.example）、本文中の URL は、自社の引用に数える。
