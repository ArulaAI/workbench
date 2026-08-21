import data from '../../../data/f10-replay.json';

export default function ActLearning() {
  const learning = data.learning;

  return (
    <div className="act-learning">
      {/* Observations */}
      <div className="panel surface">
        <div className="panel-label">Observations Extracted from F10</div>
        <p className="panel-note">
          A 10-step extraction pipeline reads every log, review, gate result, and guardian
          verdict. It looks for 19 observation types.
        </p>
      </div>

      <div className="observation-cards">
        {learning.observations.map((obs, i) => (
          <div key={i} className="panel surface observation-card">
            <div className="obs-header">
              <span className={`obs-type-badge obs-type-${obs.type}`}>{obs.type}</span>
              {obs.task_id && <span className="mono obs-task">T{obs.task_id}</span>}
              <span className="obs-weight mono">weight: {obs.priority_weight}</span>
            </div>
            <p className="obs-description">{obs.description}</p>
            <div className="obs-agent">
              <span className="obs-agent-label">Agent:</span>
              <span className="mono">{obs.agent}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Classification cascade */}
      <div className="panel surface">
        <div className="panel-label">Classification Cascade</div>
        <div className="cascade-steps">
          {learning.classification_cascade.map((step, i) => (
            <div key={step} className="cascade-step">
              <span className="cascade-num">{i + 1}</span>
              <span className="cascade-name">{step}</span>
              {i < learning.classification_cascade.length - 1 && <span className="cascade-arrow">→</span>}
            </div>
          ))}
        </div>
        <p className="panel-note">
          Most observations hit stage 1 or 2. The LLM fires only for genuinely novel situations.
          Fast and cheap by default.
        </p>
      </div>

      {/* Pattern lifecycle */}
      <div className="panel surface">
        <div className="panel-label">Pattern Lifecycle: Observations → Patterns → Injections</div>
        <div className="lifecycle-viz">
          <div className="lifecycle-col">
            <div className="lifecycle-header">Observations</div>
            {learning.pattern_lifecycle.example.observations.map((obs, i) => (
              <div key={i} className="lifecycle-item lifecycle-obs">{obs}</div>
            ))}
          </div>
          <div className="lifecycle-arrow">→</div>
          <div className="lifecycle-col">
            <div className="lifecycle-header">Pattern</div>
            <div className="lifecycle-item lifecycle-pattern">
              {learning.pattern_lifecycle.example.pattern}
            </div>
          </div>
          <div className="lifecycle-arrow">→</div>
          <div className="lifecycle-col">
            <div className="lifecycle-header">Injection</div>
            <div className="lifecycle-item lifecycle-injection">
              {learning.pattern_lifecycle.example.injection}
            </div>
          </div>
        </div>
      </div>

      {/* Feedback loop */}
      <div className="panel surface">
        <div className="panel-label">The Feedback Loop</div>
        <pre className="ascii-block">{`     ┌─────────────────────────────────────────────┐
     │                                             │
     ▼                                             │
  ┌──────┐     ┌──────────────┐     ┌──────────┐  │
  │ RUN  │ ──▶ │ OBSERVATIONS │ ──▶ │ PATTERNS │  │
  └──────┘     └──────────────┘     └────┬─────┘  │
                                         │        │
                                    ┌────▼─────┐  │
                                    │INJECTIONS│──┘
                                    └──────────┘

  Run 3 is better than Run 1 because SPEED remembered.`}</pre>
      </div>
    </div>
  );
}
