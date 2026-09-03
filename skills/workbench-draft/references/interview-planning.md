# Contextual Interview Planning

Treat the PRD structure as fixed coverage, not as a fixed questionnaire. Build
the next question from the requirement, repository evidence, confirmed answers,
and the material decision still missing.

## Planning loop

1. Extract known facts, supported inferences, and unresolved decisions.
2. Check which PRD coverage areas already have enough evidence.
3. Score each area using evidence confidence and decision impact. Activate only
   unresolved areas that can materially change user impact, behavior, scope,
   acceptance, safety, success, or delivery.
4. Generate the provisional PRD immediately, marking inferred and unresolved
   content honestly.
5. Ask one plain-language question about the highest-value gap.
6. Re-plan after every confirmed answer because it may resolve or reveal other
   coverage areas.
7. Stop when remaining uncertainty can safely be reviewed in the draft or
   recorded under Open Questions.

Stable coverage IDs support persistence and traceability. They do not require a
question to be asked, and they must not appear as an eight-question promise to
the user. The active plan may grow or shrink as confirmed evidence changes.

Surface no more than three clarifications. Rank candidates using uncertainty,
decision impact, and downstream leverage. Confidence alone must not block a
draft: low-confidence, low-impact content becomes an inference or open question;
low-confidence, high-impact content becomes a clarification.

## Question-writing rules

- Refer to the actual feature and behavior already described.
- Resolve one product decision at a time. Group states only when they are parts
  of the same decision boundary.
- Do not assume roles, permissions, platforms, integrations, or workflows that
  do not exist.
- Use product language instead of framework language such as "jobs to be done"
  unless the user already uses it.
- State a meaningful contrast when it helps the user decide.
- Ask about an unknown fact directly; never ask the user to classify the
  feature or document.
- Do not ask for information already present in the requirement or repository.
- Generate a suggested answer only from evidence that actually resolves the
  question. Otherwise present the question without a pseudo-answer assembled
  from unrelated earlier text.

## Contextual examples

For authentication in a single-role task application, ask:

> Which authentication method should the first release support: username and
> password, Google sign-in, another provider, or a specific combination?

Then resolve backward compatibility with a user-confirmed decision:

> How are you thinking of rolling out authentication to existing users? How
> will they set up authentication, and what should happen to their existing
> account and data?

Do not infer sharing, roles, credential distribution, or migration behavior.
Only ask about sharing when the requirement or repository shows that sharing
already exists or is part of the requested scope. Because authentication can
lock existing users out of their data, keep the rollout answer unresolved until
the user confirms it unless durable evidence provides the complete decision.

For a local task-priority change, ask:

> Who needs to see or change priority, and should every existing task user have
> the same access?

Do not request a persona catalog if the application has one undifferentiated
user.

## Conditional coverage

Always resolve the problem, intended user outcome, essential behavior,
acceptance, and success signal. Activate explicit scope or delivery/control
questions only when evidence suggests multiple workflows, access boundaries,
migration, external dependencies, difficult reversal, operational rollout,
sensitive data, AI autonomy, financial impact, compliance, or comparable risk.

If a conditional area is inactive, compose the relevant PRD section concisely
from confirmed boundaries or state that no feature-specific item was identified.
Do not make the user answer a generic question merely to fill the section.
