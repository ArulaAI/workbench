import { useState } from 'react';
import data from '../../../data/f10-replay.json';

type SpecTab = 'product' | 'design' | 'tech';

/** Fake TUI editor chrome wrapping spec content */
function SpecEditor({ filename, children }: { filename: string; children: React.ReactNode }) {
  return (
    <div className="tui-editor">
      <div className="tui-titlebar">
        <div className="tui-dots">
          <span className="tui-dot tui-dot-red" />
          <span className="tui-dot tui-dot-yellow" />
          <span className="tui-dot tui-dot-green" />
        </div>
        <span className="tui-filename">{filename}</span>
        <span className="tui-badge">readonly</span>
      </div>
      <div className="tui-body">
        {children}
      </div>
    </div>
  );
}

export default function ActSpecAuthoring() {
  const [tab, setTab] = useState<SpecTab>('product');

  return (
    <div className="act-spec-authoring">
      {/* Opening statement */}
      <div className="panel surface spec-intro">
        <div className="spec-intro-grid">
          <div className="spec-intro-stat">
            <span className="spec-intro-value">3</span>
            <span className="spec-intro-label">Text files</span>
          </div>
          <div className="spec-intro-stat">
            <span className="spec-intro-value">0</span>
            <span className="spec-intro-label">Figma links</span>
          </div>
          <div className="spec-intro-stat">
            <span className="spec-intro-value">5</span>
            <span className="spec-intro-label">Traceable tasks</span>
          </div>
        </div>
        <p className="spec-intro-text">
          Every requirement, every visual decision, every architectural choice
          encoded as machine-readable text. The pipeline reads these files. Nothing else.
        </p>
      </div>

      {/* Tabs */}
      <div className="spec-tabs">
        {([
          ['product', 'Product Spec'],
          ['design', 'Design Spec'],
          ['tech', 'Tech Spec'],
        ] as [SpecTab, string][]).map(([id, label]) => (
          <button
            key={id}
            className={`spec-tab ${tab === id ? 'active' : ''}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'product' && <ProductSpec />}
      {tab === 'design' && <DesignSpec />}
      {tab === 'tech' && <TechSpec />}
    </div>
  );
}

function ProductSpec() {
  const p = data.specs.product;

  return (
    <div className="spec-content">
      <SpecEditor filename="specs/product/f10-rich-feed.md">
        {/* Problem */}
        <div className="tui-section">
          <div className="tui-heading"># Problem</div>
          <p className="problem-text">{p.problem}</p>
        </div>

        {/* Personas — compact row */}
        <div className="tui-section">
          <div className="tui-heading"># Personas</div>
          <div className="persona-row">
            {p.personas.map((persona) => (
              <div key={persona.name} className="persona-compact">
                <div className="persona-compact-top">
                  <span className="persona-compact-avatar">
                    {persona.name.split(' ').map(w => w[0]).join('')}
                  </span>
                  <span className="persona-compact-name">{persona.name}</span>
                  <span className="persona-compact-role">{persona.role}</span>
                </div>
                <p className="persona-compact-use">{persona.use_case}</p>
              </div>
            ))}
          </div>
        </div>

        {/* User stories */}
        <div className="tui-section">
          <div className="tui-heading"># User Stories</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>ID</th><th>Story</th><th>Priority</th></tr>
              </thead>
              <tbody>
                {p.user_stories.map((s) => (
                  <tr key={s.id}>
                    <td className="mono">{s.id}</td>
                    <td>{s.story}</td>
                    <td>
                      <span className={`badge badge-${s.priority}`}>{s.priority}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Scope exclusions */}
        <div className="tui-section">
          <div className="tui-heading"># Scope Exclusions</div>
          <div className="scope-list">
            {p.scope_out.map((s) => (
              <div key={s.item} className="scope-item">
                <span className="scope-item-name">{s.item}</span>
                <span className="scope-item-rationale">{s.rationale}</span>
              </div>
            ))}
          </div>
        </div>
      </SpecEditor>
    </div>
  );
}

function DesignSpec() {
  const d = data.specs.design;

  return (
    <div className="spec-content">
      <SpecEditor filename="specs/design/f10-rich-feed.md">
        {/* ASCII mockup — lead with the visual */}
        <div className="tui-section">
          <div className="tui-heading"># Layout Contract</div>
          <pre className="ascii-block ascii-hero">{d.ascii_mockup}</pre>
          <div className="ascii-callout">
            <span className="ascii-callout-arrow">←</span>
            <span className="ascii-callout-text">
              One line for activity entries. The reviewer will catch a violation
              of this exact contract in Act 3.
            </span>
          </div>
        </div>

        {/* Visual hierarchy */}
        <div className="tui-section">
          <div className="tui-heading"># Visual Hierarchy</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Type</th><th>Events</th><th>Treatment</th></tr>
              </thead>
              <tbody>
                {d.visual_hierarchy.map((v) => (
                  <tr key={v.type}>
                    <td className="mono">{v.type}</td>
                    <td className="mono small">{v.events.join(', ')}</td>
                    <td>{v.treatment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Tokens */}
        <div className="tui-section">
          <div className="tui-heading"># Design Tokens</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Element</th><th>Token</th></tr>
              </thead>
              <tbody>
                {d.tokens.map((t) => (
                  <tr key={t.element}>
                    <td>{t.element}</td>
                    <td className="mono small">{t.token}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Figma note */}
        <div className="tui-section">
          <div className="tui-heading">
            # Figma Reference: <span className="accent">N/A</span>
          </div>
          <p className="panel-note" style={{ marginTop: 0 }}>
            ASCII art defines layout. Token tables define styling.
            More precise than most Figma handoffs because every decision is
            machine-readable text that agents can verify against.
          </p>
        </div>
      </SpecEditor>
    </div>
  );
}

function TechSpec() {
  const t = data.specs.tech;

  return (
    <div className="spec-content">
      <SpecEditor filename="specs/tech/f10-rich-feed.md">
        {/* Before / After — lead with code */}
        <div className="tui-section">
          <div className="tui-heading"># Transformation</div>
          <div className="before-after-ascii">
            <div className="ba-col">
              <div className="ba-label">Before (current EventCard)</div>
              <pre className="ascii-block small">{`┌──────────────────────────┐
│ SHIPPED           1d ago │
│ Shipped AI Resume Builder│
│ project / 01KJJ0QT...   │
└──────────────────────────┘`}</pre>
            </div>
            <div className="ba-arrow">→</div>
            <div className="ba-col">
              <div className="ba-label">After (timeline with hierarchy)</div>
              <pre className="ascii-block small">{`○  Maya Chen  shipped        2h ago
│  ┌────────────────────────────┐
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │
│  │  AI Resume Builder         │
│  │  React · Python · OpenAI   │
│  └────────────────────────────┘`}</pre>
            </div>
          </div>
        </div>

        {/* Metadata contract */}
        <div className="tui-section">
          <div className="tui-heading"># Metadata Contract</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Event Type</th><th>Required Fields</th><th>Missing in Seed</th></tr>
              </thead>
              <tbody>
                {t.metadata_contract.map((m) => (
                  <tr key={m.event_type}>
                    <td className="mono small">{m.event_type}</td>
                    <td className="mono small">{m.required_fields.join(', ')}</td>
                    <td className="mono small warn">
                      {m.missing_in_seed.length > 0 ? m.missing_in_seed.join(', ') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Key decisions */}
        <div className="tui-section">
          <div className="tui-heading"># Architectural Decisions</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Decision</th><th>Choice</th><th>Alternative</th><th>Rationale</th></tr>
              </thead>
              <tbody>
                {t.key_decisions.map((d) => (
                  <tr key={d.decision}>
                    <td>{d.decision}</td>
                    <td className="mono small">{d.choice}</td>
                    <td className="mono small">{d.alternative}</td>
                    <td className="small">{d.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* File impact */}
        <div className="tui-section">
          <div className="tui-heading"># File Impact</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>File</th><th>Change</th></tr>
              </thead>
              <tbody>
                {t.file_impact.map((f) => (
                  <tr key={f.file}>
                    <td className="mono small">{f.file}</td>
                    <td>{f.change}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="panel-note">
            The scope is constrained by the spec, not discovered by agents.
          </p>
        </div>
      </SpecEditor>
    </div>
  );
}
