# Contributing a Skill

🇬🇧 English | 🇪🇸 [Español](CONTRIBUTING.es.md)

Kal's Skill Market ([browse it here](https://carlosbv99-bit.github.io/kal/))
is this repository's `skills/` folder. Publishing a Skill means
opening a pull request against it.

## How to publish

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

## What's checked automatically, and what isn't

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

## Local sandbox, not a training-wheels API

Skills always run in an ephemeral, isolated Docker container per
call — no network, read-only filesystem, non-root, no standing
access to anything outside `/workspace` — regardless of how they were
installed. See [README.md](README.md) for the full architecture.
