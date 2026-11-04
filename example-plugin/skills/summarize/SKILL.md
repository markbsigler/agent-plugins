---
name: summarize
description: Summarizes text or a text file the user provides, sizing the summary from word, line, and character counts produced by a bundled Python script. Use when the user asks for a summary, TL;DR, or short version of some text, or as the starting template when adding a new skill to this repository.
license: MIT
metadata:
  maintainer: your-org
---

# Summarize

Template skill for the `example-plugin` scaffold. It shows the three parts of a skill:
instructions (this file), a bundled script (`scripts/`), and on-demand reference material
(`references/`). Copy this directory when starting a new skill.

## When to use this skill

Use it when the user asks for a summary of text or of a text file.

## How to use this skill

1. Measure the input with the bundled script, which accepts a file path or piped text:

   ```bash
   # Portable (macOS, Linux, and Windows)
   uv run --script scripts/word_count.py path/to/file.txt

   # macOS/Linux shebang form
   echo "some text" | ./scripts/word_count.py
   ```

   It prints a JSON object with `lines`, `words`, and `chars`.

2. Read [references/summary-guidelines.md](references/summary-guidelines.md) to choose a
   length and shape for the summary.
3. Write the summary. Report the result to the user rather than pasting the JSON.

## Notes for skill authors

- `scripts/word_count.py` is a self-contained [PEP 723](https://peps.python.org/pep-0723/)
  script with inline metadata, so it needs no install step and the skill directory stays
  copyable.
- Keep scripts small, deterministic, and side-effect free unless the skill's purpose
  requires side effects (and say so in `description`).
- Put long or rarely needed material in `references/` and link to it from `SKILL.md`.
