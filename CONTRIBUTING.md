# Contributing to Kal

🇬🇧 English | 🇪🇸 [Español](CONTRIBUTING.es.md)

There are two different things you might want to contribute: **code**
to the kernel itself (`kernel/`, `agent_core/`, `sdk/`, tests), or a
**Skill** to the Skill Market. They have different workflows, covered
in the two sections below.

## Contributing code

1. Fork the repo and clone it locally.
2. Set up a virtualenv and install dependencies:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-core.txt -r requirements-dev.txt
   ```
   `requirements-multimodal.txt` (diffusers, faster-whisper, piper-tts,
   playwright, etc. — several GB) is only needed if you're touching
   image/audio/video/STT/browser code specifically; most of the test
   suite runs without it (those tests skip themselves via
   `pytest.importorskip(...)` when it's missing).
3. Run the tests:
   ```
   python -m pytest tests/ -q
   ```
   This is the same command CI runs. A handful of tests need Docker
   running (`requires_docker` in `tests/conftest.py`) or a real Ollama
   instance (`tests/test_*_integration.py`) — those skip themselves
   automatically when the dependency isn't available.
4. Lint (same check CI enforces — real errors only, not a style
   opinion):
   ```
   python -m ruff check --select=E9,F .
   ```
5. Open a pull request against `main`.

**Where things live**, if you're not sure where a change belongs:
- `kernel/` — sandboxing, permissions, the Skill registry, the Kernel
  Bus, Kernel Services (image/audio/STT). Zero dependency on
  `agent_core/` — this is deliberate, keep it that way.
- `agent_core/` — the LLM agent loop, orchestrator, memory, the
  Conversation Engine. Depends on `kernel/`/`sdk/`, never the reverse.
- `sdk/` — the public API a Skill imports (`Tool`, `ToolManifest`,
  `Artifact`, `Permission`, `call()`). Pure stdlib, on purpose: this
  package gets copied as-is into every Skill's Docker container (see
  `kernel/registry/sandboxed_skill.py`), so it can never gain a
  dependency that isn't already inside the container.
- `tests/` — mirrors the module being tested (`test_agent_loop.py` →
  `agent_core/llm/agent_loop.py`, etc.). A `*_integration.py` suffix
  means it needs a real service (Ollama, Docker) and skips itself
  otherwise.

A PR that changes behavior should come with a test that would have
failed before the change — this repo's `docs/HISTORY.md` is a long,
honest log of real bugs found in actual use, each with the test that
now guards against it; that's the standard a new contribution is held
to, not 100% coverage for its own sake.

If your change is small and well-scoped, look for an issue labeled
**good first issue** — those are picked to be understandable without
reading the whole codebase first.

## Contributing a Skill

Kal's Skill Market ([browse it here](https://carlosbv99-bit.github.io/kal/))
is this repository's `skills/` folder. Publishing a Skill means
opening a pull request against it.

### How to publish

1. Fork this repo, add your Skill under `skills/<your-skill-name>/`
   (`skill.yaml` + your code — see any existing skill under `skills/`
   for the manifest format).
2. Sign it with your **own** keypair, never someone else's:
   ```
   python3 scripts/sign_skill.py skills/<your-skill-name>/ --key-dir <your-key-dir>
   ```
   Keep `<your-key-dir>` somewhere persistent — signing a future
   version with the same directory attributes it to the same author.
3. Open a pull request.

### What's checked automatically, and what isn't

A CI check (`scripts/validate_skills.py`) runs on every pull request
and blocks merging until it passes. It verifies **package integrity**
only:
- Your `skill.yaml` parses correctly.
- Your `skill.sig` is present and cryptographically verifies against
  the current contents of your Skill's folder.

It does **not** check, and cannot check:
- Whether your code does what the description says.
- Whether the permissions you declared make sense for what the Skill
  actually does.
- Whether the Skill is safe, well-written, or malicious.

A valid signature proves the package wasn't altered since you signed
it — it says nothing about whether the content should be trusted.
That's why every pull request also gets a **manual review by a
maintainer** before merging, today entirely a human judgment call, not
an automated one. This is a real bottleneck at this project's current
size, not a scalability solution — it may evolve as the community
grows.

### Local sandbox, not a training-wheels API

Skills always run in an ephemeral, isolated Docker container per
call — no network, read-only filesystem, non-root, no standing
access to anything outside `/workspace` — regardless of how they were
installed. See [README.md](README.md) for the full architecture.
