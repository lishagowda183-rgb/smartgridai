import { Link } from "react-router-dom";
import SectionCard from "../components/cards/SectionCard.jsx";
import StatCard from "../components/cards/StatCard.jsx";
import { StatSkeleton } from "../components/cards/Skeleton.jsx";
import ErrorState from "../components/cards/ErrorState.jsx";
import EmptyState from "../components/cards/EmptyState.jsx";
import UploadForecastChart from "../components/charts/UploadForecastChart.jsx";
import WeatherSection from "../components/weather/WeatherSection.jsx";
import { useApi } from "../hooks/useApi.js";
import {
  formatInr,
  formatKWh,
  formatNumber,
  formatTime,
  statusChip,
  trendBadge,
  weatherBadge,
} from "../utils/format.js";
import * as api from "../services/api.js";

function KpiGrid({ children }) {
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">{children}</div>;
}

export default function Dashboard() {
  const dash = useApi(() => api.getDashboard());

  const data = dash.data;
  const isOnboarding = dash.error
    ? String(dash.error).toLowerCase().includes("uploaded")
    : data?.onboarding;

  if (isOnboarding) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Smart Energy Dashboard</h1>
          <p className="text-sm text-slate-400">
            Your weather-aware household electricity dashboard.
          </p>
        </div>
        <SectionCard title="Get started" subtitle="Everything runs on your own consumption data">
          <div className="flex flex-col items-start gap-4 py-4 text-center sm:flex-row sm:text-left">
            <div className="text-3xl" aria-hidden="true">
              ⚡
            </div>
            <div className="flex-1">
              <p className="text-sm text-slate-200">
                Upload your household electricity consumption (CSV or XLSX, in kWh) to unlock
                forecasts, analytics, bills and the AI assistant.
              </p>
              <p className="mt-1 text-xs text-slate-500">
                No sample data is ever shown — every figure is computed from your uploaded file.
              </p>
              <Link
                to="/forecast"
                className="mt-3 inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-500"
              >
                Upload consumption data
              </Link>
            </div>
          </div>
        </SectionCard>
      </div>
    );
  }

  const unit = data?.unit || "kWh";
  const current = data?.current || {};
  const week = data?.week || {};
  const month = data?.month || {};
  const peak = data?.peak || {};
  const weather = data?.weather;
  const bill = data?.household_bill;
  const statusMeta = statusChip(data?.status);
  const weatherMeta = weatherBadge(weather);

  const points = (data?.points || []).map((p) => ({
    timestamp: p.timestamp,
    value: p.predicted_consumption,
    lower: p.lower_bound,
    upper: p.upper_bound,
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Smart Energy Dashboard</h1>
          <p className="text-sm text-slate-400">
            {data?.filename ? (
              <>
                Household forecast for <b className="text-slate-200">{data.filename}</b> ·{" "}
                {data.frequency} · {scale(data.rows)} readings
              </>
            ) : (
              "Your weather-aware household electricity dashboard"
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusMeta.cls}`}>
            {statusMeta.text}
          </span>
          <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${weatherMeta.cls}`}>
            {weatherMeta.text}
          </span>
          {data?.trend && (
            <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${trendBadge(data.trend).cls}`}>
              {trendBadge(data.trend).text}
            </span>
          )}
        </div>
      </div>

      {dash.error ? (
        <ErrorState message={dash.error} />
      ) : dash.loading ? (
        <KpiGrid>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <StatSkeleton key={i} />
          ))}
        </KpiGrid>
      ) : (
        <>
          <KpiGrid>
            <StatCard
              label="Current Consumption"
              value={formatNumber(current.value)}
              unit={unit}
              badge={{ text: "Latest reading", cls: "border-teal-500/30 bg-teal-500/10 text-teal-300" }}
              sub={current.timestamp ? `Observed ${formatTime(current.timestamp)}` : "—"}
            />
            <StatCard
              label="Today (Forecast)"
              value={formatNumber(data?.today?.value)}
              unit={unit}
              sub={data?.today ? `Full day ${data.today.date}` : "No day forecast"}
            />
            <StatCard
              label="Tomorrow (Forecast)"
              value={formatNumber(data?.tomorrow?.value)}
              unit={unit}
              sub={data?.tomorrow ? `Full day ${data.tomorrow.date}` : "No day forecast"}
            />
            <StatCard
              label="This Week (Forecast)"
              value={formatNumber(week.total)}
              unit={unit}
              sub={
                week.start_date
                  ? `${week.start_date} → ${week.end_date} · avg ${formatKWh(week.average_daily)}/day`
                  : "No weekly forecast"
              }
              change={
                week.change_percent !== undefined && week.change_percent !== null
                  ? { value: week.change_percent, label: "vs historical baseline" }
                  : undefined
              }
            />
            <StatCard
              label="Next Month (Forecast)"
              value={formatNumber(month.total)}
              unit={unit}
              sub={month.days ? `Forecast ${month.days} days · avg ${formatKWh(month.average_daily)}/day` : "—"}
              change={
                month.change_percent !== undefined && month.change_percent !== null
                  ? { value: month.change_percent, label: "vs historical baseline" }
                  : undefined
              }
            />
            <StatCard
              label="Estimated Bill"
              value={bill ? formatInr(bill.total) : "—"}
              badge={{ text: "Household · INR", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" }}
              sub={bill ? `Next ${bill.forecasted_period || "month"} · ${formatKWh(bill.forecasted_monthly_kwh)}/mo` : "Bills require household kWh data"}
            />
          </KpiGrid>

          <SectionCard
            title="Consumption Forecast"
            subtitle={
              data?.display_label
                ? `${data.display_label} — model ${data.model}`
                : "Forecast from your uploaded history"
            }
            className="xl:col-span-2"
          >
            {points.length ? (
              <UploadForecastChart historical={data?.historical_tail || []} predicted={points} unit={unit} />
            ) : (
              <EmptyState message="No forecast points available." />
            )}
          </SectionCard>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <WeatherSection weather={weather} now={data?.weather_now} title="Weather" />

            <SectionCard title="Predicted Peak" subtitle="Peak period in this horizon">
              <div className="space-y-3">
                <StatCard
                  label="Peak value"
                  value={formatNumber(peak.value)}
                  unit={unit}
                  sub={peak.timestamp ? formatTime(peak.timestamp) : "—"}
                />
                <StatCard
                  label="Peak-to-average ratio"
                  value={formatNumber(peak.peak_to_average_ratio, 2)}
                  sub={peak.peak_hour !== null && peak.peak_hour !== undefined ? `Peak hour of day ${peak.peak_hour}:00` : "—"}
                />
              </div>
            </SectionCard>

            <SectionCard title="Forecast Components" subtitle="Model + weather status">
              <ul className="space-y-2 text-sm">
                <li className="flex items-center justify-between gap-3">
                  <span className="text-slate-400">Model</span>
                  <span className="text-right font-medium text-white">{data?.model || "—"}</span>
                </li>
                <li className="flex items-center justify-between gap-3">
                  <span className="text-slate-400">Weather</span>
                  <span className="text-right font-medium text-white">{weather?.label || "unavailable"}</span>
                </li>
                <li className="flex items-center justify-between gap-3">
                  <span className="text-slate-400">Trend</span>
                  <span className="text-right font-medium capitalize text-white">{data?.trend || "—"}</span>
                </li>
                {data?.model_features?.length > 0 && (
                  <li className="pt-1">
                    <p className="mb-1 text-xs uppercase tracking-wide text-slate-500">Features</p>
                    <div className="flex flex-wrap gap-1">
                      {data.model_features.map((f) => (
                        <span key={f} className="rounded bg-surface/60 px-1.5 py-0.5 text-[10px] text-slate-400">
                          {f}
                        </span>
                      ))}
                    </div>
                  </li>
                )}
              </ul>
            </SectionCard>
          </div>

          {data?.recommendations?.length > 0 && (
            <SectionCard title="Recommendations" subtitle="Derived from your forecast + history">
              <ul className="space-y-2">
                {data.recommendations.map((r) => (
                  <li key={r.id} className="rounded-lg bg-surface/40 px-3 py-2 text-sm text-slate-300">
                    {r.message}
                    {r.basis && <p className="mt-0.5 text-xs text-slate-500">{r.basis}</p>}
                  </li>
                ))}
              </ul>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}

function scale(n) {
  return n >= 1000 ? `${(n / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k` : n;
}