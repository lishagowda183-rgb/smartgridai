import SectionCard from "../cards/SectionCard.jsx";
import { weatherBadge } from "../../utils/format.js";

function Metric({ label, value, unit }) {
  return (
    <div className="rounded-lg bg-surface/50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-white">
        {value ?? "—"}
        <span className="ml-1 text-xs font-normal text-slate-400">{unit}</span>
      </p>
    </div>
  );
}

/**
 * Always-rendered weather section (Phase 4.1).
 *
 * A) real weather available -> temp/humidity/precip/wind + status/source
 * B) long-term historical/seasonal patterns -> the honest label
 * C) fetch failure -> "temporarily unavailable" retry note, forecast continues
 *
 * `weather` is the forecast `weather` block; `now` is the dashboard `weather_now`
 * current observation. Never invents values the backend did not provide.
 */
export default function WeatherSection({ weather, now, title = "Weather" }) {
  const meta = weatherBadge(weather);
  const status = weather?.weather_status || weather?.status;
  const observation = now?.observation;
  const source = weather?.weather_source || now?.source || "Open-Meteo";

  return (
    <SectionCard title={title} subtitle={meta?.text || "Weather context for this forecast"}>
      {status === "temporarily_unavailable" ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <p className="font-semibold">Weather is temporarily unavailable</p>
          <p className="mt-1 text-xs text-amber-100/80">
            The automatic weather refresh failed, so this forecast continues with the available
            data and historical consumption patterns. Regenerate in a moment to retry.
          </p>
        </div>
      ) : (
        <>
          {observation && (
            <div className="mb-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-4xl font-bold tracking-tight text-white">
                  {observation.temperature_c ?? "—"}
                </span>
                <span className="text-slate-400">°C</span>
                <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs font-medium uppercase tracking-wide text-sky-300">
                  {observation.condition || "unknown"}
                </span>
              </div>
              <div className="mt-1 text-xs text-slate-400">
                Observed at {observation.time}
                {now?.generatedAt && <span> · API snapshot {now.generatedAt}</span>}
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Metric
              label="Temperature"
              value={observation?.temperature_c ?? (status === "not_available" ? "n/a" : "—")}
              unit="°C"
            />
            <Metric
              label="Humidity"
              value={observation?.humidity_pct ?? "—"}
              unit="%"
            />
            <Metric
              label="Precipitation"
              value={observation?.precipitation_mm ?? "—"}
              unit="mm"
            />
            <Metric
              label="Wind"
              value={observation?.wind_speed_kmh ?? "—"}
              unit="km/h"
            />
          </div>
          <p className="mt-3 rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-400">
            <span className="font-semibold text-slate-200">
              Status: {weather?.label || weather?.status} · Source: {source}
            </span>
            {(weather?.note || weather?.weather_note) && (
              <span className="mt-1 block">{weather?.note || weather?.weather_note}</span>
            )}
          </p>
          {weather?.weather_features_used?.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">
              Weather features used: {weather.weather_features_used.join(", ")}.
            </p>
          )}
        </>
      )}
    </SectionCard>
  );
}