## OVP Governance Trigger

When the user says `orchestration mode`, `governance mode`, `OVP governance`,
`legal step`, `policy gate`, `next legal action`, or `implementation handoff`,
read `docs/ai-workflow/README.md` and, for this device-control repository,
`docs/ai-workflow/governance-trigger.md` before implementation.

Treat the active native Goal as the operator control plane. Refresh `origin/main`
and preserve dirty user worktrees; use one coherent branch and pull request for
one accepted slice. Do not perform live-device scans, device mutations,
credential operations, firmware updates, deployments, or other external effects
unless the active Goal explicitly establishes that effect and its recovery
boundary.
