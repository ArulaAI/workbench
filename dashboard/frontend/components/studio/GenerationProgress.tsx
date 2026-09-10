import { useEffect, useState } from "react";
import type { Operation } from "./types";

export function GenerationProgress({operation}: {operation: Operation}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [operation.id]);
  const start = Date.parse(operation.started_at || operation.created_at || "");
  const seconds = Number.isFinite(start) ? Math.max(0, Math.floor((now - start) / 1000)) : null;
  const elapsed = seconds === null ? null : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  const queued = operation.status === "queued";
  return <div className="studio-generation-progress">
    <p role="status">{operation.demo ? "Loading the saved example · about 5 seconds. No AI request is being made." : queued ? "Waiting for an available generation slot." : seconds !== null && seconds >= 120
      ? "This is taking a while. We’re still waiting for the complete response."
      : operation.action === "clarify" ? "Checking the brief and preparing any necessary questions."
      : "A complete draft can take several minutes. It appears after validation."}</p>
    {elapsed && <p aria-live="off"><span>{queued ? "Time in queue" : "Elapsed"}: {elapsed}</span>{!operation.demo && !queued && operation.timeout_seconds && <span> · Model response limit: {Math.ceil(operation.timeout_seconds / 60)} min</span>}</p>}
    <p>Your inputs are saved. You can leave this workspace and return.</p>
  </div>;
}
