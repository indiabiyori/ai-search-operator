---
type: regex
target:
  source: file
  path: ai-search/entities.csv
flags: m
pattern: '^﻿?entity_id,kind,name,terms,exclude_terms,domains\r?$'
---
entities.csv の見出しの行が、normalize_observations.py の読む列（entity_id,kind,name,terms,exclude_terms,domains）と同じなら合格。
