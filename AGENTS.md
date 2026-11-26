# SITARA — Mandatory Instructions for AI Coding Agents

Before editing code, read:

- `README.md`
- `docs/PRD.md`
- `docs/system_design.md`
- `docs/architecture.md`
- `docs/agents.md`
- `docs/TEST_STRATEGY.md`
- `docs/DEFINITION_OF_DONE.md`
- Relevant decisions in `docs/ARCHITECTURE_DECISIONS.md`

## Non-negotiable rules

1. Use TDD: write a meaningful failing test first, implement the smallest correct change, refactor, and run focused plus regression tests.
2. Never weaken/delete tests or disable lint/security gates merely to obtain a green result.
3. Never claim a command, test, scan, or build passed unless it was executed and the result observed.
4. Never commit `.env`, credentials, tokens, private keys, production data, or confidential meeting content. Use synthetic fixtures.
5. Do not test destructively against production. Use versioned Alembic migrations and isolated test databases.
6. Enforce authorization server-side for every endpoint, object, search result, export, and file download.
7. PIC must not access full restricted minutes/Decision Brief or mutate official status, including by direct API request.
8. During a live meeting, active Rektor, Warek, and Secretariat users may edit minutes. The per-meeting notetaker identity is recorded but is not an exclusive edit gate; use revision concurrency controls. PIC and Super Admin remain unable to read full minutes.
9. Authorized Secretariat and Manager Legal users have the same operational authority, including official task status changes. PIC and Super Admin do not inherit this business permission.
10. A decision may generate zero or multiple action items. Each task has one active main PIC and may have supporting PICs.
11. AI/OCR output remains a draft until a permitted human reviews it; never submit confidential data to an external service without approval.
12. Keep changes small and layered. Do not add dependencies or design patterns without a concrete need.
13. Review `git diff`, tests, migration safety, and secrets before reporting completion.

Follow the detailed workflows, test commands, tool policy, security rules, and reporting format in `docs/agents.md`. If instructions or requirements conflict, do not silently choose: report the conflict and ask for clarification where it changes product/security behavior.
