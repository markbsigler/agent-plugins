# AGENTS.md

Instructions for coding agents (and humans) working in this repository.

This repo is a collection of **Agent Plugins**: portable packages of Agent Skills and MCP
server configuration built to the
[Agent Plugins Specification v1.0.0](https://agent-plugins.org/specification). It is also a
plugin **marketplace**, so a client can install any single plugin from it.

Read this file before adding or modifying a plugin. For the contributor walkthrough, see
[`CONTRIBUTING.md`](./CONTRIBUTING.md).

## 0. Quick reference

| Plugin | Contents |
| --- | --- |
| [`aha-feature`](./aha-feature) | Aha! feature/epic/requirement skill; `mcp.json` for the Aha! remote MCP server |
| [`codebase-diagrams`](./codebase-diagrams) | Skill that writes and renders Mermaid architecture diagrams |
| [`example-plugin`](./example-plugin) | Template for new plugins; **not** listed in the marketplace |

```bash
just install       # one-time machine setup (uv is the only prerequisite)
just check         # lint, format, types, spelling, tests + coverage gate, security
just new-plugin X  # scaffold a plugin (never hand-build one)
just doctor        # diagnose the toolchain
```

### Canonical sources

Consult these directly rather than relying on memory, blog posts, or secondary summaries:

| Topic | Canonical source |
| --- | --- |
| Plugin package format | https://agent-plugins.org/specification |
| Skill format | https://agentskills.io/specification |
| MCP protocol | https://modelcontextprotocol.io/specification/ |

Where the Agent Plugins specification and this document conflict, the specification wins.

## 1. Repository layout

```text
agent-plugins/
├── <plugin>/              # any top-level directory containing plugin.json
├── example-plugin/        # canonical template the scaffolder copies
├── .github/plugin/        # marketplace.json catalog
├── schemas/1.0.0/         # vendored Agent Plugins JSON Schemas (just update-schemas)
├── scripts/               # cross-platform helpers behind the justfile
├── tests/                 # repo-level validation, auto-discovers plugins
└── justfile, pyproject.toml, uv.lock, .pre-commit-config.yaml, trivy.yaml, ...
```

- Any top-level directory containing `plugin.json` **is** a plugin. Discovery and validation
  are driven by that glob, so a new plugin is covered by the test suite with no test edits.
- **Never hand-build a plugin** — run `just new-plugin <name>`, which copies
  `example-plugin/` and rewrites every identifier (`--no-mcp` omits `mcp.json`).
- Repo-level tooling (`README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `pyproject.toml`,
  `justfile`, `schemas/`, `scripts/`, `tests/`, and so on) is not plugin content. Never place
  it inside a plugin and never make plugin behavior depend on it. Plugins never import from
  each other.
- `scripts/` holds the Python helpers that back the `justfile` (`toolchain.py`,
  `new_plugin.py`, `_scaffold.py`, `security_scan.py`, `update_schemas.py`). Put logic here,
  not in a recipe (§1.3).
- There is **no CI** on this repository. Local checks (`just check` and the pre-commit hooks)
  are the only enforcement, so they must pass before every commit.

### 1.1 One `uv` environment

One root `uv.lock` pins the dev tooling; `just sync` runs `uv sync`. Skill scripts are
PEP 723 files and do not belong to this environment. After any dependency change, run
`uv lock` then `uv sync` and commit `uv.lock`. If trivy blocks on a CVE, bump the package
with `uv lock -P <package>`.

### 1.2 Environment setup

**`uv` is the single hard prerequisite.** `just` installs from PyPI
(`uv tool install rust-just`, with wheels for macOS, Linux, and Windows) and the Python tools
come from the project environment. Never install them separately.

- **`just install`** detects the platform package manager (Homebrew, apt, dnf, pacman,
  zypper, winget, scoop, Chocolatey), installs what is missing, and syncs the environment.
  It is idempotent.
- **`just doctor`** reports the status of every tool without changing anything. Run it first
  when something behaves unexpectedly.
- `trivy` is **optional**: development, testing, and linting work without it, and
  `just security` skips cleanly when it is absent.

### 1.3 Portability rules

This repo must work on **macOS, Linux, and Windows**. Two rules keep it that way, both
enforced by `tests/test_portability.py`:

1. **`justfile` recipes must be shell-agnostic.** A recipe is a single command: no bash
   shebangs, `&&`, `||`, pipes, `$(...)`, redirects, or loops. Windows has no bash and
   `set windows-shell` routes to PowerShell. Anything needing logic goes in `scripts/*.py`,
   invoked via `uv`:

   ```make
   # wrong -- POSIX only
   doctor:
       for t in uv just; do command -v $t || echo missing; done

   # right -- runs anywhere
   doctor:
       uv run python scripts/toolchain.py doctor
   ```

2. **Text files are LF.** `.gitattributes` enforces this. A CRLF after a
   `#!/usr/bin/env -S uv run --script` shebang produces a baffling "bad interpreter" error on
   Unix.

Also:

- Skill scripts keep their shebang *and* are documented with the portable
  `uv run --script <path>` form, because Windows ignores shebangs.
- The executable bit is asserted from **git's index mode** (`100755`), not the filesystem.
  Set it with `git update-index --chmod=+x <path>` if `chmod` isn't available.
- Use `pathlib`, never string path concatenation or hardcoded `/`.
- Scripts must not use `shell=True` (tested).

## 2. The Agent Plugins package format (summary)

### 2.1 Plugin package model

- A plugin is one directory and **must** contain `plugin.json` at its root.
- Any spec-defined plugin-relative path must start with `./` and resolve inside the plugin
  root, even through symlinks. Never write a path that can escape (`../`, absolute paths).
  Tests reject symlinks that resolve outside the plugin.
- Command arguments, environment values, and HTTP headers are opaque strings, not
  path-checked. See §2.4 and §2.5.

### 2.2 Manifest (`plugin.json`)

- The schema is **closed**. Only these top-level fields are permitted: `$schema` (required),
  `name` (required), `version`, `description`, `author`, `homepage`, `repository`, `license`,
  `keywords`, `extensions`. Anything else belongs under `extensions`, keyed by a
  reverse-domain namespace you own.
- `$schema` must be exactly `"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"`.
- `name`: 1–64 characters of lowercase ASCII letters, digits, `-` and `.`; it must start and
  end alphanumeric, with no `--` or `..`. Valid: `example-plugin`, `acme.tools`. Invalid:
  `My-Plugin`, `-start`, `has--double`.
- The directory name must equal `name` (tested).
- No `TODO` or template placeholder values may remain in a plugin's manifests (tested; the
  scaffolder deliberately leaves them to be replaced).

### 2.3 Component types (fixed locations only)

Agent Plugins v1 defines exactly two portable component types, discovered only from fixed
locations. `plugin.json` never contains inline component config.

| Component | Location | Discovery rule |
| --- | --- | --- |
| Skills | `skills/` | Each **immediate** child directory containing a regular `SKILL.md`. Not recursive. |
| MCP servers | `mcp.json` | JSON object with only `$schema` and `mcpServers`. |

A missing `skills/` or `mcp.json` is fine; it is just an absent component type.

**Nothing else belongs in a plugin** beyond `plugin.json`, `README.md`, `CHANGELOG.md` and
`LICENSE`. `servers/` and similar build material are not portable components: clients ignore
them and they would ship inside every installed copy. Host server source in its own
repository. The only other allowed top-level directories are reverse-domain client
extensions (§2.6). `tests/test_manifests.py` enforces this.

### 2.4 Transports and placeholders

- Plugins here reference **`streamable-http`** servers hosted elsewhere. `stdio` entries are
  supported by the spec but are not the pattern here.
- Remote entries require `type` and `url`; `url` must be absolute HTTP(S), with no userinfo
  or fragment, and non-loopback endpoints must use HTTPS.
- `${PLUGIN_ROOT}` / `${PLUGIN_DATA}` expand **only** in a stdio entry's `args`, `env`, and
  `cwd`, never in `command`, `url`, or headers.
- **Consequence:** one manifest cannot parameterize dev/staging/prod URLs. Ship one URL, or
  maintain per-environment plugin variants. A plugin that needs a per-user value (for
  example `aha-feature` and the Aha! subdomain) documents the one-line edit in its README.

### 2.5 Secrets

`headers` and committed `env` values are **visible package data**, not a secrets mechanism.
Never put credentials, tokens, or API keys there; tests reject credential-looking header
names. Agent Plugins v1 defines no portable OAuth or credential field; authentication is
client-managed. Do not invent one.

### 2.6 Client extensions

Only add data under `extensions.<namespace>` or a top-level `<namespace>/` directory for a
reverse-domain namespace you own and document (for example `com.example.client/`). Don't
invent hooks, agents, or commands at the portable top level.

## 3. Skills

A skill is `skills/<name>/SKILL.md` plus optional `scripts/`, `references/`, and `assets/`.
`tests/test_skills.py` validates every skill against the
[Agent Skills specification](https://agentskills.io/specification):

- Frontmatter opens with `---` and uses only these keys: `name`, `description`, `license`,
  `compatibility`, `metadata` (string-to-string), `allowed-tools`.
- `name`: 1–64 characters, lowercase alphanumeric plus single hyphens, no leading or trailing
  hyphen, and **equal to the directory name**.
- `description`: required, at most 1024 characters. Say both *what* the skill does and *when*
  to use it, since that is what an agent matches against. `compatibility` is at most 500.
- Use progressive disclosure: keep `SKILL.md` focused, and put long or rarely needed material
  in `references/` linked from `SKILL.md` so it costs no context until read.
- Any `./scripts/...` path mentioned in `SKILL.md` must exist.
- Bundled scripts must be executable (git index mode), have a shebang, and use LF endings.
- Show the `uv run --script scripts/<name>.py` form in `SKILL.md`.

## 4. Python conventions

### 4.1 Use `uv` exclusively

- `uv` for everything: running, dependency management, resolution. Do **not** introduce
  `venv`, `pip`, `pipx`, `pyenv`, or `poetry`; each has a `uv` equivalent (`uv run`,
  `uv sync`, `uv add`, `uv run --script`, `uv python install`). Ask before adding any other
  packaging tool.
- Never commit `requirements.txt`. Skill dependencies belong in a PEP 723 inline block; dev
  tooling lives in the root `pyproject.toml` with `uv.lock` committed.
- `.python-version` pins the interpreter for the dev environment (3.12). Skill scripts
  declare their own `requires-python`.

### 4.2 Skill scripts are PEP 723 single files

Inline `# /// script` metadata, `#!/usr/bin/env -S uv run --script` shebang, `chmod +x`.
Dependencies resolve on first run, so the skill directory stays self-contained and copyable.
Keep scripts small and deterministic, and say so in the skill `description` when a script has
side effects.

### 4.3 Data validation and processing

When a script needs them:

- **Pydantic v2** for structured input and output at boundaries (script stdout, HTTP bodies).
  Use v2 APIs only (`model_dump()`, `model_validate()`, `Field`), never v1 (`.dict()`,
  `.parse_obj()`).
- **polars** for tabular work, not `pandas` without asking. Prefer the lazy API
  (`pl.scan_csv(...).collect()`) for data that may not fit in memory.
- Declare these per skill script in its PEP 723 block, never in the repo root.

### 4.4 Testing

```bash
just test          # everything, with the branch-coverage gate
just test-fast     # skip tests marked `slow`
```

- Coverage uses **branch** measurement with an **80% gate** (`fail_under` in
  `pyproject.toml`), including scripts run in subprocesses (`patch = ["subprocess"]`).
  `[tool.coverage.run].source` scopes it to `scripts/` and the skill scripts under test.
  Run `just coverage` for a line-by-line report.
- `filterwarnings = ["error"]`: a new warning fails the suite. Fix the cause rather than
  filtering it. Tests use `--import-mode=importlib` and `--strict-markers`.
- Mark tests that start a real subprocess or touch the network `@pytest.mark.slow`.
- **Repo-level tests auto-discover.** Any test taking `plugin_dir` or `skill_dir` is
  parametrized across everything found (see `tests/conftest.py`, `tests/discovery.py`). Add
  new *checks*, never hardcoded plugin names.
- What the suites cover: `test_manifests.py` (schemas, MCP rules, top-level entries),
  `test_skills.py` (Agent Skills spec), `test_marketplace.py` (§5), `test_portability.py`
  (§1.3), plus per-script and tooling tests.
- Use [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/) for verbose expected
  values: write `snapshot()`, run `just snapshot-fix`, then **read the diff**. A passing fix
  means code and test agree, not that the value is correct.
- **`scripts/*.py` are tested by importing and calling `main()` directly** (mocking
  `subprocess.run`, `shutil.which`, `urllib.request.urlopen`, and so on), not by spawning
  `uv run python scripts/x.py` per scenario: a subprocess can't be measured in-process and
  lets slow system dependencies creep in. Keep at most one real subprocess smoke test per
  script to prove the CLI wiring (see `test_new_plugin_cli_works_as_documented`).

### 4.5 Code quality

- Type hints on all signatures; avoid bare `Any` when a concrete type exists.
- `pathlib.Path` over string path manipulation (ruff `PTH`).
- Google-style docstrings (ruff `D`), line length 100, `from __future__ import annotations`.
- Never `shell=True`; pass argument lists. Handle expected failures with clear non-zero
  exits, not tracebacks.
- Suppress a lint only with a **targeted, explained** `# noqa: RULE`. `RUF100` fails the
  build on stale suppressions.

### 4.6 Tooling

Everything runs through `just`; prefer recipes over retyping commands, and update the
`justfile` (not just this doc) when a command changes.

| Tool | Purpose | Recipe |
| --- | --- | --- |
| `uv` | Packaging, environment, script running | `just sync` |
| `just` | Task runner | `just` (lists recipes) |
| `ruff` | Lint and format (broad rule set) | `just lint` / `just fmt` |
| `ty` | Type check (**not** mypy or pyright) | `just typecheck` |
| `taplo` | TOML formatting | `just fmt` |
| `typos` | Spell check | `just spell` |
| `pytest` | Tests and coverage | `just test` |
| `pre-commit` | Git hooks | `just install-hooks` |
| `trivy` | Vulnerabilities, secrets, misconfig (optional) | `just security` |

`ty` skips PEP 723 scripts (`[tool.ty.src].exclude`) because their dependencies live in
`uv`'s per-script cache, and it needs `extra-paths` for `scripts/`, `tests/`, and the
`aha-feature` scripts. Type-check a skill script with
`uv run --with ty --with <deps> ty check <path>`.

For `trivy`: fix real findings rather than suppressing them. If a finding is a reviewed false
positive, add it to [`.trivyignore`](./.trivyignore) **with a comment**. Never suppress
silently.

Pre-commit runs `language: system` hooks that call this repo's toolchain, so hooks and the
`justfile` cannot drift: file hygiene, `ruff check`, `ruff format`, `taplo`, `typos`, `ty`,
fast `pytest` with coverage, and `trivy`. If you add a repo-level tool, add **both** a
recipe and a hook.

### 4.7 Before committing

Run **`just check`** (lint, format, types, spelling, tests, security). Then:

1. Exercise any new or changed script directly.
2. Re-read `plugin.json` and `mcp.json` diffs against §2; a schema violation is fatal for
   the whole plugin.
3. If dependencies changed, commit the updated `uv.lock`.
4. If a plugin changed, update its `CHANGELOG.md`; bump `version` (and the marketplace entry,
   §5) when the change is releasable. Record repo-level changes in the root `CHANGELOG.md`.

## 5. Marketplace and releases

[`.github/plugin/marketplace.json`](./.github/plugin/marketplace.json) lists every
distributable plugin (`name`, `description`, `version`, `source: "./<plugin>"`).
`tests/test_marketplace.py` requires that:

- every plugin except `example-plugin` is listed, and names are unique;
- each entry's `name`, `description`, and `version` match that plugin's `plugin.json`.

Change both together. Plugin versions follow semantic versioning and track the plugin's own
`CHANGELOG.md`.

## 6. Git conventions

- Commit subjects use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`), imperative, at most 72 characters, with a body explaining *why* when the
  change is non-trivial.
- Commit and push only when asked. Never skip hooks (`--no-verify`) or amend or force-push
  without explicit approval. Fix the cause of a failing hook instead.
- Never commit credentials, `.coverage`, `htmlcov/`, `cov_annotate/`, or `.DS_Store`.
- Keep PRs focused on one plugin or one concern.

## 7. Checklist for a new plugin

- [ ] Created with `just new-plugin <name>` (not hand-built).
- [ ] Directory name matches manifest `name`.
- [ ] `plugin.json` has only spec-allowed top-level fields and no `TODO` or template values.
- [ ] Each skill is `skills/<name>/SKILL.md` with frontmatter `name` matching its directory
      and a description saying *what* and *when*.
- [ ] Skill scripts are PEP 723, executable, have a shebang, and are shown as
      `uv run --script` in `SKILL.md`.
- [ ] `mcp.json` (if present) uses `streamable-http` with a real HTTPS URL and no
      credentials in headers; delete it otherwise.
- [ ] Nothing at the plugin top level except `plugin.json`, `skills/`, `mcp.json`, docs, and
      reverse-domain extension directories.
- [ ] README and `CHANGELOG.md` describe the plugin; `LICENSE` is present.
- [ ] Marketplace entry added to `.github/plugin/marketplace.json` if it is distributable.
- [ ] `just check` passes.
