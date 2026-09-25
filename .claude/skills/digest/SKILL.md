---
name: digest
description: Write this week's law-radar AI digest in Claude Code, at no API cost. Takes the week's keyword matches from the Monday run (digests/YYYY-WW.matches.json), answers the filter, read and score requests with the prompts in law_radar/prompts, then runs the citation validator and linter. Use when the user runs /digest or asks for the weekly law digest. Optional argument - an ISO week such as 2026-W40.
---

# /digest

The weekly GitHub Action only lists keyword matches (`--no-ai`). This skill does the AI part in
Claude Code. The Python tool writes every model request to a file; you answer each one; the tool
then checks the answers with the same citation validator and linter as API mode. Fields that fail
twice are dropped. Never fix them by hand.

Work from the repository root.

## 1. Check the setup

- If `.venv/bin/law-radar` doesn't exist, run `python3 -m venv .venv` then `.venv/bin/pip install -e .`
- If there's no `icp.yaml` and no `ICP_YAML` environment variable, stop and tell the user to copy
  `icp.example.yaml` to `icp.yaml` and fill it in.
- Run `git pull --ff-only` to get the Monday run's matches. If it fails, stop and show the error.

## 2. Run one step

```
.venv/bin/law-radar digest-step
```

Add `--week 2026-W40` if the user gave a week. Then check the exit code:

- **0, `COMPLETE`**: go to step 4.
- **3, `WAITING`**: the output lists request files. Go to step 3.
- **anything else**: show the error to the user and stop.

## 3. Answer the requests

Answer each request file with a **fresh subagent** (general-purpose), up to 5 in parallel. Don't
answer requests yourself in this conversation. That keeps your context small, and each answer
depends only on its request. Use this prompt, with the path filled in:

> You are acting as the language model for one request from a tool called law-radar.
> Read this file and do exactly what it says: `<request file path>`
> The file may be long (a full legal text). Read all of it, in chunks if needed, before answering.
> Rules:
> - Read only that one file. Do not open, search or list any other file or folder in the repository.
> - Answer as the model: follow the system prompt and user message inside the file exactly.
> - Quotes must be copied character for character from the document text inside the file.
> - Write only the JSON object that matches the schema in the file, to the exact answer path the file
>   gives. No markdown fences, no extra text. Make sure it is valid JSON.
> - Then reply with one line: the path you wrote.

When all the subagents are done, go back to step 2. A week usually takes four or five rounds:
filter, read, score, rewrites, complete. If it's still waiting after 8 rounds, stop and tell the
user which requests are stuck.

## 4. Report

Show the user:
- the `COMPLETE` line (texts read, laws published, facts dropped, fields not generated);
- the path of `digests/YYYY-WW.md`, and each law's headline and scorecard points.

Then say: "Review `digests/YYYY-WW.md`, then commit and push. The weekly Issue and the Pages table
update on push."

## Rules

- Don't edit anything in `law_radar/`, the prompts, the tests, `datasets.yaml` or the ICP to make
  an answer pass.
- Don't edit the digest or the answer files after the checks. Dropped means dropped.
- Don't commit or push. The user reviews first.
- The weekly cap is `limits.max_documents_claude_code` in the ICP config (10 by default). Texts
  over the cap are kept for next week.
