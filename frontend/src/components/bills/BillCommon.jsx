export function BillLine({ label, value, bold = false, muted = false }) {
  return (
    <div className={`flex items-center justify-between py-1.5 ${muted ? "text-slate-500" : ""}`}>
      <span className={`text-sm ${bold ? "font-semibold text-white" : "text-slate-400"}`}>{label}</span>
      <span className={`text-sm tabular-nums ${bold ? "font-bold text-white" : "text-slate-200"}`}>{value}</span>
    </div>
  );
}

export function ModeTabs({ mode, onChange }) {
  return (
    <div className="inline-flex rounded-lg border border-panel-edge bg-surface/50 p-1 text-sm">
      {[
        { id: "regional", label: "Regional Grid Energy Cost" },
        { id: "household", label: "Household Bill Simulator" },
      ].map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onChange(t.id)}
          className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
            mode === t.id
              ? "bg-brand-600 text-white"
              : "text-slate-400 hover:bg-panel-edge/60 hover:text-white"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function ScopeTag({ scope }) {
  const cls =
    scope === "household"
      ? "border-teal-500/30 bg-teal-500/10 text-teal-300"
      : scope === "regional_grid"
        ? "border-brand-500/30 bg-brand-500/10 text-brand-300"
        : "border-slate-500/30 bg-slate-500/10 text-slate-300";
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {scope === "household" ? "Household" : scope === "regional_grid" ? "Regional Grid" : scope || "Unknown"}
    </span>
  );
}