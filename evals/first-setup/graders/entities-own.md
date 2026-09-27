---
type: regex
target:
  source: file
  path: ai-search/entities.csv
flags: m
pattern: '^[^,\n]+,own,[^\n]*架空茶舗[^\n]*kakuu-chaho\.example'
---
kind が own の行に、自社の名前（架空茶舗）とドメイン（kakuu-chaho.example）が入っていれば合格。
