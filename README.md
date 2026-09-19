# Kal

🇬🇧 English | 🇪🇸 [Español](README.es.md)

> A kernel doesn't ask an AI agent's code if it can be trusted — it
> makes sure it never has to be.

**A pure security microkernel for AI agent capabilities — no agent, no LLM, no ML bundled.**

Every AI agent framework eventually has to answer the same question:
when an agent's code goes wrong — a bad tool call, a compromised
dependency, a prompt injection that talks it into something it
shouldn't do — what actually stops it? Too often the honest answer is
"nothing built in, we just trust the code." Kal is built around the
opposite answer: a security microkernel that mediates everything an
agent — or any piece of code running as one of its tools — is allowed
to touch, enforced from outside that code, so no individual Skill has
to be trusted for the whole system to stay safe.

Kal was extracted from [kal-in](https://github.com/carlosbv99-bit/kal-in)
(kal's own reference agent) in September 2026, once it became clear the
two needed to be independently usable: a kernel that mediates what any
agent — kal-in's own reference agent, or a third-party one — is allowed
to do, without shipping a specific agent's tools bundled inside it. The
first consumer of this separation is [Likay-OS](https://github.com/Kevindelb/Likay-OS),
an operating system for AI agents that needs a kernel it can mount
underneath *any* agent without the kernel colliding with that agent's
own toolset.

## What's in here

- **Access Manager / Permission Cascade** (`kernel/permissions/`) —
  tiered, deny-by-default access to filesystem and network, with
  explicit human approval gates.
- **Sandbox** (`kernel/lifecycle/`) — every untrusted skill runs in an
  isolated, non-root Docker container, regardless of where it came
  from.
- **Tool Registry** (`kernel/registry/`) — generic registration,
  versioning, rollback and cryptographic signature verification for
  tools/skills. Deciding *which* tools exist by default is agent
  policy, not kernel mechanism — this repo registers none.
- **Audit Log** (`audit/`) — hash-chained, tamper-evident record of
  every sensitive action.
- **Kernel Service Bus** (`kernel/api/`) — generic dispatch-by-name
  protocol + Unix socket server so a sandboxed skill can call out to a
  service without ever seeing a real filesystem path.
- **Resource Broker** (`kernel/broker/`) — tracks and evicts resources
  under memory pressure; blind to anything an agent doesn't explicitly
  register with it (see Likay-OS's roadmap for closing that gap for
  externally-mediated agents).
- **SDK** (`sdk/`) — the stable, versioned, 100%-stdlib public surface
  a Skill or agent uses to talk to the kernel (`Tool`, `ToolManifest`,
  `Artifact`, `Permission`) — never kernel internals directly.
- **Static code analysis** (`code_analysis/`) — AST-level validation of
  dynamically-proposed tool code before it ever reaches a sandbox.

This repo has **zero** dependency on any LLM, ML library, or specific
agent framework — verified, not assumed: `import agent_core` and
`import tool_integration` both fail with `ModuleNotFoundError` here.

## What's NOT in here

Anything that decides *what an agent does* — the reasoning loop, tool
implementations (image/audio/video generation, browser automation,
memory), model selection, prompts — lives in
[kal-in](https://github.com/carlosbv99-bit/kal-in), kal's own reference
agent built on top of this kernel. A third-party agent could equally be
built on top of this kernel instead.

## Status

Extracted with git history preserved for every file that moved here
(`git log --follow` on any path under `kernel/`/`sdk/`/`audit/` shows
its history from before the split). 367 tests, standalone, installing
only `requirements-core.txt` — no agent code, no ML libraries.

## Get involved

This is a young, actively developed project, and there's real room to
contribute — you don't need to be the one who wrote an agent framework
to have something to add here. Security review, testing the sandbox
against cases we haven't thought of, and just asking hard questions
about the threat model are all genuinely useful.

- Open an [issue](https://github.com/carlosbv99-bit/kal/issues) to
  propose something, report a bug, or ask where to start.
- If you want to write or talk about this project, this README and
  the code itself are the primary source — every claim here is meant
  to be checkable against what's actually in the repo. That same level
  of care is the day-to-day working method: every change gets
  reviewed and verified in ongoing coordination with Claude
  (Anthropic), not just documented after the fact.

License: [Apache 2.0](LICENSE).
