# ai-search-operator

[![test](https://github.com/indiabiyori/ai-search-operator/actions/workflows/test.yml/badge.svg)](https://github.com/indiabiyori/ai-search-operator/actions/workflows/test.yml)

日本語: [README.md](README.md)

An Agent Skill for tracking how a Japanese-language brand or site appears in AI search, with Claude Code. You ask ChatGPT, Google AI Mode, and similar services the same questions under the same conditions and paste each answer into a file; the scripts count mentions (your name appears in the answer) and citations (your pages appear as sources), and judge whether a change made a difference. Its first rule is never to make up numbers: without recorded answers it reports no rates, and when too few prompts moved it returns "undecidable" instead of calling an improvement. I built it for my own use and am publishing it as is.

Everything in the skill is written in Japanese: SKILL.md, the playbooks, the templates, and the scripts' help and messages. The full guide is the Japanese [README.md](README.md).

## What it does

- 8 playbooks that Claude reads per task: ground rules and prioritization, setup (brand name variants, domains, competitors, verified facts), prompt set design, observation, citation gaps and inaccurate answers, AI crawler policy, before/after experiments, and reading the Search Console generative AI performance report, Bing Webmaster Tools AI Performance, and the GA4 "AI assistant" channel.
- 5 templates and a list of 34 AI crawlers (`data/ai-crawlers.csv`), each row with its official source URL and the date it was checked.
- 4 Python scripts that use only the standard library:
  - `new_round.py` creates answer-file templates for one observation round (prompts × services × repeats) and never overwrites existing files.
  - `normalize_observations.py` turns the answer files into `observations.csv` (one row per answer) and `citations.csv` (one row per source). Mentions are matched only in the answer text, after URLs are removed; tracking parameters are stripped; short links and unresolvable redirects are counted separately as "destination unknown".
  - `compare_runs.py` reports rates as `k/n` per group of conditions (service, web/app/API, login state, mode, region, language) and compares before and after with a per-prompt sign test. The verdict is one of improvement signal, worsening signal, no clear change detected, or undecidable. With fewer than 6 prompts whose rate moved it is always undecidable, because even 6 out of 6 moving the same way only just gives p = 0.03125.
  - `ai_robots_check.py` checks robots.txt against each AI crawler following RFC 9309 (a 429 response is shown as "indeterminate" because RFC 9309 and Google treat it differently). It never sends an AI crawler's User-Agent, refuses URLs with credentials, and does not connect to private addresses (including redirect targets) unless `--allow-private` is given.
- Ground rules written into SKILL.md:
  - Report rates only from recorded answers and reports, always as `k/n`, with the round and condition group. No "AI visibility score" or estimated share.
  - Do not count answers that could not be recorded (no AI answer, error, not yet pasted) as "not mentioned".
  - Do not promise that llms.txt, structured data, or any writing style will get you cited.
  - Point out manipulative tactics (mass-producing pages per prompt wording, hidden text aimed at AI) and offer alternatives.
  - A signal is not proof that the change caused it.

## How it relates to seo-operator

ai-search-operator stops at observing and identifying what is missing: which prompt, which sources were cited, and what your page lacks. Rewriting pages, structured data, internal links, backlinks, and indexing issues are handed to [seo-operator](https://github.com/indiabiyori/seo-operator) with the target URL, what is missing, and the evidence. seo-operator 1.1.0 also has an AI search playbook, so when both are installed, name `ai-search-operator` in your request for observation and experiments.

## Install

Windows has not been tested yet.

Claude Code (plugin), from a terminal:

```bash
claude plugin marketplace add indiabiyori/ai-search-operator
claude plugin install ai-search-operator@ai-search-operator
```

Or copy the folder by hand:

```bash
git clone https://github.com/indiabiyori/ai-search-operator.git
mkdir -p ~/.claude/skills
cp -R ai-search-operator/skills/ai-search-operator ~/.claude/skills/
```

On claude.ai (web or Cowork), zip the `skills/ai-search-operator` folder so that `ai-search-operator` is at the top of the zip, turn on "Code execution and file creation" in Settings → Capabilities, and upload the zip in Customize → Skills → "+" → "+ Create skill" → "Upload a skill". If `ai_robots_check.py --url` cannot reach your site from there, paste the robots.txt content and Claude will check it with `--file`.

The scripts need Python 3.9 or later and nothing else: no uv, no pip, no packages. On macOS, `/usr/bin/python3` (3.9, from the Command Line Tools) works as is.

To update a plugin install, run `claude plugin marketplace update ai-search-operator` and `claude plugin update ai-search-operator@ai-search-operator`, then restart Claude Code.

## Getting started

Create one working folder per site, open Claude Code there, and ask for the initial setup, for example `ai-search-operator で初回セットアップをして` ("run the ai-search-operator initial setup"). Claude creates `ai-search/brief.md` (goals, verified facts with sources, observation rules), `ai-search/entities.csv` (name variants, exclusions, and domains for you and your competitors), and `ai-search/prompts.csv` from templates. Then build a prompt set (questions by funnel stage, branded and non-branded), and start the first round: Claude creates the answer files with `new_round.py`, you ask each question in a new conversation and paste the answer and its sources, and Claude summarizes the round with `normalize_observations.py` and `compare_runs.py --period`.

The effort of one round is set by a single formula:

```text
records = prompts × services × repeats
```

The time per record depends on the service and the length of the answer, so the skill does not assume one; measure it in your first round.

## Terms of service

The skill never automates or scrapes AI services. The terms for the consumer services of ChatGPT, Claude, and Copilot prohibit automated collection (APIs have separate terms, not covered here), and Google prohibits automated access that violates its robots.txt. Perplexity's [Terms of Service](https://www.perplexity.ai/hub/legal/terms-of-service) section 5.2(i) also prohibits doing the same monitoring, copying, or collection by manual processes, and 5.2(a) prohibits copying information from the service. Manual observation may therefore conflict with Perplexity's terms, so Perplexity is left out of the skill's default examples; read the terms and decide yourself whether to include it (checked 2026-09-26).

## Tests

All 675 tests passed on macOS with Python 3.9.6 (`/usr/bin/python3`), 3.9.25, 3.11.15, 3.13.13, and 3.14.7 (2026-09-27). GitHub Actions runs the same tests on Ubuntu 24.04 with Python 3.9 and 3.13 on every push to main and every pull request. Python 3.10, 3.12, and Windows have not been tested. See [tests/README.md](tests/README.md) (in Japanese) for how to run them. Five evals in [evals/](evals/) check when the skill is triggered (and that it is not triggered for regular SEO or proofreading), that it gives no rates without recorded answers, that it does not promise effects from llms.txt, and that it leaves the crawler policy to the user. In two runs each on 2026-09-27, 10 of 10 passed with the skill and 9 of 10 without it, so the evals do not yet measure how much the skill helps. They use model credits, so they are run by hand with `claude plugin eval`, not in CI.

## Limitations

- No automatic collection of AI answers. API-based collection is not included yet; the `surface` field already accepts `api` so API results can go into the same CSV later.
- No script yet for the Search Console generative AI performance export or the Bing AI Performance export. They will be added after checking real export files. Until then, the playbook explains how to read them by hand.
- Answer accuracy is not judged by the scripts. Claude drafts the judgment, and only answers reviewed by a person count toward the inaccuracy rate.
- It assumes a Japanese-language brand or site (default language `ja`, region `JP`).
- The ground rules are instructions in SKILL.md; the tests do not check Claude's replies. If a rate appears without a source, ask which round and how many answers it came from.

## License and attribution

MIT (see [LICENSE](LICENSE)). Statements about each company's specifications and terms in the playbooks and in `data/ai-crawlers.csv` summarize their official documentation, with source URLs and check dates. [Google Search Central documentation](https://developers.google.com/search/docs) is published by Google under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with code samples under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).

Version 1.0.0 (last updated 2026-09-27).
