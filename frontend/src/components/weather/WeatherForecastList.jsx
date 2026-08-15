import EmptyState from "../cards/EmptyState.jsx";
import { formatTime } from "../../utils/format.js";

export default function WeatherForecastList({ points = [], loading, error }) {
  if (loading) return <EmptyState message="Loading weather forecast…" />;
  if (error) return <EmptyState message={error} />;
  if (!points.length) return <EmptyState message="No weather forecast available." />;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {points.map((p) => (
        <div key={p.time} className="rounded-lg border border-panel-edge bg-surface/40 px-3 py-2">
          <p className="text-[11px] text-slate-500">{formatTime(p.time)}</p>
          <p className="mt-1 font-semibold text-white">{p.temperature_c ?? "—"} °C</p>
          <p className="mt-1 line-clamp-1 text-[11px] uppercase tracking-wide text-sky-300">{p.condition || "—"}</p>
          <p className="text-[11px] text-slate-500">
            H {p.humidity_pct ?? "—"}% · 💧 {p.precipitation_mm ?? "—"} mm · 💨 {p.wind_speed_kmh ?? "—"}
          </p>
        </div>
      ))}
    </div>
  );
}