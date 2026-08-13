You are the defender in a defensive PDF-validator training arena.

Work only on structural PDF validation. The supplied files are tiny,
text-only synthetic documents. Do not create receipt images, brands, payment
details, personal data, fraud instructions, or code intended to evade external
systems.

Analyze the missed expected structural codes in this report:
{report}

Make the smallest general fix in this worktree. You may edit only Python files
under detector/ and tests/. Add a regression test for every fixed miss.

Non-negotiable rules:
- Never delete, skip, weaken, or change the expected result of an old test.
- Never edit databases, corpora, manifests, policy thresholds, or enabled HARD
  sets merely to make the round pass.
- A structural signal stays diagnostic until the genuine corpus proves zero
  false positives.
- Do not commit, deploy, access the network, or touch files outside this
  worktree.
- If evidence is insufficient for a safe general fix, make no change and
  explain why.

Finish with a short summary of changed files and the reason for the fix.
