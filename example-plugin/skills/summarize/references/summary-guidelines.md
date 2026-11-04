# Summary guidelines

Load this file only when the user asks for a summary and the right length or shape is not
obvious. Keeping it out of `SKILL.md` means it costs no context until it is needed.

## Choosing a length

Use the counts from `scripts/word_count.py` to size the summary:

| Input words | Target summary |
| --- | --- |
| Under 200 | One or two sentences |
| 200 to 1,500 | One short paragraph |
| Over 1,500 | A short paragraph plus three to five bullet points |

## Shape

- Lead with the main point, then supporting detail.
- Keep names, numbers, and dates exactly as written in the source.
- Do not add claims the source does not make.
- If the source is ambiguous or incomplete, say so instead of guessing.
