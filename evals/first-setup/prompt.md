---
name: first-setup
description: 初回セットアップを頼まれたら ai-search/ に brief.md・entities.csv・prompts.csv を作り、entities.csv に自社と競合を決まった列で入れ、テンプレートの例の行を残さない
tags: [task, setup]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Edit]
---

自社が ChatGPT や Google の AI による概要でどう扱われているか、観測を始めたいです。この作業フォルダにセットアップしてください。

- 自社: 架空茶舗（読みは「かくうちゃほ」、英字表記は Kakuu Chaho）。サイトは kakuu-chaho.example
- 競合: 見本茶園（mihon-chaen.example）と試験製茶（shiken-seicha.example）

自社と競合はファイルに入れておいてください。事業の目標や正しい事実など、ほかの項目は私があとで記入するので、わからない欄は空けたままで構いません。
