---
name: round-rates-accuracy
description: 架空の観測データから、ラウンドの自社の言及率・引用率を組ごとに正しい k/n で出す。未記入・AI の回答なし・エラー・出典が不明の回答を分母から外す
tags: [task]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Bash]
---

ai-search/answers/2026-10-08 に、ChatGPT と Google の AI による概要の回答を貼り終えました。このラウンドの自社（架空珈琲）の言及率と引用率を教えてください。
