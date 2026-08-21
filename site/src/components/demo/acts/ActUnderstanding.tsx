import { useState } from 'react';
import data from '../../../data/f10-replay.json';

type Section = 'csg' | 'skeletons' | 'alignment' | 'pipeline';

export default function ActUnderstanding() {
  const [section, setSection] = useState<Section>('csg');
  const intel = data.intelligence;

  return (
    <div className="act-understanding">
      {/* Section tabs */}
      <div className="spec-tabs">
        {([
          ['csg', 'Code Intelligence'],
          ['skeletons', 'Skeleton Compression'],
          ['alignment', 'Spec Alignment'],
          ['pipeline', 'Context Pipeline'],
        ] as [Section, string][]).map(([id, label]) => (
          <button
            key={id}
            className={`spec-tab ${section === id ? 'active' : ''}`}
            onClick={() => setSection(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {section === 'csg' && <CSGSection />}
      {section === 'skeletons' && <SkeletonsSection />}
      {section === 'alignment' && <AlignmentSection />}
      {section === 'pipeline' && <PipelineSection />}

      {/* Codebase snapshot — at the bottom */}
      <div className="panel surface" style={{ marginTop: 24 }}>
        <div className="panel-label">Codebase Snapshot</div>
        <div className="stat-row">
          <div className="stat">
            <span className="stat-value">{intel.codebase.total_files.toLocaleString()}</span>
            <span className="stat-label">Files</span>
          </div>
          <div className="stat">
            <span className="stat-value">{intel.codebase.total_lines.toLocaleString()}</span>
            <span className="stat-label">Lines</span>
          </div>
          <div className="stat">
            <span className="stat-value">{Object.keys(intel.codebase.languages).length}</span>
            <span className="stat-label">Languages</span>
          </div>
        </div>
        <div className="lang-bars">
          {Object.entries(intel.codebase.languages)
            .sort(([, a], [, b]) => b.lines - a.lines)
            .slice(0, 5)
            .map(([lang, info]) => (
              <div key={lang} className="lang-bar-row">
                <span className="lang-name">{lang}</span>
                <div className="lang-bar-track">
                  <div
                    className="lang-bar-fill"
                    style={{ width: `${(info.lines / intel.codebase.total_lines) * 100}%` }}
                  />
                </div>
                <span className="lang-count">{info.files} files</span>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

function CSGSection() {
  const csg = data.intelligence.csg;

  const layers = [
    {
      key: 'layer_a' as const,
      color: 'var(--color-accent)',
      stat: `${csg.layer_a.nodes.toLocaleString()} nodes`,
      ascii: [
        '  ·  ·  ·',
        '  ·  ·  ·',
        '  ·  ·  ·',
      ],
    },
    {
      key: 'layer_b' as const,
      color: 'var(--color-blue)',
      stat: `${csg.layer_b.edges.toLocaleString()} edges`,
      ascii: [
        '  ·──·  ·',
        '  ·  ·──·',
        '  ·──·──·',
      ],
    },
    {
      key: 'layer_c' as const,
      color: 'var(--color-violet)',
      stat: `${csg.layer_c.clusters.toLocaleString()} clusters`,
      ascii: [
        '  ┌·──·┐ ·',
        '  │·  ·──·│',
        '  └·──·──·┘',
      ],
    },
    {
      key: 'layer_d' as const,
      color: 'var(--color-amber)',
      stat: 'centrality scores',
      ascii: [
        '  ┌·──●┐ ·',
        '  │·  ·──·│',
        '  └·──·──●┘',
      ],
    },
  ];

  type LayerKey = 'layer_a' | 'layer_b' | 'layer_c' | 'layer_d';

  return (
    <div className="spec-content">
      {/* Colored layer build visualization */}
      <div className="panel surface">
        <div className="panel-label">How SPEED reads your codebase</div>
        <div className="csg-build">
          {layers.map(({ key, color, ascii }) => {
            const layer = csg[key as LayerKey];
            return (
              <div key={key} className="csg-build-col">
                <div className="csg-build-label" style={{ color }}>{layer.label}</div>
                <pre className="csg-build-ascii" style={{ color }}>{ascii.join('\n')}</pre>
              </div>
            );
          })}
        </div>
      </div>

      {/* Layer detail cards */}
      <div className="csg-layers">
        {layers.map(({ key, color, stat }) => {
          const layer = csg[key as LayerKey];
          return (
            <div key={key} className="panel surface csg-layer-card" style={{
              borderColor: `color-mix(in srgb, ${color} 30%, transparent)`,
            }}>
              <div className="csg-layer-header">
                <span className="csg-layer-dot" style={{ background: color }} />
                <span className="csg-layer-name">{layer.label}</span>
                <span className="csg-layer-stat mono">{stat}</span>
              </div>
              <p className="csg-layer-desc">{layer.description}</p>
            </div>
          );
        })}
      </div>

      <div className="panel surface">
        <div className="panel-label">Why it matters</div>
        <p className="panel-note">
          FeedEventType is a hub node with high centrality: changing it ripples across 14 files.
          When the Architect assigns T3 (the timeline rewrite) to opus instead of sonnet,
          the CSG explains why: the files touched have high impact scores.
        </p>
      </div>
    </div>
  );
}

function SkeletonsSection() {
  const sk = data.intelligence.skeletons;
  const pct = ((1 - sk.skeleton_lines / sk.source_lines) * 100).toFixed(1);
  return (
    <div className="spec-content">
      <div className="panel surface">
        <div className="stat-row">
          <div className="stat">
            <span className="stat-value">{sk.source_lines.toLocaleString()}</span>
            <span className="stat-label">Source Lines</span>
          </div>
          <div className="stat">
            <span className="stat-value accent">→</span>
            <span className="stat-label">{pct}% removed</span>
          </div>
          <div className="stat">
            <span className="stat-value">{sk.skeleton_lines.toLocaleString()}</span>
            <span className="stat-label">Skeleton Lines</span>
          </div>
          <div className="stat">
            <span className="stat-value accent">{sk.compression_ratio}x</span>
            <span className="stat-label">Compression</span>
          </div>
        </div>
      </div>

      <div className="panel surface">
        <div className="panel-label">How it works</div>
        <div className="skeleton-demo">
          <div className="skeleton-col">
            <div className="ba-label">Source (full file)</div>
            <pre className="ascii-block small">{`export function getActorDisplayName(
  event: FeedEvent
): string {
  const meta = event.metadata;
  if (meta?.actor_name) {
    return meta.actor_name;
  }
  if (meta?.actor_username) {
    return meta.actor_username;
  }
  return 'A builder';
}

export function getGradientClasses(
  index: number
): string {
  const palettes = [
    'from-indigo-500 via-purple-500 to-pink-500',
    'from-emerald-500 via-teal-500 to-cyan-500',
    'from-amber-500 via-orange-500 to-red-500',
    'from-blue-500 via-indigo-500 to-violet-500',
  ];
  return palettes[index % palettes.length];
}`}</pre>
          </div>
          <div className="ba-arrow">→</div>
          <div className="skeleton-col">
            <div className="ba-label">Skeleton (signatures only)</div>
            <pre className="ascii-block small">{`export function getActorDisplayName(
  event: FeedEvent
): string

export function getGradientClasses(
  index: number
): string`}</pre>
          </div>
        </div>
        <p className="panel-note">
          Every function signature preserved. Every implementation detail gone.
          Enough for an agent to understand the interface without drowning in the body.
        </p>
      </div>
    </div>
  );
}

function AlignmentSection() {
  const sa = data.intelligence.spec_alignment;
  return (
    <div className="spec-content">
      <div className="panel surface">
        <div className="stat-row">
          <div className="stat">
            <span className="stat-value">{sa.total_claims}</span>
            <span className="stat-label">Claims Extracted</span>
          </div>
          <div className="stat">
            <span className="stat-value" style={{ color: 'var(--color-green)' }}>{sa.confirmed}</span>
            <span className="stat-label">Confirmed</span>
          </div>
          <div className="stat">
            <span className="stat-value" style={{ color: 'var(--color-amber)' }}>{sa.missing}</span>
            <span className="stat-label">Missing</span>
          </div>
          <div className="stat">
            <span className="stat-value" style={{ color: 'var(--color-red)' }}>{sa.divergent}</span>
            <span className="stat-label">Divergent</span>
          </div>
        </div>
      </div>

      <div className="alignment-grid">
        <div className="panel surface">
          <div className="panel-label" style={{ color: 'var(--color-green)' }}>Confirmed (exists in codebase)</div>
          <div className="tag-list">
            {sa.examples.confirmed.map((t) => (
              <span key={t} className="tag tag-green">{t}</span>
            ))}
          </div>
        </div>
        <div className="panel surface">
          <div className="panel-label" style={{ color: 'var(--color-amber)' }}>Missing (needs creation)</div>
          <div className="tag-list">
            {sa.examples.missing.map((t) => (
              <span key={t} className="tag tag-amber">{t}</span>
            ))}
          </div>
        </div>
        <div className="panel surface">
          <div className="panel-label" style={{ color: 'var(--color-red)' }}>Divergent (exists but different)</div>
          <div className="tag-list">
            {sa.examples.divergent.map((t) => (
              <span key={t} className="tag tag-red">{t}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="panel surface">
        <div className="panel-label">What the developer receives</div>
        <p className="panel-note">
          The developer agent for T3 receives this alignment table in its prompt.
          It knows EventCard exists and must be replaced. It knows MilestoneCard
          doesn't exist and must be created. It knows actor exists but the resolver
          is a TODO. No guessing.
        </p>
      </div>
    </div>
  );
}

function PipelineSection() {
  const budget = data.intelligence.budget;
  const pipeline = data.intelligence.context_pipeline;

  const funnelSteps = [
    { label: 'Full codebase', value: budget.total_lines, color: 'var(--color-text-tertiary)' },
    { label: 'After CSG scope', value: budget.after_csg_scope, color: 'var(--color-blue)' },
    { label: 'After skeleton compression', value: budget.after_skeleton, color: 'var(--color-violet)' },
    { label: 'Agent prompt', value: budget.agent_prompt, color: 'var(--color-accent)' },
  ];

  const maxVal = funnelSteps[0].value;

  return (
    <div className="spec-content">
      <div className="pipeline-layers">
        {([
          [pipeline.layer1, 'var(--color-accent)'],
          [pipeline.layer2, 'var(--color-blue)'],
          [pipeline.layer3, 'var(--color-violet)'],
        ] as const).map(([layer, color]) => (
          <div key={layer.label} className="panel surface">
            <div className="panel-label" style={{ color }}>{layer.label}</div>
            <p className="panel-note">{layer.description}</p>
          </div>
        ))}
      </div>

      <div className="panel surface">
        <div className="panel-label">Context Funnel: 90K lines → 8K agent prompt</div>
        <div className="funnel">
          {funnelSteps.map((step) => (
            <div key={step.label} className="funnel-step">
              <div className="funnel-bar-track">
                <div
                  className="funnel-bar-fill"
                  style={{
                    width: `${(step.value / maxVal) * 100}%`,
                    background: step.color,
                  }}
                />
              </div>
              <div className="funnel-meta">
                <span className="funnel-label">{step.label}</span>
                <span className="funnel-value mono">{step.value.toLocaleString()} lines</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel surface">
        <div className="panel-label">Degradation Tiers</div>
        <p className="panel-note">When context exceeds the token budget:</p>
        <ol className="degradation-list">
          {budget.degradation_tiers.map((tier, i) => (
            <li key={i} className={i === budget.degradation_tiers.length - 1 ? 'accent-text' : ''}>
              {tier}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
