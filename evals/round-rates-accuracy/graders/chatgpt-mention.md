---
type: regex
flags: i
pattern: 'chatgpt[\s\S]{0,300}?(?:[^\d/]5\s*件?\s*[/／]\s*7(?![\d/])|[^\d]7\s*件中\s*5\s*件)'
---
chatgpt の組の自社の言及が 5/7（7件中5件）と書かれていれば合格。

期待値は、fixtures/ を normalize_observations.py と compare_runs.py --period 2026-10-08 で集計した値。9件のうち、未記入 1件とエラー 1件を分母から外す。出典のチップ（[kakuu-coffee.example][1]）にだけ社名がある回答は、言及に数えない。
