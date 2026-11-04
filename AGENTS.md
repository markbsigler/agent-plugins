# AGENTS.md

Instructions for coding agents (and humans) working in this repository.

This repo is a collection of **Agent Plugins**: portable packages of Agent
Skills and MCP server configuration built to the
[Agent Plugins Specification v1.0.0](https://agent-plugins.org/specification).

Read this file before adding or modifying a plugin. For the contributor
walkthrough, see [`CONTRIBUTING.md`](./CONTRIBUTING.md).

### Canonical sources

Consult these directly rather than relying on memory, blog posts, or
secondary summaries — all are current and authoritative:

| Topic | Canonical source |
| --- | --- |
| Plugin package format | https://agent-plugins.org/specification |
| Skill format | https://agentskills.io/specification |
| **MCP protocol** | **https://modelcontextprotocol.io/specification/** |

Where the Agent Plugins specification and this document conflict, the
specification wins.

## 1. Repository layout

- Any top-level directory containing `plugin.json` **is** a plugin. Discovery
  and validation are driven by that glob, so a new plugin directory is
  automatically covered by the test suite with no test edits.
- [`example-plugin/`](./example-plugin) is the canonical example. **Never hand-build a
  new plugin** — run `just new-plugin <name>`, which copies it and rewrites
  every identifier.
- Repo-level tooling — `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `pyproject.toml`, `justfile`,
  `.gitattributes`, `.pre-commit-config.yaml`, `schemas/`, `scripts/`,
  `tests/` — is not plugin content. Never place it inside a plugin, and never
  make plugin behavior depend on it.
- `scripts/` holds the cross-platform Python helpers that back the `justfile`
  (`toolchain.py`, `new_plugin.py`, `security_scan.py`, `update_schemas.py`). Add logic here
  rather than in a recipe — see §1.3.
- [`schemas/1.0.0/`](./schemas/1.0.0) vendors the canonical Agent Plugins JSON
  Schemas used by the tests. Refresh with `just update-schemas`.

### 1.1 One `uv` environment

One root `uv.lock` pins the dev tooling. Sync with **`just sync`** (`uv sync`).
Skill scripts are PEP 723 files and do not belong to this environment.

### 1.2 Environment setup

**`uv` is the single hard prerequisite.** Everything else bootstraps from it:
`just` installs from PyPI (`uv tool install rust-just`, which has wheels for
macOS, Linux, and Windows), and the Python tools come from the project environment.

Run **`just install`** on a new machine: it detects the platform's package
manager (Homebrew, apt, dnf, pacman, zypper, winget, scoop, Chocolatey),
installs what's missing, and syncs the environment. It is idempotent.

**`just doctor`** reports the status of every tool without changing anything — run it first when something behaves unexpectedly.

`trivy` is **optional**: development, testing, and linting work without it. `just security` skips cleanly when `trivy` is absent.

Python tools (`ruff`, `ty`, `taplo`, `typos`, `pytest`) come from the uv
environment, not a package manager. Never install them separately.

### 1.3 Portability rules

This repo must work on **macOS, Linux, and Windows**. Two rules keep it that
way, both enforced by `tests/test_portability.py`:

1. **`justfile` recipes must be shell-agnostic.** A recipe is a single
   command. No bash shebangs, `&&`, `||`, pipes, `$(...)`, redirects, or
   loops — Windows has no bash, and `set windows-shell` routes to PowerShell.
   Anything needing logic goes in `scripts/*.py` and is invoked via `uv`:

   ```make
   # wrong -- POSIX only
   doctor:
       for t in uv just; do command -v $t || echo missing; done

   # right -- runs anywhere
   doctor:
       uv run python scripts/toolchain.py doctor
   ```

2. **Text files are LF.** `.gitattributes` enforces this. A CRLF after a
   `#!/usr/bin/env -S uv run --script` shebang produces a baffling "bad
   interpreter" error on Unix.

Also:

- Skill scripts keep their shebang *and* are documented with the portable
  `uv run --script <path>` invocation, because Windows ignores shebangs.
- The executable bit is asserted from **git's index mode** (`100755`), not the
  filesystem, so the check is meaningful on Windows. Set it with
  `git update-index --chmod=+x <path>` if `chmod` isn't available.
- Use `pathlib`, never string path concatenation or hardcoded `/`.

## 2. The Agent Plugins package format (summary)

### 2.1 Plugin package model

- A plugin is one directory and **must** contain `plugin.json` at its root.
- Any spec-defined plugin-relative path must start with `./` and resolve
  inside the plugin root, even through symlinks. Never write a path that can
  escape (`../`, absolute paths).
- Command arguments, environment values, and HTTP headers are opaque strings —
  not path-checked. See §2.4 and §2.5.

### 2.2 Manifest (`plugin.json`)

- The schema is **closed**. Only these top-level fields are permitted:
  `$schema` (required), `name` (required), `version`, `description`, `author`,
  `homepage`, `repository`, `license`, `keywords`, `extensions`. Anything else
  belongs under `extensions`, keyed by a reverse-domain namespace you own.
- `$schema` must be exactly
  `"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"`.
- `name`: 1–64 chars, lowercase ASCII letters/digits/`-`/`.`, must start and
  end alphanumeric, no `--` or `..`. Valid: `example-plugin`, `acme.tools`.
  Invalid: `My-Plugin`, `-start`, `has--double`.
- Keep the directory name identical to `name` (enforced by tests).

### 2.3 Component types (fixed locations only)

Agent Plugins v1 defines exactly two portable component types, discovered only
from fixed locations. `plugin.json` never contains inline component config.

| Component | Location | Discovery rule |
| --- | --- | --- |
| Skills | `skills/` | Each **immediate** child directory containing a regular `SKILL.md`. Not recursive. |
| MCP servers | `mcp.json` | JSON object with only `$schema` and `mcpServers`. |

A missing `skills/` or `mcp.json` is fine — just an absent component type.

**Nothing else belongs in a plugin.** `servers/` and similar build material are
not portable components: clients ignore them, and they would ship inside every
installed copy. Host server source in its own repository. The only other
allowed top-level directories are reverse-domain client extensions (§2.6).
`tests/test_manifests.py` enforces this.

### 2.4 Transports and placeholders

- Plugins here reference **`streamable-http`** servers hosted elsewhere. `stdio`
  entries are supported by the spec but are not the pattern here.
- Remote entries require `type` and `url`; `url` must be absolute HTTP(S),
  with no userinfo or fragment, and non-loopback endpoints must use HTTPS.
- `${PLUGIN_ROOT}` / `${PLUGIN_DATA}` expand **only** in a stdio entry's
  `args`, `env`, and `cwd` — never in `command`, `url`, or headers.
- **Consequence:** one manifest cannot parameterize dev/staging/prod URLs.
  Ship the production URL, or maintain per-environment plugin variants.

### 2.5 Secrets

`headers` and committed `env` values are **visible package data**, not a
secrets mechanism. Never put credentials, tokens, or API keys there — tests
reject credential-looking header names. Agent Plugins v1 defines no portable
OAuth or credential field; authentication is client-managed. Do not invent one.

### 2.6 Client extensions

Only add data under `extensions.<namespace>` or a top-level `<namespace>/`
directory for a reverse-domain namespace you own and document. Don't invent
hooks/agents/commands at the portable top level.

## 3. Python conventions

### 3.1 Use `uv` exclusively

- `uv` for everything: running, dependency management, resolution. Do **not**
  introduce `venv`, `pip`, `pipx`, `pyenv`, or `poetry`. There is a `uv`
  equivalent for each (`uv run`, `uv sync`, `uv add`, `uv run --script`,
  `uv python install`). Ask before adding any other packaging tool.
- Never commit `requirements.txt`. Dependencies belong in a PEP 723 inline
  block (skills); the repo's dev tooling lives in the root `pyproject.toml`
  with `uv.lock` committed.
- `.python-version` pins the interpreter for the dev environment.

### 3.2 Skill scripts are PEP 723 single files

Inline `# /// script` metadata, `#!/usr/bin/env -S uv run --script` shebang,
`chmod +x`. Dependencies resolve on first run, so the skill directory stays
self-contained and copyable.

Never make one plugin import code from another.

### 3.3 Data validation and processing

- **Pydantic v2** for structured input/output at boundaries — script stdout,
  tool returns, HTTP bodies. Use v2 APIs only (`model_dump()`,
  `model_validate()`, `Field`), never v1 (`.dict()`, `.parse_obj()`). Prefer
  `Field` constraints over hand-rolled validation.
- **polars** for tabular work — not `pandas` without asking. Prefer the lazy
  API (`pl.scan_csv(...).collect()`) for anything that may not fit in memory.
- Declare these per skill script (PEP 723 block), never in the repo root.

### 3.4 Testing

```bash
just test          # everything
just test-fast     # skip subprocess/network round trips
```

- **Repo-level tests auto-discover plugins.** Any test taking `plugin_dir`
  or `skill_dir` is parametrized across everything found. Add
  new *checks*, never new hardcoded plugin names.
- Use [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/) for
  verbose expected values: write `snapshot()`, run `just snapshot-fix`, then
  **read the diff**. A passing fix means code and test agree — not that the
  new value is correct.
- **`scripts/*.py` are tested by importing and calling `main()` directly**
  (mocking `subprocess.run`, `shutil.which`, `urllib.request.urlopen`, etc.),
  not by spawning `uv run python scripts/x.py` for every scenario. A
  subprocess sees a separate interpreter, so coverage tooling can't measure
  it and slow, real system dependencies creep in. Keep at most one real
  subprocess-based smoke test per script to prove the actual CLI/shebang
  wiring works (see `test_new_plugin_cli_works_as_documented`); put every
  other scenario through a direct `main()` call.
- Run `just coverage` (`pytest --cov --cov-report=annotate:cov_annotate`)
  periodically. `[tool.coverage.run].source` in `pyproject.toml` scopes
  measurement to `scripts/` and the skill scripts that tests import or run.

### 3.5 Code quality

- Type hints on all signatures; avoid bare `Any` when a concrete type exists.
- `pathlib.Path` over string path manipulation (enforced by ruff `PTH`).
- Google-style docstrings (`D` ruleset).
- Never `shell=True`; pass argument lists.
- Handle expected failures explicitly with clear non-zero exits, not
  tracebacks.
- Suppress a lint only with a **targeted, explained** `# noqa: RULE`. `RUF100`
  fails the build on stale suppressions.

### 3.6 Tooling

Everything runs through `just` — prefer recipes over retyping commands, and
update the `justfile` (not just this doc) when a command changes.

| Tool | Purpose |
| --- | --- |
| `uv` | Packaging, environment, script running |
| `just` | Task runner (`just install`, `just doctor`, `just check`) |
| `ruff` | Lint + format |
| `ty` | Type check (**not** mypy/pyright) |
| `taplo` | TOML formatting |
| `typos` | Spell check |
| `pytest` | Tests |
| `trivy` | Vulnerabilities, secrets, misconfig |

`ty` skips PEP 723 scripts (`[tool.ty.src].exclude`) because their deps live in
`uv`'s per-script cache. Type-check one with
`uv run --with ty --with <deps> ty check <path>`.

For `trivy`: fix real findings rather than suppressing them; if a finding is a
reviewed false positive, add it to [`.trivyignore`](./.trivyignore) **with a
comment**. Never suppress silently.

Pre-commit (`just install-hooks`) runs the same tools as `language: system`
hooks calling this repo's toolchain, so hooks and `justfile` can't drift. If
you add a repo-level tool, add **both** a recipe and a hook.

### 3.7 Before committing

Run **`just check`** (lint, format, types, spelling, tests, security). Then:

1. Exercise any new/changed script directly.
2. Re-read `plugin.json` / `mcp.json` diffs against §2 — a schema violation is
   fatal for the whole plugin.
3. If dependencies changed, commit the updated `uv.lock`.

## 4. Checklist for a new plugin

- [ ] Created with `just new-plugin <name>` (not hand-built).
- [ ] Directory name matches manifest `name`.
- [ ] `plugin.json` has only spec-allowed top-level fields; no TODO/template
      values left.
- [ ] Each skill is `skills/<name>/SKILL.md` with frontmatter `name` matching
      its directory and a description saying *what* and *when*.
- [ ] Skill scripts are PEP 723, executable, and have a shebang.
- [ ] `mcp.json` (if present) uses `streamable-http` with a real HTTPS URL and
      no credentials in headers; delete it otherwise.
- [ ] Nothing at the plugin top level except `plugin.json`, `skills/`,
      `mcp.json`, docs, and reverse-domain extension directories.
- [ ] `just check` passes.
