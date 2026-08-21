---
title: SPEED
description: High-fidelity orchestration for AI coding agents.
template: splash
hero:
  tagline: High-fidelity orchestration for AI coding agents.
  image:
    file: ../../assets/logo.svg
  actions:
    - text: Get Started
      link: /docs/getting-started/
      icon: right-arrow
      variant: primary
    - text: View on GitHub
      link: https://github.com/speed-org/SPEED
      icon: external
---

import { Card, CardGrid } from '@astrojs/starlight/components';

## The Four Pillars of SPEED

<CardGrid stagger>
	<Card title="Tutorials" icon="open-book">
		Start with [The 15-Minute Feature](/docs/getting-started/) to see SPEED in action.
	</Card>
	<Card title="How-to Guides" icon="setting">
		Learn how to [write high-fidelity specs](/docs/writing-specs/) and [troubleshoot failures](/docs/troubleshooting/).
	</Card>
	<Card title="Reference" icon="document">
		Deep dive into [CLI commands](/docs/api/cli/), [configuration schemas](/docs/api/config/), [language support](/docs/api/language-support/), and the [agent fleet](/docs/api/agents/).
	</Card>
	<Card title="Explanation" icon="information">
		Understand the [design philosophy](/docs/design-philosophy/) and the [3-Layer context pipeline](/docs/context-pipeline/).
	</Card>
</CardGrid>

## Orchestration Above Exploration

SPEED moves the heavy lifting of orientation from the agent to the infrastructure. By providing high-fidelity, pre-computed context, we eliminate hallucinations and ensure deterministic output.

- **Zero Hallucination**: Agents implementation is grounded in the Codebase Semantic Graph.
- **Parallel Execution**: Complex features are decomposed into independent, parallel task streams.
- **Automated Verification**: Every turn is gated by linters, tests, and coherence checkers.
