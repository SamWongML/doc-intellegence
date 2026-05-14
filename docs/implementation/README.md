# Implementation Docs

Per-phase plan for the Doc-Search MCP system. Designed for minimal context: each session loads only one phase file (+ shared if needed).

- **Progress tracker:** [/PROGRESS.md](../../PROGRESS.md) — open this first
- **Architecture & repo layout:** [architecture.md](architecture.md) — first session only
- **Shared contracts (models, schema, clients):** [contracts.md](contracts.md) — load when a phase touches them
- **Phases:** [phase-0](phase-0.md) · [phase-1](phase-1.md) · [phase-2](phase-2.md) · [phase-3](phase-3.md) · [phase-4](phase-4.md) · [phase-5](phase-5.md) · [phase-6](phase-6.md)

Build order: `0 → 1 → 2 → 4 → 5 → 6`. Phase 3 (PDF/Office) only if sources need it.
