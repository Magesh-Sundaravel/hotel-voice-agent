---
name: grill-me
description: Stress-test a feature plan before any code is written. Use at the start of every feature (step 1 of the CLAUDE.md workflow), or when the user says "grill me" or asks to challenge a plan.
---
# Grill the plan

Interview the user about the plan until there are no open questions. Do not write code or docs during this skill.

1. Restate the plan in three to five lines: the goal, the tools touched, the data written.
2. Ask one question at a time, hardest first. Wait for the answer before the next one. Cover:
   - Caller experience: what the agent says, in Italian and English, on success and on each failure. Is it one or two spoken sentences, one question at a time?
   - Tool contract: inputs, outputs, every `reason`, side effects, idempotency key (see docs/tools.md and .claude/rules/tools.md).
   - Latency: can it answer in under ~1.5 s? If not, what is the filler line or background job?
   - PII: what reaches logs and Langfuse? Only `guest_id` in logs; phones and emails masked in traces (.claude/rules/data.md).
   - Data: which tables change, does it need a migration, does it stay inside src/db/?
   - Decisions: does it contradict anything in docs/decisions/? If so, stop and ask before going on.
   - Evals: which IT and EN cases prove it works, and which existing cases could regress?
3. When the user's answer is vague, ask again with a concrete example ("a caller says X, what happens?").
4. End with a short summary: the agreed plan, the decisions made, and anything left open. That summary is the input to the docs/tools.md contract.
