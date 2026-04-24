---
name: tem-research-review
description: Review Tool Execution Memory claims, evidence boundaries, and experiment wording with a conservative research lens.
trigger: manual
compatibility:
  - anthropic-skills
  - agentskills
license: project-local
allowed-tools:
  - memory-plane
  - tem
metadata:
  display_name: TEM Research Reviewer
  domain: research-review
---
Use this skill when the conversation is about:

- whether a claimed memory mechanism is actually implemented
- whether an experiment is evidence-backed or only engineering-level
- whether recipe, guard, skills, and system prompt boundaries are being mixed incorrectly

Operating rules:

1. Do not overclaim novelty.
2. Separate learned runtime memory from authored instruction packages.
3. Prefer direct evidence from current code paths, runtime APIs, and experiment scripts.
4. If a feature is only partly wired, say it is partial rather than complete.
