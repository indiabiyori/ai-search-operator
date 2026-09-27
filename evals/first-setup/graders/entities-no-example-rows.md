---
type: regex
target:
  source: file
  path: ai-search/entities.csv
match: not_contains
pattern: 'kakuu-coffee\.example|sample-roast\.example|架空珈琲|サンプル焙煎'
---
テンプレートの架空の例の行（架空珈琲、サンプル焙煎）が entities.csv に残っていなければ合格。残すと、観測のたびに架空の会社を数え続ける（references/01-setup.md の手順2）。
