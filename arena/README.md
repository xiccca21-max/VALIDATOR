# PDF Validator Arena

Defensive training loop for structural PDF validation:

1. A tool-less generator agent chooses allowlisted byte-level mutations.
2. A deterministic factory creates tiny, non-visual synthetic PDFs.
3. The production route and structural audit evaluate every candidate.
4. Misses increase the generator's strategy weights.
5. A defender agent proposes a fix in an isolated Git worktree.
6. Deterministic unit and genuine-corpus gates accept or reject the candidate.

The arena never creates visual receipts, bank branding, payment details,
personal data, QR codes, JavaScript, attachments, or network links. Agents
cannot weaken the judge or access an immutable holdout.

## Commands

Offline generator and judge smoke:

```powershell
py -3.13 -m arena.orchestrator --rounds 1
```

Full agent loop after configuring `CURSOR_API_KEY`:

```powershell
.\arena\run.ps1 -Rounds 5
```

Bounded hourly batches:

```powershell
.\arena\run.ps1 -Rounds 5 -Forever -IntervalSeconds 3600
```

Each invocation is capped by `config.json`. Defender changes are committed only
to isolated `arena/round-NNNN` branches. The arena never merges, pushes, or
deploys them automatically.

## Fail-closed conditions

- Existing production changes are uncommitted.
- An agent edits anything except Python under `detector/` or `tests/`.
- The diff exceeds 1,000 lines.
- Compilation, pytest, or the genuine-corpus zero-FP gate fails.
- A run crashes, times out, or changes a database/corpus/policy artifact.

Runtime PDFs, reports, and adaptive state are ignored by Git. API keys are read
only from the environment and are never written to reports.
