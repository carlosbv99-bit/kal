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
3. Run the tests:
   ```
   python -m pytest tests/ -q
   ```
   Same command CI runs (367 tests today). A handful need Docker
   running (`requires_docker` in `tests/conftest.py`) — those skip
   themselves automatically when it isn't available.
4. Lint (same check CI enforces — real errors only, not a style
   opinion):
   ```
   python -m ruff check --select=E9,F .
   ```
5. Open a pull request against `main`.

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

If your change is small and well-scoped, look for an issue labeled
**good first issue** — those are picked to be understandable without
reading the whole codebase first.

## Reporting a security issue

This is a security kernel — if you find a way to escape the sandbox,
bypass a permission check, or otherwise get code to do something the
kernel is supposed to prevent, please open an issue describing it.
There's no dedicated private disclosure channel yet at this project's
current size; treat that as a known gap, not a reason to stay quiet.
