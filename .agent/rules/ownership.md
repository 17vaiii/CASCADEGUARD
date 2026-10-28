<!-- OWNER: P1 | STATUS: ACTIVE -->
# STRICT OWNERSHIP RULES (non-negotiable)

- **Roles:**
  - **P1** Grid Simulation and Search Lead (Critical path, currently active)
  - **P2** Cloud, Data and Platform Lead
  - **P3** Cascade ML Lead
  - **P4** Theft and Loss Analytics Lead
  - **P5** Optimization, RAG, LLM and Dashboard Lead

- **Right now only P1 files may be created, edited or deleted.** Do NOT modify any file owned by P2, P3, P4 or P5, even for a "small fix", refactor, import change or formatting.
- The only exception is the **one-time scaffold** in Section 3, which creates placeholder files (header comment only) for other roles. After the scaffold, those files are LOCKED.
- You may **read** other roles' files. If a task needs a change in a locked file, STOP, tell the user which file and what change, and let the user hand it to the owner. Do not make the change.
- Every file starts with: `# OWNER: Px | NEEDS: Py | STATUS: LOCKED (until P1 handoff done)` or `ACTIVE` for P1 files.
- Never change a frozen contract in `contracts/`. Propose changes in `docs/p1/` instead.
- Before any edit, state the file path and its owner. If the owner is not P1, refuse and explain.
- Pre-commit hook (`scripts/check_ownership.py`) fails if staged files belong to a role other than the current role set in `.agent/role`.
