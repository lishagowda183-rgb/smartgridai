import { useState } from "react";
import EmptyState from "../cards/EmptyState.jsx";
import { formatTime } from "../../utils/format.js";

const SEVERITY_STYLE = {
  critical: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  high: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  moderate: "border-amber-500/30 bg-amber-500/10 text-amber-300",
};

const METHOD_LABEL = {
  rolling_zscore: "Rolling z-score",
  hourly_profile: "Hourly profile",
  nighttime: "Nighttime",
  isolation_forest: "Isolation Forest",
};

export default function AnomalyList({ anomalies = [], counts, loading, error, onFilter }) {
  const [severity, setSeverity] = useState("All");
  const sev = severity === "All" ? null : severity;

  const items = sev ? anomalies.filter((a) => a.severity === sev) : anomalies;

  if (loading) return <EmptyState message="Loading anomalies…" />;
  if (error) return <EmptyState message={error} />;

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {["All", "Moderate", "High", "Critical"].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSeverity(s)}
            className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
              severity === s
                ? "bg-brand-600 text-white"
                : "border border-panel-edge bg-surface/50 text-slate-400 hover:bg-panel-edge/60"
            }`}
          >
            {s}
          </button>
        ))}
        {counts && <span className="ml-auto text-xs text-slate-500">found {items.length} anomalies</span>}
      </div>

      {items.length === 0 ? (
        <EmptyState message="No anomalies for this severity." />
      ) : (
        <ul className="max-h-96 divide-y divide-panel-edge overflow-y-auto rounded-lg border border-panel-edge bg-surface/30">
          {items.map((a, i) => (
            <li key={`${a.timestamp}-${a.method}-${i}`} className="px-4 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500">{formatTime(a.timestamp)}</span>
                <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${SEVERITY_STYLE[a.severity] || SEVERITY_STYLE.moderate}`}>
                  {a.severity}
                </span>
                <span className="text-xs text-slate-400">{METHOD_LABEL[a.method] || a.method}</span>
                <span className="text-xs text-slate-500">{a.type}</span>
                <span className="ml-auto text-sm font-semibold text-white tabular-nums">{Number(a.value).toLocaleString()} MW</span>
              </div>
              <p className="mt-0.5 text-[11px] text-slate-500">score {a.score}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}