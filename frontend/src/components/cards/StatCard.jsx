export default function StatCard({ label, value, unit, sub, badge, change, icon }) {
  const changeColor =
    change && change.value > 0 ? "text-emerald-400" : change?.value < 0 ? "text-rose-400" : "text-slate-400";
  return (
    <div className="rounded-xl border border-panel-edge bg-panel p-4">
      <div className="flex items-start justify-between">
        <p className="text-sm font-medium text-slate-400">{label}</p>
        {badge && (
          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${badge.cls}`}>
            {badge.text}
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-bold text-white tracking-tight">{value}</span>
        {unit && <span className="text-sm font-medium text-slate-400">{unit}</span>}
      </div>
      {sub && <p className="mt-1 text-xs text-slate-400">{sub}</p>}
      {change && (
        <p className={`mt-1 text-xs font-medium ${changeColor}`}>
          {change.value > 0 ? "▲" : change.value < 0 ? "▼" : "•"} {Math.abs(change.value)}% {change.label}
        </p>
      )}
    </div>
  );
}