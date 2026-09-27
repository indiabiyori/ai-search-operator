---
type: regex
target:
  source: file
  path: ai-search/entities.csv
flags: m
pattern: '^(?=[\s\S]*^[^,\n]+,competitor,[^\n]*見本茶園[^\n]*mihon-chaen\.example)(?=[\s\S]*^[^,\n]+,competitor,[^\n]*試験製茶[^\n]*shiken-seicha\.example)'
---
kind が competitor の行が2つあり、見本茶園（mihon-chaen.example）と試験製茶（shiken-seicha.example）がそれぞれ入っていれば合格。
