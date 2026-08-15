import SectionCard from "../cards/SectionCard.jsx";

const EFFECT_BADGES = {
  HIGHER_THAN_NORMAL: { text: "Higher usage", cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
  LOWER_THAN_NORMAL: { text: "Lower usage", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
  SIMILAR_TO_NORMAL: { text: "Similar to normal", cls: "border-slate-500/30 bg-slate-500/10 text-slate-300" },
};

function effectBadge(cls) {
  return EFFECT_BADGES[cls] || { text: "—", cls: "border-slate-500/30 bg-slate-500/10 text-slate-300" };
}

function shortDate(iso) {
  if (!iso) return "—";
  return String(iso).slice(0, 10);
}

export default function FestivalSection({ festivals = {} }) {
  const analysis = festivals.analysis || [];
  const upcoming = festivals.upcoming || [];
  const applied = festivals.applied || [];

  const appliedByKey = new Map();
  for (const ap of applied) {
    appliedByKey.set(`${ap.festival_name}|${ap.date}`, ap);
  }

  if (!festivals || (!analysis.length && !upcoming.length)) {
    return (
      <SectionCard
        title="Festival / calendar awareness"
        subtitle="Deterministic Indian festival & holiday calendar for the forecast period"
      >
        <p className="text-xs text-slate-400">
          No festival information was returned for this forecast.
        </p>
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="Festival / calendar awareness"
      subtitle="Deterministic festival & holiday dates for the forecast period — household-specific effects learned only from your uploaded history"
    >
      {festivals.note && <p className="text-xs text-slate-400">{festivals.note}</p>}

      {upcoming.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Upcoming in the forecast period
          </h3>
          <ul className="mt-2 space-y-1.5">
            {upcoming.map((u) => {
              const hasEffect = Boolean(u.festival_data_available);
              const badge = effectBadge(u.historical_classification);
              const appliedEntry = appliedByKey.get(`${u.festival_name}|${u.date}`);
              return (
                <li key={`${u.festival_name}-${u.date}`} className="rounded-lg border border-panel-edge bg-surface/40 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-white">
                      {u.festival_name}
                      <span className="ml-2 text-xs font-normal text-slate-400">{shortDate(u.date)}</span>
                    </span>
                    {u.national_holiday && (
                      <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[10px] font-bold text-indigo-300">
                        National holiday
                      </span>
                    )}
                    {hasEffect && (
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}>
                        {badge.text}
                      </span>
                    )}
                    {appliedEntry?.applied_multiplier != null && (
                      <span className="rounded-full border border-brand-500/40 bg-brand-500/10 px-2 py-0.5 text-[10px] font-bold text-brand-300">
                        Forecast adjusted ×{appliedEntry.applied_multiplier}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                    <span>Window {shortDate(u.window_start)} → {shortDate(u.window_end)}</span>
                    {hasEffect && u.festival_effect_percent != null && (
                      <span className="text-slate-300">
                        Forecast {u.festival_effect_percent >= 0 ? "+" : ""}
                        {u.festival_effect_percent}% vs normal (from your history)
                      </span>
                    )}
                  </div>
                  {u.note && <p className="mt-1 text-[11px] text-slate-500">{u.note}</p>}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {analysis.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            What your history shows (household observations)
          </h3>
          <ul className="mt-2 space-y-1.5">
            {analysis.map((a) => {
              const badge = effectBadge(a.classification);
              return (
                <li key={`${a.festival_name}-${a.date}`} className="rounded-lg border border-panel-edge bg-surface/40 px-3 py-2 text-xs text-slate-300">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-white">
                      {a.festival_name}
                      <span className="ml-2 font-normal text-slate-400">{shortDate(a.date)}</span>
                    </span>
                    {a.data_available && (
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}>
                        {badge.text}
                      </span>
                    )}
                    {!a.data_available && (
                      <span className="rounded-full border border-slate-500/30 bg-slate-500/10 px-2 py-0.5 text-[10px] font-bold text-slate-300">
                        Insufficient data
                      </span>
                    )}
                  </div>
                  {a.data_available && (
                    <p className="mt-1 text-slate-400">
                      {a.difference_percent >= 0 ? "+" : ""}
                      {a.difference_percent}% vs comparable baseline (
                      {a.festival_average_kwh} vs {a.normal_average_kwh} avg, {a.observation_count} observations)
                    </p>
                  )}
                  {!a.data_available && (
                    <p className="mt-1 text-slate-500">
                      {a.observation_count}/{a.minimum_observations} observations in window — {a.note}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {applied.length > 0 && (
        <p className="mt-3 rounded-lg border border-brand-500/40 bg-brand-500/10 px-3 py-2 text-xs text-brand-200">
          The forecast was adjusted for <b>{applied.length}</b> festival window
          {applied.length > 1 ? "s" : ""} using your observed history.
        </p>
      )}
    </SectionCard>
  );
}