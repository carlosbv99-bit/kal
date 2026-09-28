# Contributing to Kal

🇬🇧 English | 🇪🇸 [Español](CONTRIBUTING.es.md)

> This repo is **kal**, the pure security microkernel — no agent, no
> LLM, no ML bundled. Anything that decides *what an agent does*
> (reasoning loop, tool implementations, memory) lives in
> [kal-in](https://github.com/carlosbv99-bit/kal-in), kal's own
> reference agent built on top of this kernel — see the note at the
> top of [README.md](README.md).

## Contributing code

1. Fork the repo and clone it locally.
2. Set up a virtualenv and install dependencies:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-core.txt -r requirements-dev.txt
   ```
   That's the whole dependency surface — no ML libraries, no LLM
   client, nothing multimodal. If a change of yours needs something
   heavier than that, it almost certainly belongs in kal-in instead
   of here.
3. Install the local git hook (once per clone):
   ```
   python3 scripts/install_git_hooks.py
   ```
   Rejects a commit that leaves a skill with modified content but a
   stale `skill.sig` — a `ruff --fix` reordering imports in
   `skills/*/tool.py` already broke this in practice, in kal-in (see
   its `docs/HISTORY.md`, "Reconciliación con 3 commits remotos + bug
   real de firmas rotas"). Without this hook, you only find out once
   the full suite or CI fails, not before committing.
4. Run the tests:
   ```
   python -m pytest tests/ -q
   ```
   Same command CI runs (367 tests today). A handful need Docker
   running (`requires_docker` in `tests/conftest.py`) — those skip
   themselves automatically when it isn't available.
5. Lint (same check CI enforces — real errors only, not a style
   opinion):
   ```
   python -m ruff check --select=E9,F .
   ```
6. Open a pull request against `main`.

**Where things live**, if you're not sure where a change belongs:
- `kernel/` — sandboxing, permissions, the Skill registry, the Kernel
  Bus, the resource broker. Pure security infrastructure: no LLM, no
  ML, no agent logic. Zero dependency on anything agent-specific —
  this is deliberate, keep it that way (verified by grep, not just
  convention: `import agent_core`/`import tool_integration` both fail
  here with `ModuleNotFoundError`).
- `sdk/` — the public API a Skill imports (`Tool`, `ToolManifest`,
  `Artifact`, `Permission`, `call()`). 100% stdlib on purpose: this
  package gets copied as-is into every Skill's Docker container (see
  `kernel/registry/sandboxed_skill.py`), so it can never gain a
  dependency that isn't already inside the container.
- `audit/` — the hash-chained, tamper-evident audit log every
  sensitive kernel action writes to.
- `code_analysis/` — AST-level static validation of dynamically
  proposed tool code, run before it ever reaches a sandbox.
- `skills/` — a handful of first-party Skills bundled with the
  kernel itself (system info, QR codes, and thin wrappers around
  Kernel Services for image/audio/download) — mostly reference
  implementations and integration-test fixtures, not a product
  catalog. The real, growing Skill Market lives in kal-in.
- `tests/` — mirrors the module being tested (`test_docker_runner_*.py`
  → `kernel/lifecycle/docker_runner.py`, etc.). A `requires_docker`
  test needs Docker running and skips itself otherwise.

A PR that changes behavior should come with a test that would have
failed before the change — this repo's `docs/HISTORY.md` is a log of
real bugs found in actual use (most inherited from kal-in's own
history before the split, some found here since), each with the test
that now guards against it; that's the standard a new contribution is
held to, not 100% coverage for its own sake.

## Keeping kal and kal-in in sync

kal-in embeds its own copy of `kernel/`, `sdk/`, `audit/`, and
`code_analysis/` — it does not depend on the `kal` package (see the
note at the top of this file). That means a fix made in one repo
**never reaches the other on its own**. This has bitten this project
for real, more than once: K-2 (a symlink-based host file read) sat
unfixed in kal for two weeks after being fixed in kal-in, found only
by a manual audit; the same thing happened in reverse with M-12
(unkeyed audit log hash chain) and the pre-commit skill-signature
check documented above — both originated in kal-in and had to be
found and ported here separately, by hand, well after the fact.

If your change touches `kernel/`, `sdk/`, `audit/`, `code_analysis/`,
or a Skill that exists in both repos by name (check
`skills/` in each): before calling the change done —
1. Check whether the equivalent file/logic exists in the other repo.
2. If it does, apply the equivalent fix there too, in the same
   sitting — not as a "port this later" note. Adapt comments that
   reference file paths or audit IDs specific to one repo, but keep
   the same underlying protection.
3. Run that repo's own test suite and lint independently — don't
   assume "it worked here, it'll work there." Different Python
   version floors and slightly different surrounding code are real
   sources of divergence on their own (see kal-in's `docs/HISTORY.md`,
   M-9: a lockfile resolved against the wrong Python version almost
   shipped).
4. Commit and push to both repos, and reference the sibling commit's
   hash in the second commit message once it exists — `git log` alone
   should be able to answer "did this get ported?" without anyone
   having to remember.

`kal-in`'s `scripts/check_kernel_drift.py` (`.github/workflows/kernel_drift.yml`,
daily + on demand) is the safety net for whatever slips through this,
not the primary mechanism — it only reports divergence, it never
fixes anything, and only kal-in runs it today (nothing currently
checks from kal's side outward). Run it locally at any time with:
```
python3 scripts/check_kernel_drift.py --kal-repo /path/to/local/kal
```

If your change is small and well-scoped, look for an issue labeled
**good first issue** — those are picked to be understandable without
reading the whole codebase first.

## Reporting a security issue

This is a security kernel — if you find a way to escape the sandbox,
bypass a permission check, or otherwise get code to do something the
kernel is supposed to prevent, please open an issue describing it.
There's no dedicated private disclosure channel yet at this project's
current size; treat that as a known gap, not a reason to stay quiet.
