import { CLASS_LEVELS, classChip } from "../../utils/format.js";

/**
 * LOW / MEDIUM / HIGH classification view: horizontal bars per bucket with
 * percentages, plus the derived thresholds (documented as percentiles of the
 * uploaded history).
 */
export default function ClassificationBars({ classification, unit = "kWh" }) {
  if (!classification) return null;
  const { counts = {}, percentages = {}, thresholds = {}, method, note } = classification;
  const levels = [
    { level: "LOW", ...CLASS_LEVELS.LOW },
    { level: "MEDIUM", ...CLASS_LEVELS.MEDIUM },
    { level: "HIGH", ...CLASS_LEVELS.HIGH },
  ].map((meta) => ({
    ...meta,
    count: counts[meta.level] ?? 0,
    pct: percentages[meta.level] ?? 0,
  }));
  const maxPct = Math.max(1, ...levels.map((l) => l.pct));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {levels.map(({ level, label, barClass, color, count, pct }) => (
          <div key={level} className="rounded-lg border border-panel-edge bg-surface/40 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-white">{label}</span>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${classChip(level).chipClass}`}>
                {pct}%
              </span>
            </div>
            <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-panel-edge/60">
              <div
                className={`h-full rounded-full ${barClass}`}
                style={{ width: `${Math.min(100, Math.round((pct / maxPct) * 100))}%`, backgroundColor: color }}
              />
            </div>
            <p className="mt-1 text-xs text-slate-400">
              {count} periods
            </p>
          </div>
        ))}
      </div>

      {thresholds.low != null && thresholds.high != null && (
        <div className="rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-400">
          <span className="font-semibold text-slate-200">Thresholds ({unit}):</span>{" "}
          Low {"<"} {Number(thresholds.low).toLocaleString()} · Medium{" "}
          {Number(thresholds.low).toLocaleString()}–{Number(thresholds.high).toLocaleString()} · High{" "}
          {">"} {Number(thresholds.high).toLocaleString()} · {method || note || ""}
        </div>
      )}
    </div>
  );
}