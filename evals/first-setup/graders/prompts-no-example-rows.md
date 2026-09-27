---
type: regex
target:
  source: file
  path: ai-search/prompts.csv
match: not_contains
pattern: '架空珈琲|コーヒー'
---
テンプレートの架空の例のプロンプト（コーヒー豆の質問）が prompts.csv に残っていなければ合格。残すと、次のラウンドで new_round.py が他社の質問の回答ファイルまで作る（references/01-setup.md の手順2）。
