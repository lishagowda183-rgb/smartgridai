import EmptyState from "../cards/EmptyState.jsx";
import { formatTime } from "../../utils/format.js";

function Metric({ label, value, unit }) {
  return (
    <div className="rounded-lg bg-surface/50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-white">
        {value}
        <span className="ml-1 text-xs font-normal text-slate-400">{unit}</span>
      </p>
    </div>
  );
}

export default function WeatherNow({ current, location, generatedAt, loading, error }) {
  if (loading) {
    return (
      <div className="space-y-3 p-1">
        <div className="animate-pulse rounded-xl bg-panel-edge/70 h-10 w-36" />
        <div className="animate-pulse rounded-xl bg-panel-edge/70 h-20" />
      </div>
    );
  }
  if (error) return <EmptyState message={error} />;
  if (!current) return <EmptyState message="Weather unavailable from backend." />;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-4xl font-bold text-white tracking-tight">{current.temperature_c ?? "—"}</span>
        <span className="text-slate-400">°C</span>
        <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs font-medium text-sky-300 uppercase tracking-wide">
          {current.condition || "unknown"}
        </span>
      </div>
      <div className="mt-1 text-xs text-slate-400">
        Observed at {formatTime(current.time)}
        {generatedAt && <span> · API snapshot {formatTime(generatedAt)}</span>}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="Humidity" value={current.humidity_pct ?? "—"} unit="%" />
        <Metric label="Precipitation" value={current.precipitation_mm ?? "—"} unit="mm" />
        <Metric label="Wind" value={current.wind_speed_kmh ?? "—"} unit="km/h" />
        <Metric label="Weather code" value={current.weather_code ?? "—"} unit="WMO" />
      </div>
      {location && (
        <div className="mt-3 text-xs text-slate-400">
          {location.timezone || "—"} · {location.timezone_abbreviation || ""} · lat {location.latitude} · lon{" "}
          {location.longitude}
        </div>
      )}
    </div>
  );
}