# Magewell AIO Control governance adapter

This repository inherits OVP governance from the central authority at
[`blaze-ovp/docs/ai-workflow`](https://github.com/WestonConat/blaze-ovp/tree/main/docs/ai-workflow).
It is an adapter, not a replacement for that authority.

For a governance trigger, read:

1. `AGENTS.md`;
2. `docs/ai-workflow/governance-trigger.md`; and
3. the central governance trigger, working-thread authority, authorization,
   proportionality, convergence, evidence, orchestration, and legal/policy
   documents named there.

`origin/main` is the governing repository baseline. Preserve unrelated dirty
worktrees, use the smallest coherent branch/PR topology, and run `just check`
before repository publication or closeout.

The app controls network devices. Read-only discovery may contact only the
operator-approved `ALLOWED_SUBNET`; device settings, naming, credentials, and
firmware changes remain separate effect boundaries and require explicit active
Goal scope. No adapter wording authorizes a device effect.
