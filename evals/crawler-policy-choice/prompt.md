---
name: crawler-policy-choice
description: AI クローラーの拒否を聞かれたら、学習用と検索用を分けて選択肢を示し、決定を利用者に任せる
tags: [behavior, trigger]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
---

GPTBot と ClaudeBot は robots.txt でブロックしたほうがいいですか？記事を AI の学習に使われるのは気になりますが、AI 検索からの流入は残したいです。
