---
type: regex
target:
  source: file
  path: ai-search/prompts.csv
flags: m
pattern: '^﻿?prompt_id,prompt,stage,branded,intent_group,source,active,added_on\r?$'
---
prompts.csv の見出しの行が、new_round.py と normalize_observations.py の読む列と同じなら合格。
