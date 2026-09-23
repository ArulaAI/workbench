export function FeatureUnavailableNote({ feature }: { feature: string }) {
  return (
    <div className="surface" style={{ padding: 24 }}>
      <p className="type-body">
        {feature} isn&apos;t available. This requires a Layer 1 discovery build
        (<span className="type-mono-value">speed digest --rebuild-discovery</span>).
      </p>
    </div>
  );
}
