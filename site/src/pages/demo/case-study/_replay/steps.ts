import {
  specs, planAudits, validationFindings, tasks,
  reviews, secretsScan, guardianPostReview,
  task3Fixes, coherenceCreatedTask4,
  coherence, integration, traceability,
  guardianPostIntegration, observations, conventions,
} from '../_data';

/* ── Types ─────────────────────────────────── */

export type Phase = 'define' | 'audit' | 'execute' | 'review' | 'correct' | 'coherence' | 'integrate' | 'learn';
export type LineColor = 'default' | 'accent' | 'green' | 'amber' | 'red' | 'dim';

export interface TerminalLine {
  text: string;
  color: LineColor;
  indent?: number;
}

export interface FileContent {
  path: string;
  language: string;
  lines: string[];
  highlightLines?: number[];
}

export interface ReplayStep {
  id: string;
  phase: Phase;
  delay: number; // ms before this step shows (at 1x)
  terminal: TerminalLine[];
  file?: FileContent | null;
}

/* ── Step builder ──────────────────────────── */

export function buildSteps(): ReplayStep[] {
  const s: ReplayStep[] = [];
  let id = 0;
  const step = (phase: Phase, delay: number, terminal: TerminalLine[], file?: FileContent | null): void => {
    s.push({ id: String(id++), phase, delay, terminal, file });
  };

  // ═══════════════════════════════════════════
  // DEFINE — spec authoring
  // ═══════════════════════════════════════════

  step('define', 600, [
    { text: '> speed run --issue 11480 --branch 1.9.x', color: 'accent' },
  ], {
    path: 'github.com/appwrite/appwrite/issues/11480',
    language: 'markdown',
    lines: [
      '# #11480 — sort-auth-by-last-activity',
      '',
      'The accessedAt field exists in the database with a proper',
      'index, but the Users API query validator doesn\'t expose it.',
      '',
      'Teams that need to identify inactive accounts, build admin',
      'dashboards, or run engagement analysis must implement custom',
      'tracking logic on their side.',
      '',
      '## Repository',
      '',
      'appwrite/appwrite',
      '55K+ stars · 451 contributors · 33K+ commits',
      'TypeScript 64.4% · PHP 34.2%',
      '',
      '## Branch',
      '',
      '1.9.x',
    ],
  });

  step('define', 400, [
    { text: '', color: 'default' },
    { text: '── Define ────────────────────────────────', color: 'dim' },
    { text: 'Writing product spec...', color: 'default' },
  ], {
    path: specs.product.filename,
    language: 'markdown',
    lines: [
      '# Product Spec: sort-auth-by-last-activity',
      '',
      '## Problem',
      specs.product.problem,
      '',
      '## Personas',
      ...specs.product.personas.map(p => `- **${p.name}** (${p.role}): ${p.useCase}`),
      '',
      '## User Stories',
      ...specs.product.userStories.map(s => `- [${s.priority}] ${s.story} — ${s.query}`),
      '',
      '## Out of Scope',
      ...specs.product.scopeOut.map(s => `- ${s}`),
    ],
  });

  step('define', 300, [
    { text: '✓ Product spec written', color: 'green' },
    { text: `  ${specs.product.personas.length} personas, ${specs.product.userStories.length} user stories, ${specs.product.scopeOut.length} scope-outs`, color: 'dim' },
    { text: 'Writing design spec...', color: 'default' },
  ], {
    path: specs.design.filename,
    language: 'markdown',
    lines: [
      '# Design Spec: sort-auth-by-last-activity',
      '',
      '## Intent',
      `> ${specs.design.intent}`,
      '',
      '## Do Not',
      ...specs.design.doNot.map(d => `- ${d}`),
      '',
      '## States',
      ...specs.design.states.map(s => `| ${s.name} | ${s.description} |`),
      '',
      '## Implementation Notes',
      ...specs.design.notes.map(n => `- ${n}`),
    ],
  });

  step('define', 300, [
    { text: '✓ Design spec written', color: 'green' },
    { text: `  ${specs.design.states.length} states, ${specs.design.doNot.length} constraints`, color: 'dim' },
    { text: 'Writing tech spec...', color: 'default' },
  ], {
    path: specs.tech.filename,
    language: 'markdown',
    lines: [
      '# Tech Spec: sort-auth-by-last-activity',
      '',
      '## Query Types',
      ...specs.tech.queryTypes.map(q => `- ${q.type}: ${q.example}`),
      '',
      '## File Impact',
      ...specs.tech.fileImpact.map(f => `- ${f.file} — ${f.change}`),
      '',
      '## Key Decisions',
      ...specs.tech.keyDecisions.map(d => `- ${d.decision}: **${d.choice}** — ${d.rationale}`),
    ],
  });

  step('define', 200, [
    { text: '✓ Tech spec written', color: 'green' },
    { text: `  ${specs.tech.queryTypes.length} query types, ${specs.tech.fileImpact.length} files, ${specs.tech.keyDecisions.length} decisions`, color: 'dim' },
  ]);

  // ═══════════════════════════════════════════
  // AUDIT — spec consistency check
  // ═══════════════════════════════════════════

  step('audit', 500, [
    { text: '', color: 'default' },
    { text: '── Audit ─────────────────────────────────', color: 'dim' },
    { text: 'Auditing specs for consistency...', color: 'default' },
  ], {
    path: specs.tech.filename,
    language: 'markdown',
    lines: [
      '# Tech Spec: sort-auth-by-last-activity',
      '',
      '## Query Types',
      ...specs.tech.queryTypes.map(q => `- ${q.type}: ${q.example}`),
      '',
      '## File Impact',
      ...specs.tech.fileImpact.map(f => `- ${f.file} — ${f.change}`),
      '',
      '## Key Decisions',
      ...specs.tech.keyDecisions.map(d => `- ${d.decision}: **${d.choice}** — ${d.rationale}`),
    ],
  });

  for (const audit of planAudits) {
    step('audit', 200, [
      { text: `  ${audit.specType}: ${audit.status.toUpperCase()}${audit.estimatedTasks ? ` (${audit.estimatedTasks} tasks estimated)` : ''}`, color: audit.status === 'pass' ? 'green' : 'red' },
    ]);
  }

  for (const finding of validationFindings) {
    step('audit', 250, [
      { text: `  [${finding.severity.toUpperCase()}] ${finding.issue}`, color: finding.severity === 'warning' ? 'amber' : 'dim' },
    ]);
  }

  step('audit', 200, [
    { text: '✓ Audit complete — 3/3 specs passed, 1 warning', color: 'green' },
  ]);

  // ═══════════════════════════════════════════
  // EXECUTE — task planning + execution
  // ═══════════════════════════════════════════

  step('execute', 500, [
    { text: '', color: 'default' },
    { text: '── Execute ───────────────────────────────', color: 'dim' },
    { text: 'Decomposing into task DAG...', color: 'default' },
  ]);

  // Plan
  for (const task of tasks.slice(0, 3)) {
    const deps = task.dependsOn.length > 0 ? ` (depends: ${task.dependsOn.map(d => 'T' + d).join(', ')})` : ' (root)';
    step('execute', 150, [
      { text: `  T${task.id}: ${task.title}${deps}`, color: 'accent' },
    ]);
  }

  step('execute', 300, [
    { text: '✓ Plan: 3 tasks, DAG: T1 → [T2, T3]', color: 'green' },
  ]);

  // Execute T1
  step('execute', 400, [
    { text: '', color: 'default' },
    { text: `▶ T1: ${tasks[0].title}`, color: 'accent' },
    { text: `  model: ${tasks[0].model} | files: ${tasks[0].files.length} | budget: ${tasks[0].budget.total.toLocaleString()} tokens`, color: 'dim' },
  ], {
    path: tasks[0].files[0],
    language: 'php',
    lines: [
      '<?php',
      '',
      'namespace Appwrite\\Utopia\\Database\\Validator\\Queries;',
      '',
      'class Users extends Base {',
      '    public const ALLOWED_ATTRIBUTES = [',
      "        'name',",
      "        'email',",
      "        'phone',",
      "        'status',",
      "        'passwordUpdate',",
      "        'registration',",
      "        'emailVerification',",
      "        'phoneVerification',",
      "+       'accessedAt',  // ← SPEED added this",
      '    ];',
      '}',
    ],
    highlightLines: [14],
  });

  for (const gate of tasks[0].gateChecks) {
    step('execute', 80, [
      { text: `  ${gate.status === 'pass' ? '✓' : '⚠'} ${gate.name}`, color: gate.status === 'pass' ? 'green' : 'amber' },
    ]);
  }

  step('execute', 200, [
    { text: `✓ T1 complete — ${tasks[0].duration}s, ${tasks[0].budget.used.toLocaleString()} tokens used`, color: 'green' },
  ]);

  // Execute T2 + T3 in parallel
  step('execute', 400, [
    { text: '', color: 'default' },
    { text: `▶ T2: ${tasks[1].title}`, color: 'accent' },
    { text: `▶ T3: ${tasks[2].title}  (parallel)`, color: 'accent' },
  ], {
    path: tasks[1].files[0],
    language: 'php',
    lines: [
      '<?php',
      '',
      'public function testAccessedAtSortAndFilter(): void',
      '{',
      "    // Create users with distinct accessedAt timestamps",
      "    \$user1 = \$this->createUser('user1_' . uniqid());",
      "    \$user2 = \$this->createUser('user2_' . uniqid());",
      "    \$noActivity = \$this->createUser('noact_' . uniqid());",
      '',
      '    // Trigger accessedAt via authenticated requests',
      '    sleep(1);  // distinct second-precision timestamps',
      "    \$this->client->call('GET', '/account', [",
      "        'x-appwrite-session' => \$session1,",
      '    ]);',
      '',
      '    // Sort descending — most recent first',
      "    \$response = \$this->client->call('GET', '/users', [",
      "        'queries' => [Query::orderDesc('accessedAt')],",
      '    ]);',
      '',
      "    \$this->assertGreaterThan(0, \$response['total']);",
      '}',
    ],
  });

  // T2 gates
  for (const gate of tasks[1].gateChecks) {
    step('execute', 60, [
      { text: `  T2: ${gate.status === 'pass' ? '✓' : '⚠'} ${gate.name}`, color: gate.status === 'pass' ? 'green' : 'amber' },
    ]);
  }

  step('execute', 100, [
    { text: `✓ T2 complete — ${tasks[1].duration}s, ${tasks[1].budget.used.toLocaleString()} tokens`, color: 'green' },
  ]);

  // T3 gates
  step('execute', 200, [], {
    path: tasks[2].files[0],
    language: 'markdown',
    lines: [
      '# List Users',
      '',
      '## Queryable Attributes',
      '',
      '| Attribute | Type | Sort | Filter |',
      '|-----------|------|------|--------|',
      '| name | string | ✓ | ✓ |',
      '| email | string | ✓ | ✓ |',
      '| phone | string | ✓ | ✓ |',
      '| accessedAt | datetime | ✓ | ✓ |  ← NEW',
      '',
      '## Notes',
      '',
      '- accessedAt updates at most once per 24 hours per user.',
      '- Requests where another user is impersonating this account',
      '  do not update accessedAt.',
    ],
    highlightLines: [9],
  });

  for (const gate of tasks[2].gateChecks) {
    step('execute', 60, [
      { text: `  T3: ${gate.status === 'pass' ? '✓' : '⚠'} ${gate.name}`, color: gate.status === 'pass' ? 'green' : 'amber' },
    ]);
  }

  step('execute', 100, [
    { text: `✓ T3 complete — ${tasks[2].duration}s, ${tasks[2].budget.used.toLocaleString()} tokens`, color: 'green' },
  ]);

  // ═══════════════════════════════════════════
  // REVIEW — per-task code review
  // ═══════════════════════════════════════════

  step('review', 500, [
    { text: '', color: 'default' },
    { text: '── Review ────────────────────────────────', color: 'dim' },
  ]);

  for (const review of reviews.slice(0, 3)) {
    const verdict = review.verdict === 'approve' ? '✓ APPROVED' : '✗ CHANGES REQUESTED';
    const color: LineColor = review.verdict === 'approve' ? 'green' : 'red';

    step('review', 300, [
      { text: `T${review.taskId}: ${verdict} (${review.specChecks.satisfied}/${review.specChecks.total} spec checks)`, color },
    ]);

    for (const issue of review.issues) {
      const ic: LineColor = issue.severity === 'major' ? 'red' : issue.severity === 'minor' ? 'amber' : 'dim';
      step('review', 200, [
        { text: `  [${issue.severity.toUpperCase()}] ${issue.file.split('/').pop()}:${issue.line}`, color: ic },
        { text: `  ${issue.message}`, color: 'default', indent: 2 },
      ], {
        path: issue.file,
        language: issue.file.endsWith('.md') ? 'markdown' : 'php',
        lines: [
          `// Review finding at line ${issue.line}:`,
          `// [${issue.severity.toUpperCase()}]`,
          '',
          issue.message,
          ...('suggestion' in issue && issue.suggestion ? ['', `// Suggestion: ${issue.suggestion}`] : []),
        ],
        highlightLines: [3],
      });
    }
  }

  // Security scan
  step('review', 400, [
    { text: '', color: 'default' },
    { text: `⚠ Security scan: flagged ${secretsScan.flaggedContent}`, color: 'amber' },
    { text: `  ${secretsScan.file} lines ${secretsScan.flaggedLines.join(', ')}`, color: 'dim' },
  ]);

  step('review', 300, [
    { text: `  Diagnosis: ${secretsScan.diagnosis.slice(0, 80)}...`, color: 'dim' },
    { text: `✓ Resolved: ${secretsScan.resolution}`, color: 'green' },
  ]);

  // Guardian
  step('review', 400, [
    { text: '', color: 'default' },
    { text: 'Guardian post-review:', color: 'default' },
  ]);

  for (const flag of guardianPostReview.flags) {
    step('review', 250, [
      { text: `  [${flag.severity.toUpperCase()}] ${flag.description.slice(0, 100)}${flag.description.length > 100 ? '...' : ''}`, color: flag.severity === 'critical' ? 'red' : 'dim' },
    ]);
  }

  // ═══════════════════════════════════════════
  // CORRECT — self-correction
  // ═══════════════════════════════════════════

  // Corrected docs file — built up progressively with each fix
  const correctedDocsLines = [
    '# List Users',
    '',
    '## Queryable Attributes',
    '',
    '| Attribute | Type | Sort | Filter |',
    '|-----------|------|------|--------|',
    '| name | string | ✓ | ✓ |',
    '| email | string | ✓ | ✓ |',
    '| phone | string | ✓ | ✓ |',
    '| accessedAt | datetime | ✓ | ✓ |  ← NEW',
    '',
    '## Notes',
    '',
    '- accessedAt updates at most once per 24 hours per user.',
    '  High-frequency logins within the same 24-hour window',
    '  will not produce additional updates.',
    '- Requests where another user is impersonating this account',
    '  (indicated by a non-empty impersonatorUserId on the',
    '  session) do not update accessedAt.',
    '',
    '## Example',
    '',
    '```php',
    'use Appwrite\\Services\\Users;',
    '$users = new Users($client);',
    '$response = $users->list([',
    "    Query::orderDesc('accessedAt'),",
    ']);',
    '```',
  ];

  // Highlight indices per fix (0-indexed into correctedDocsLines)
  const fixHighlights: number[][] = [
    [13, 14, 15],     // Fix 1: removed env-var claim, added 24h clarification
    [16, 17, 18],     // Fix 2: fixed impersonator terminology
    [23, 24],         // Fix 3: fixed PHP SDK syntax
  ];

  step('correct', 500, [
    { text: '', color: 'default' },
    { text: '── Self-Correction ───────────────────────', color: 'dim' },
    { text: 'Re-executing T3 with review fixes...', color: 'default' },
  ]);

  let cumulativeHL: number[] = [];
  for (let f = 0; f < task3Fixes.length; f++) {
    const fix = task3Fixes[f];
    cumulativeHL = [...cumulativeHL, ...fixHighlights[f]];
    step('correct', 250, [
      { text: `  ✓ ${fix.what}`, color: 'green' },
      { text: `    ${fix.detail}`, color: 'dim' },
    ], {
      path: 'docs/references/users/list-users.md',
      language: 'markdown',
      lines: correctedDocsLines,
      highlightLines: [...cumulativeHL],
    });
  }

  step('correct', 400, [
    { text: '', color: 'default' },
    { text: '⚡ Coherence check found a semantic bug:', color: 'amber' },
    { text: `  ${coherenceCreatedTask4.reason.slice(0, 120)}...`, color: 'default' },
  ]);

  step('correct', 300, [
    { text: '  → Creating T4: Fix coherence issues', color: 'accent' },
  ]);

  // Execute T4 — show corrected test file with coherence fixes highlighted
  step('correct', 400, [
    { text: '', color: 'default' },
    { text: `▶ T4: ${tasks[3].title}`, color: 'accent' },
    { text: `  model: ${tasks[3].model} | files: ${tasks[3].files.length} | budget: ${tasks[3].budget.total.toLocaleString()} tokens`, color: 'dim' },
  ], {
    path: 'tests/e2e/Services/Users/UsersBase.php',
    language: 'php',
    lines: [
      '<?php',
      '',
      'public function testAccessedAtSort(): void',
      '{',
      "    \\$user1 = \\$this->createUser('user1_' . uniqid());",
      "    \\$user2 = \\$this->createUser('user2_' . uniqid());",
      '',
      '    // Trigger accessedAt via authenticated request',
      "    \\$this->client->call('GET', '/account', [",
      "        'x-appwrite-session' => \\$session1,",
      '    ]);',
      '',
      '    sleep(1);  // distinct second-precision timestamps',
      '',
      "    \\$this->client->call('GET', '/account', [",
      "        'x-appwrite-session' => \\$session2,",
      '    ]);',
      '',
      "    \\$response = \\$this->client->call('GET', '/users', [",
      "        'queries' => [Query::orderDesc('accessedAt')],",
      '    ]);',
      '',
      "    \\$this->assertEquals(\\$user2['\\$id'], \\$response['users'][0]['\\$id']);",
      '}',
    ],
    highlightLines: [7, 8, 9, 10, 12, 14, 15, 16],
  });

  for (const gate of tasks[3].gateChecks) {
    step('correct', 60, [
      { text: `  ${gate.status === 'pass' ? '✓' : '⚠'} ${gate.name}`, color: gate.status === 'pass' ? 'green' : 'amber' },
    ]);
  }

  step('correct', 200, [
    { text: `✓ T4 complete — ${tasks[3].duration}s, ${tasks[3].budget.used.toLocaleString()} tokens`, color: 'green' },
  ]);

  // Review T4
  const r4 = reviews[3];
  step('correct', 300, [
    { text: `T4: ✓ APPROVED (${r4.specChecks.satisfied}/${r4.specChecks.total} spec checks)`, color: 'green' },
  ]);

  // ═══════════════════════════════════════════
  // COHERENCE — contract verification
  // ═══════════════════════════════════════════

  step('coherence', 500, [
    { text: '', color: 'default' },
    { text: '── Coherence ─────────────────────────────', color: 'dim' },
    { text: 'Checking cross-task contracts...', color: 'default' },
  ], {
    path: '.speed/coherence-check.md',
    language: 'markdown',
    lines: [
      '# Coherence Check',
      '',
      '## Cross-Task Contracts',
      '',
      ...coherence.contractGaps.map(g => `- [ ] ${g.item}`),
      '',
      '## Schema Consistency',
      ...coherence.schemaInconsistencies.length > 0
        ? coherence.schemaInconsistencies.map((s: any) => `- [${s.severity}] ${s.description}`)
        : ['- No inconsistencies found'],
      '',
      '## Spec Traceability',
      '',
      ...traceability.covered.map((r: any) =>
        `- [ ] ${r.requirement.slice(0, 60)}${r.requirement.length > 60 ? '...' : ''} → T${r.coveredBy.join(', T')}`
      ),
    ],
  });

  for (const gap of coherence.contractGaps) {
    step('coherence', 100, [
      { text: `  ✓ ${gap.item}`, color: 'green' },
    ]);
  }

  step('coherence', 200, [
    { text: `✓ Coherence: ${coherence.contractGaps.length}/${coherence.contractGaps.length} contracts satisfied`, color: 'green' },
  ]);

  step('coherence', 400, [
    { text: '', color: 'default' },
    { text: 'Checking spec traceability...', color: 'default' },
  ]);

  for (const req of traceability.covered) {
    step('coherence', 120, [
      { text: `  ✓ ${req.requirement.slice(0, 70)}${req.requirement.length > 70 ? '...' : ''} → T${req.coveredBy.join(', T')}`, color: 'green' },
    ]);
  }

  step('coherence', 200, [
    { text: `✓ Traceability: ${traceability.requirementsFound}/${traceability.requirementsFound} requirements covered`, color: 'green' },
  ]);

  // ═══════════════════════════════════════════
  // INTEGRATE — branch merge + guardian
  // ═══════════════════════════════════════════

  step('integrate', 400, [
    { text: '', color: 'default' },
    { text: '── Integrate ─────────────────────────────', color: 'dim' },
    { text: 'Merging task branches...', color: 'default' },
    ...integration.mergedBranches.map(b => ({ text: `  ← ${b}`, color: 'dim' as LineColor })),
    { text: `  → ${integration.targetBranch}`, color: 'accent' },
  ], {
    path: '.speed/integration.md',
    language: 'markdown',
    lines: [
      '# Integration',
      '',
      '## Branches',
      '',
      ...integration.mergedBranches.map((b: string) => `  ← ${b}`),
      `  → ${integration.targetBranch}`,
      '',
      '## Status',
      '',
      `Conflicts: ${integration.conflicts}`,
      `Failures: ${integration.failures}`,
      '',
      '## Guardian Post-Integration',
      '',
      ...guardianPostIntegration.flags.map((f: any) =>
        `[${f.severity.toUpperCase()}] ${f.description}`
      ),
    ],
  });

  step('integrate', 300, [
    { text: `✓ Integration: ${integration.mergedBranches.length} branches, ${integration.conflicts} conflicts, ${integration.failures} failures`, color: 'green' },
  ]);

  step('integrate', 300, [
    { text: '', color: 'default' },
    { text: 'Guardian post-integration:', color: 'default' },
  ]);

  for (const flag of guardianPostIntegration.flags) {
    step('integrate', 200, [
      { text: `  [${flag.severity.toUpperCase()}] ${flag.description.slice(0, 100)}${flag.description.length > 100 ? '...' : ''}`, color: flag.severity === 'critical' ? 'red' : 'dim' },
    ]);
  }

  // ═══════════════════════════════════════════
  // LEARN — observations + conventions
  // ═══════════════════════════════════════════

  step('learn', 500, [
    { text: '', color: 'default' },
    { text: '── Learn ─────────────────────────────────', color: 'dim' },
    { text: `Extracting observations... ${observations.total} found`, color: 'default' },
  ], {
    path: '.speed/observations.md',
    language: 'markdown',
    lines: [
      '# Run Summary',
      '',
      '4 tasks · 7 files · 3 bugs self-caught · 648 seconds',
      '',
      '## Observations',
      '',
      `${observations.total} total`,
      '',
      ...observations.categories.map((c: any) => `- ${c.type}: ${c.count}`),
      '',
      '## Key Findings',
      '',
      ...observations.highlights.map((h: any) =>
        `- [${h.severity.toUpperCase()}] ${h.finding.slice(0, 100)}${h.finding.length > 100 ? '...' : ''}`
      ),
      '',
      '## Conventions Discovered',
      '',
      `${conventions.total} patterns from ${conventions.filesAnalyzed.toLocaleString()} files`,
      '',
      ...conventions.examples.map((c: any) =>
        `- ${c.convention} (${c.confidence}, ${Math.round(c.adherence * 100)}% adherence)`
      ),
    ],
  });

  for (const cat of observations.categories) {
    step('learn', 120, [
      { text: `  ${cat.type}: ${cat.count}`, color: 'dim' },
    ]);
  }

  step('learn', 300, [
    { text: '', color: 'default' },
    { text: `Discovering conventions... ${conventions.total} patterns from ${conventions.filesAnalyzed.toLocaleString()} files`, color: 'default' },
  ]);

  step('learn', 400, [
    { text: '', color: 'default' },
    { text: '═══════════════════════════════════════════', color: 'accent' },
    { text: '  Run complete.', color: 'accent' },
    { text: `  4 tasks · 7 files · 3 bugs self-caught · 648 seconds`, color: 'accent' },
    { text: '═══════════════════════════════════════════', color: 'accent' },
  ]);

  return s;
}
