# Proportional Drafting

Use the same core structure for every artifact and vary only the depth inside
its sections. Treat proportionality as an internal authoring judgment. Never ask
the user to classify the work by size, and never expose a size label in the
generated artifact.

## Decide depth from the requirement

Keep content concise when the change affects one primary user journey, remains
local and reversible, preserves existing contracts, and introduces no material
operational or control risk. A concise PRD will commonly need:

- one hypothesis;
- one to three user stories;
- three to seven requirements with embedded acceptance;
- one to three genuine non-regression guardrails;
- only material delivery notes, risks, and open questions;
- one or two success signals.

Add depth only when confirmed information requires it:

- additional primary users, journeys, states, surfaces, or platforms;
- cross-team, vendor, migration, or breaking-contract dependencies;
- difficult rollout, rollback, recovery, or operational ownership;
- security, privacy, legal, financial, safety, or abuse exposure;
- novel product behavior or substantial discovery uncertainty;
- nondeterministic AI behavior or autonomous external actions.

When several of these signals are present, summarize the decision in the PRD
and link detailed Design, RFC, Eval, ADR, migration, rollout, or control
artifacts. Do not turn the PRD into all of those documents.

## Question rule

Infer depth from the requirement, repository evidence, and confirmed answers.
Ask a follow-up only when a missing fact would materially change scope, user
impact, safety, acceptance, or delivery. Ask about that fact directly, for
example:

- "Does this change existing stored data or only new records?"
- "Can the action be reversed after it is submitted?"
- "Does this affect one role or every workspace member?"

Do not ask "How large is this feature?", "Which PRD size do you want?", or any
equivalent classification question. Missing information becomes an explicit
open question when drafting can safely continue.

## Anti-bloat rules

- Keep every confirmed decision in one primary section; cross-reference instead
  of restating it.
- Do not create content to satisfy a target length or fill a table.
- Do not enumerate immaterial edge cases, generic risks, or standard engineering
  practices.
- Prefer a short statement that the existing baseline applies over invented
  feature-specific guardrails or metrics.
- Optimize for the shortest document that allows product, design, and
  engineering to make the next decision safely.
