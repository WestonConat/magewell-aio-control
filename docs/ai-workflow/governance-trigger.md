# Device-control governance trigger

This high-risk adapter applies when a human uses an OVP governance trigger or
when work touches device discovery, credentials, settings, naming, firmware,
repository publication, or a linked Notion task.

Load the central authority from:

- `governance-trigger-contract.md`
- `working-thread-authority.md`
- `authorization-and-approval-policy.md`
- `work-cycle-proportionality-policy.md`
- `repo-state-and-convergence-policy.md`
- `evidence-and-validation-policy.md`
- `orchestration-mode.md`
- `legal-and-policy-gates.md`

Before a code-bearing change, refresh `origin/main`, inspect the worktree, and
keep device effects out of scope unless the active Goal explicitly permits them.
Before publishing or closeout, validate the exact candidate, review the shared
device-control surface, and preserve unrelated dirty work. `just check` is the
required repository validation gate for this project.
