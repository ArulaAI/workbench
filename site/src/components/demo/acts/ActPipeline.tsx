import { useState } from 'react';
import data from '../../../data/f10-replay.json';

type PipelineSection = 'plan' | 'run' | 'review' | 'integrate';

/** Collapsible prompt preview styled as a TUI terminal */
function PromptPreview({ agent, lines, sections }: {
  agent: string;
  lines: number;
  sections: { label: string; color: string; content: string }[];
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="prompt-preview">
      <button
        className="prompt-preview-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="prompt-preview-label">
          <span className="prompt-preview-icon">{expanded ? '▾' : '▸'}</span>
          Agent Prompt: {agent}
        </span>
        <span className="prompt-preview-meta">{lines.toLocaleString()} lines assembled</span>
      </button>
      {expanded && (
        <div className="prompt-preview-body">
          {sections.map((s, i) => (
            <div key={i} className="prompt-section">
              <div className="prompt-section-header" style={{ color: s.color }}>
                ## {s.label}
              </div>
              <pre className="prompt-section-content">{s.content}</pre>
            </div>
          ))}
          <div className="prompt-truncated">
            ... truncated ({lines.toLocaleString()} lines total)
          </div>
        </div>
      )}
    </div>
  );
}

export default function ActPipeline() {
  const [section, setSection] = useState<PipelineSection>('plan');

  return (
    <div className="act-pipeline">
      <div className="spec-tabs">
        {([
          ['plan', 'Plan'],
          ['run', 'Run'],
          ['review', 'Review'],
          ['integrate', 'Integrate'],
        ] as [PipelineSection, string][]).map(([id, label]) => (
          <button
            key={id}
            className={`spec-tab ${section === id ? 'active' : ''}`}
            onClick={() => setSection(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {section === 'plan' && <PlanSection />}
      {section === 'run' && <RunSection />}
      {section === 'review' && <ReviewSection />}
      {section === 'integrate' && <IntegrateSection />}
    </div>
  );
}

function PlanSection() {
  const tasks = data.pipeline.tasks;
  const guardian = data.pipeline.guardian_checkpoints[0];
  const verifier = data.pipeline.verifier;

  return (
    <div className="spec-content">
      {/* DAG */}
      <div className="panel surface">
        <div className="panel-label">Task DAG — 4 Tasks Decomposed</div>
        <div className="dag-viz">
          <div className="dag-row">
            <div className="dag-node dag-node-approved">
              <span className="dag-node-id">T1</span>
              <span className="dag-node-title">Enrich seed data</span>
              <span className="dag-node-meta">backend · sonnet</span>
            </div>
            <div className="dag-node dag-node-approved">
              <span className="dag-node-id">T2</span>
              <span className="dag-node-title">Feed utilities (TDD)</span>
              <span className="dag-node-meta">frontend · sonnet</span>
            </div>
          </div>
          <div className="dag-edge-down" />
          <div className="dag-row">
            <div className="dag-node dag-node-changes">
              <span className="dag-node-id">T3</span>
              <span className="dag-node-title">Timeline components</span>
              <span className="dag-node-meta">frontend · opus</span>
            </div>
          </div>
          <div className="dag-edge-down" />
          <div className="dag-row">
            <div className="dag-node dag-node-approved">
              <span className="dag-node-id">T4</span>
              <span className="dag-node-title">Integration tests</span>
              <span className="dag-node-meta">frontend · opus</span>
            </div>
          </div>
        </div>
        <p className="panel-note">
          Model selection visible: sonnet for T1/T2 (straightforward), opus for T3/T4 (complex UI and comprehensive tests).
        </p>
      </div>

      {/* Verification */}
      <div className="checkpoint-row">
        <div className="panel surface checkpoint">
          <div className="checkpoint-icon pass">✓</div>
          <div>
            <div className="checkpoint-label">Plan Verifier</div>
            <div className="checkpoint-detail">{verifier.status} — {verifier.requirements_mapped} spec requirements mapped to tasks</div>
          </div>
        </div>
        <div className="panel surface checkpoint">
          <div className={`checkpoint-icon ${guardian.status === 'aligned' ? 'pass' : 'warn'}`}>
            {guardian.status === 'aligned' ? '✓' : '!'}
          </div>
          <div>
            <div className="checkpoint-label">Guardian (pre-plan)</div>
            <div className="checkpoint-detail">{guardian.summary}</div>
          </div>
        </div>
      </div>

      <div className="panel surface">
        <div className="panel-label">Validation Report</div>
        <div className="stat-row compact">
          <div className="stat">
            <span className="stat-value">{data.pipeline.validation.findings_count}</span>
            <span className="stat-label">Findings</span>
          </div>
          <div className="stat">
            <span className="stat-value" style={{ color: 'var(--color-amber)' }}>{data.pipeline.validation.warnings}</span>
            <span className="stat-label">Warnings</span>
          </div>
          <div className="stat">
            <span className="stat-value">{data.pipeline.validation.notes}</span>
            <span className="stat-label">Notes</span>
          </div>
        </div>
        <p className="panel-note">{data.pipeline.validation.key_finding}</p>
      </div>

      {/* Architect prompt */}
      <PromptPreview
        agent="Architect"
        lines={4820}
        sections={[
          {
            label: 'Product Spec',
            color: 'var(--color-accent)',
            content: `problem: "Builders hit a wall of ULID strings..."\npersonas: [Maya Chen, James Okafor, David Morales]\nuser_stories: [RF-1..RF-5]\nscope_out: [backend actor resolution, real-time, filtering]`,
          },
          {
            label: 'CSG Impact Analysis',
            color: 'var(--color-blue)',
            content: `high_impact_symbols:\n  - FeedEventType (centrality: 0.42, blast_radius: 14)\n  - EventCard (centrality: 0.31, blast_radius: 8)\ndomains_in_scope: [feed, frontend/components, backend/seed]`,
          },
          {
            label: 'Spec Alignment',
            color: 'var(--color-violet)',
            content: `confirmed: [EventCard, FeedEventType, getActorDisplayName]\nmissing: [MilestoneCard, TimelineEntry, ActivityLine]\ndiverged: [actor resolver (TODO in source)]`,
          },
        ]}
      />
    </div>
  );
}

function RunSection() {
  const tasks = data.pipeline.tasks;

  return (
    <div className="spec-content">
      <div className="panel surface">
        <div className="panel-label">Parallel Execution</div>
        <p className="panel-note">
          T1 and T2 start simultaneously on separate git worktrees. T2 finishes first (3m 38s), T3 immediately starts.
          T1 finishes (7m 21s). T4 waits for T3.
        </p>
        <div className="execution-timeline">
          {tasks.map((task) => (
            <div key={task.id} className="exec-row">
              <span className="exec-label mono">T{task.id}</span>
              <div className="exec-bar-track">
                <div
                  className={`exec-bar-fill ${task.status === 'request_changes' ? 'exec-bar-warn' : 'exec-bar-pass'}`}
                  style={{ width: `${(task.duration_seconds / 600) * 100}%` }}
                >
                  <span className="exec-bar-text">{task.duration_display}</span>
                </div>
              </div>
              <span className="exec-model mono">{task.agent_model}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Gate matrix */}
      <div className="panel surface">
        <div className="panel-label">Gate Results</div>
        <div className="table-scroll"><table className="data-table">
          <thead>
            <tr>
              <th>Task</th>
              <th>Lint</th>
              <th>Typecheck</th>
              <th>Tests</th>
              <th>Scope</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td className="mono">T{task.id}</td>
                <td><GateCell value={task.gates.lint} /></td>
                <td><GateCell value={task.gates.typecheck} /></td>
                <td><GateCell value={task.gates.tests} /></td>
                <td><GateCell value={task.gates.scope} /></td>
                <td><GateCell value={task.review.verdict} /></td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </div>

      {/* T4 retry */}
      <div className="panel surface">
        <div className="panel-label">T4: Timeout + Retry</div>
        <p className="panel-note">
          First attempt timed out at {tasks[3].retry?.first_attempt_duration}. Retry succeeded at {tasks[3].duration_display} total.
          The system is resilient: timeouts don't kill the pipeline.
        </p>
      </div>

      {/* Cross-task propagation */}
      <div className="panel surface">
        <div className="panel-label">Cross-Task Decision Propagation</div>
        <div className="propagation">
          <div className="prop-from">
            <span className="mono">T2</span> raised a concern: "getLinkTarget accepts lowercase targetType; if backend sends uppercase, Task 3 will need to lowercase."
          </div>
          <div className="prop-arrow">↓</div>
          <div className="prop-to">
            <span className="mono">T3</span> decisions include: "Lowercased event.targetType before passing to getLinkTarget (Task 2 concern)."
          </div>
        </div>
      </div>

      {/* Developer prompt */}
      <PromptPreview
        agent="Developer (T3)"
        lines={8214}
        sections={[
          {
            label: 'Task Assignment',
            color: 'var(--color-accent)',
            content: `task: T3 — Timeline components\nfiles_touched: [src/frontend/src/app/feed/page.tsx]\ndependencies: [T2 (feed utilities)]\nmodel: opus`,
          },
          {
            label: 'Skeletons (3 files, 847 lines)',
            color: 'var(--color-blue)',
            content: `// src/frontend/src/app/feed/page.tsx\nexport default function FeedPage(): JSX.Element\nfunction EventCard({ event }: { event: FeedEvent }): JSX.Element\nfunction getActorDisplayName(event: FeedEvent): string\nfunction getGradientClasses(index: number): string`,
          },
          {
            label: 'Spec Alignment for T3',
            color: 'var(--color-violet)',
            content: `REPLACE: EventCard → timeline layout with 4 visual types\nCREATE:  MilestoneCard, ContentCard, TextCard, ActivityLine\nKEEP:    getActorDisplayName (resolve from metadata)\nWARN:    actor resolver returns None — use metadata fallback`,
          },
          {
            label: 'Design Contract',
            color: 'var(--color-amber)',
            content: `visual_hierarchy:\n  milestone: gradient header, expanded card\n  content:   embedded card with title\n  activity:  compact SINGLE-LINE entry  ← enforced\ntokens: [w-9 h-9 rounded-full, text-ink text-[14px]...]`,
          },
        ]}
      />
    </div>
  );
}

function ReviewSection() {
  const tasks = data.pipeline.tasks;
  const guardianFlag = data.pipeline.guardian_checkpoints[2];

  return (
    <div className="spec-content">
      {/* Per-task review verdicts */}
      <div className="review-grid">
        {tasks.map((task) => (
          <div key={task.id} className={`panel surface review-card ${task.review.verdict === 'request_changes' ? 'review-card-warn' : ''}`}>
            <div className="review-card-header">
              <span className="mono">T{task.id}</span>
              <span className={`badge ${task.review.verdict === 'approve' ? 'badge-must' : 'badge-warn'}`}>
                {task.review.verdict}
              </span>
            </div>
            <div className="review-card-stats">
              <span>{task.review.spec_checks} checks</span>
              <span className="sep">·</span>
              <span style={{ color: 'var(--color-green)' }}>{task.review.satisfied} satisfied</span>
              {task.review.partial > 0 && (
                <><span className="sep">·</span><span style={{ color: 'var(--color-amber)' }}>{task.review.partial} partial</span></>
              )}
              {task.review.not_satisfied > 0 && (
                <><span className="sep">·</span><span style={{ color: 'var(--color-red)' }}>{task.review.not_satisfied} not satisfied</span></>
              )}
            </div>
            {task.review.key_issue && (
              <div className="review-issue">
                <p>{task.review.key_issue}</p>
                <pre className="ascii-block small">{task.review.ascii_mockup_line}</pre>
                <p className="panel-note">
                  The ASCII art was the contract. The reviewer enforced it.
                </p>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Guardian flag */}
      <div className="panel surface guardian-flag">
        <div className="guardian-flag-header">
          <span className="guardian-icon">⚑</span>
          <span className="panel-label">Product Guardian: <span className="warn-text">flagged</span></span>
        </div>
        <blockquote className="guardian-quote">
          {guardianFlag.flag}
        </blockquote>
        <div className="guardian-rec">
          <div className="panel-label small">Recommendation</div>
          <p>{guardianFlag.recommendation}</p>
        </div>
        <p className="panel-note">
          Neither the Developer, nor the Reviewer who checked 17 requirements, caught this.
          The Guardian caught it by reasoning about the behavioral test: "Does this reward building or performing?"
        </p>
      </div>

      {/* Reviewer prompt */}
      <PromptPreview
        agent="Reviewer (T3)"
        lines={6480}
        sections={[
          {
            label: 'Code Diff (T3 branch)',
            color: 'var(--color-accent)',
            content: `+++ src/frontend/src/app/feed/page.tsx\n@@ -1,42 +1,187 @@\n-function EventCard({ event }) {\n+function MilestoneCard({ event }) {\n+function ContentCard({ event }) {\n+function ActivityLine({ event }) {  // ← single line?`,
          },
          {
            label: 'Spec Requirements (17 checks)',
            color: 'var(--color-blue)',
            content: `RF-1: visual timeline instead of flat event list\nRF-2: PROJECT_SHIPPED → milestone card with gradient\nRF-3: TRIBE_CREATED → embedded content card\nRF-4: join events → compact SINGLE-LINE entry\nRF-5: actor name, avatar, relative timestamp`,
          },
          {
            label: 'ASCII Layout Contract',
            color: 'var(--color-amber)',
            content: `○  James Okafor joined Hospitality OS     12h ago\n○  Aisha Patel joined · UX / Prototyping    3d\n   ↑ activity entries MUST be single-line\n   violation = request_changes`,
          },
        ]}
      />
    </div>
  );
}

function IntegrateSection() {
  const integration = data.pipeline.integration;
  const postGuardian = data.pipeline.guardian_checkpoints[3];

  return (
    <div className="spec-content">
      <div className="panel surface">
        <div className="panel-label">Clean Merge</div>
        <div className="stat-row">
          <div className="stat">
            <span className="stat-value">{integration.merged_branches.length}</span>
            <span className="stat-label">Branches Merged</span>
          </div>
          <div className="stat">
            <span className="stat-value" style={{ color: 'var(--color-green)' }}>{integration.conflicts}</span>
            <span className="stat-label">Conflicts</span>
          </div>
          <div className="stat">
            <span className="stat-value">{integration.test_results.frontend}</span>
            <span className="stat-label">Frontend Tests</span>
          </div>
        </div>
      </div>

      <div className="panel surface checkpoint">
        <div className="checkpoint-icon pass">✓</div>
        <div>
          <div className="checkpoint-label">Guardian (post-integration)</div>
          <div className="checkpoint-detail">{postGuardian.summary}</div>
        </div>
      </div>

      {/* Integrator prompt */}
      <PromptPreview
        agent="Integrator"
        lines={3120}
        sections={[
          {
            label: 'Merge Manifest',
            color: 'var(--color-accent)',
            content: `branches: [task-1/enrich-seed, task-2/feed-utils,\n          task-3/timeline-components, task-4/integration-tests]\nbase: feature/f10-rich-feed\nstrategy: sequential merge, T1 → T2 → T3 → T4`,
          },
          {
            label: 'Conflict Resolution Rules',
            color: 'var(--color-blue)',
            content: `priority: later tasks override earlier tasks\nexception: seed data (T1) always wins for backend/seed/\ntest_requirement: all frontend tests must pass post-merge`,
          },
        ]}
      />
    </div>
  );
}

function GateCell({ value }: { value: string }) {
  const isPass = value.startsWith('pass') || value === 'approve';
  const isWarn = value.startsWith('warn') || value === 'partial' || value === 'request_changes';
  return (
    <span className={`gate-cell ${isPass ? 'gate-pass' : isWarn ? 'gate-warn' : 'gate-fail'}`}>
      {value}
    </span>
  );
}
