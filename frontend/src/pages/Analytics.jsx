import { useMemo } from "react";
import { Link } from "react-router-dom";
import SectionCard from "../components/cards/SectionCard.jsx";
import StatCard from "../components/cards/StatCard.jsx";
import ErrorState from "../components/cards/ErrorState.jsx";
import TrendBarChart from "../components/charts/TrendBarChart.jsx";
import { useApi } from "../hooks/useApi.js";
import { formatKWh } from "../utils/format.js";
import * as api from "../services/api.js";

const DAY_NAMES = [
  "Monday", "Tuesday", "Wednesday", "Thursday",
  "Friday", "Saturday", "Sunday",
];

export default function Analytics() {
  const analytics = useApi(() => api.getHouseholdAnalytics());

  const isOnboarding = analytics.error
    ? String(analytics.error).toLowerCase().includes("uploaded")
    : false;

  const data = analytics.data;
  const unit = data?.unit || "kWh";

  const byHour = useMemo(
    () =>
      (data?.by_hour || []).map((r) => ({
        label: `${String(r.value).padStart(2, "0")}:00`,
        value: r.mean,
        valueLabel: `Mean ${formatKWh(r.mean)} (${r.count} readings)`,
      })),
    [data]
  );

  const byDow = useMemo(
    () =>
      (data?.by_day_of_week || []).map((r) => ({
        label: (r.day_name || DAY_NAMES[r.value] || r.value).slice(0, 3),
        value: r.mean,
        valueLabel: `Mean ${formatKWh(r.mean)} (${r.count} readings)`,
      })),
    [data]
  );

  const byMonth = useMemo(
    () =>
      (data?.by_month || []).map((r) => ({
        label: (r.month_name || r.value || "").slice(0, 3),
        value: r.mean,
        valueLabel: `Mean ${formatKWh(r.mean)} (${r.count} readings)`,
      })),
    [data]
  );

  const monthlyTrend = useMemo(
    () =>
      (data?.monthly_trend || []).map((r) => ({
        label: r.month,
        value: r.total,
        valueLabel: `Total ${formatKWh(r.total)} · avg ${formatKWh(r.average_daily)}/day`,
      })),
    [data]
  );

  const distribution = useMemo(
    () =>
      (data?.distribution || []).map((r) => ({
        label: r.bin,
        value: r.count,
        valueLabel: `${r.count} readings in ${r.bin} ${unit}`,
      })),
    [data, unit]
  );

  if (isOnboarding) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Usage Analytics</h1>
          <p className="text-sm text-slate-400">
            Patterns, peak hours, weather relationships and anomalies from your uploaded data.
          </p>
        </div>
        <SectionCard title="Get started" subtitle="Analytics needs your consumption data">
          <div className="flex flex-col items-start gap-4 py-4 text-center sm:flex-row sm:text-left">
            <div className="text-3xl" aria-hidden="true">
              📊
            </div>
            <div className="flex-1">
              <p className="text-sm text-slate-200">
                Upload your household electricity consumption to see usage patterns — every chart is
                computed from your own file.
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

  const peakHours = data?.peak_hours || {};
  const peakRows = (peakHours.peak_hours || []).map((r) => r);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Usage Analytics</h1>
        <p className="text-sm text-slate-400">
          {data?.filename
            ? `Patterns from ${data.filename} (${data.rows.toLocaleString()} readings)`
            : "Hour / day / month patterns, peak hours, weather and anomalies"}
        </p>
      </div>

      {analytics.error ? (
        <ErrorState message={analytics.error} />
      ) : analytics.loading ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-64 animate-pulse rounded-xl border border-panel-edge bg-panel-edge/40" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <SectionCard title="Hourly Pattern" subtitle="Average consumption by hour of day">
              {byHour.length ? (
                <TrendBarChart rows={byHour} unit={unit} height={260} />
              ) : (
                <p className="text-sm text-slate-400">No sub-daily data to profile.</p>
              )}
            </SectionCard>

            <SectionCard title="Day-of-Week Pattern" subtitle="Average consumption by day of week">
              {byDow.length ? (
                <TrendBarChart rows={byDow} unit={unit} height={260} />
              ) : (
                <p className="text-sm text-slate-400">No weekly pattern available.</p>
              )}
            </SectionCard>
          </div>

          <SectionCard title="Monthly Pattern" subtitle="Average consumption by month of year">
            {byMonth.length ? (
              <TrendBarChart rows={byMonth} unit={unit} height={240} />
            ) : (
              <p className="text-sm text-slate-400">No monthly pattern available.</p>
            )}
          </SectionCard>

          <SectionCard title="Monthly Trend" subtitle="Total consumption per month (real history)">
            {monthlyTrend.length ? (
              <TrendBarChart rows={monthlyTrend} unit={unit} height={260} color="#10b981" />
            ) : (
              <p className="text-sm text-slate-400">Not enough monthly history.</p>
            )}
          </SectionCard>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <SectionCard title="Peak Hours" subtitle="Highest average hours of the day">
              <div className="space-y-2">
                {peakRows.length ? (
                  peakRows.map((r) => (
                    <div key={r.hour} className="flex items-center justify-between rounded-lg bg-surface/50 px-3 py-2">
                      <span className="text-sm text-slate-300">
                        {String(r.hour).padStart(2, "0")}:00
                      </span>
                      <span className="text-sm font-semibold text-white tabular-nums">{formatKWh(r.mean)}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-400">No sub-daily data.</p>
                )}
                <StatCard
                  label="Peak-to-average ratio"
                  value={peakHours.peak_to_average_ratio ?? "—"}
                  sub={peakRows[0] ? `Top hour ${String(peakRows[0].hour).padStart(2, "0")}:00` : "—"}
                />
              </div>
            </SectionCard>

            <SectionCard title="Distribution" subtitle="Histogram of consumption values">
              {distribution.length ? (
                <TrendBarChart rows={distribution} unit="readings" height={240} color="#f59e0b" />
              ) : (
                <p className="text-sm text-slate-400">No distribution available.</p>
              )}
            </SectionCard>

            <SectionCard title="Anomalies" subtitle="Rolling z-score vs your local average">
              <AnomalyPanel an={data?.anomalies} />
            </SectionCard>
          </div>

          <SectionCard
            title="Weather vs Consumption"
            subtitle="Correlations only from real weather that overlaps your history — never fabricated"
          >
            <WeatherPanel wc={data?.weather_correlations} unit={unit} />
          </SectionCard>
        </>
      )}
    </div>
  );
}

function AnomalyPanel({ an }) {
  if (!an) return <p className="text-sm text-slate-400">No anomaly data.</p>;
  if (an.available === false) {
    return <p className="text-sm text-slate-400">{an.note || an.message}</p>;
  }
  if (!an.count) {
    return <p className="text-sm text-slate-300">No statistically unusual readings detected.</p>;
  }
  return (
    <div className="space-y-2">
      <StatCard
        label="Unusual readings"
        value={an.count}
        badge={{ text: an.threshold ? `z ≥ ${an.threshold}` : "z ≥ 3", cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" }}
        sub={an.window ? `Rolling window ${an.window} periods` : undefined}
      />
      <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
        {(an.anomalies || []).map((a) => (
          <li key={a.timestamp} className="rounded-lg bg-surface/40 px-3 py-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-300">{a.timestamp}</span>
              <span className="rounded bg-rose-500/10 px-1.5 py-0.5 text-[10px] font-medium capitalize text-rose-300">
                {a.severity}
              </span>
            </div>
            <p className="mt-1 text-slate-400">
              Observed {a.observed} vs typical {a.historical_avg ?? "—"} ({a.deviation != null
                ? `${a.deviation > 0 ? "+" : ""}${a.deviation}`
                : "—"})
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function WeatherPanel({ wc, unit }) {
  if (!wc) return <p className="text-sm text-slate-400">No weather data.</p>;
  if (wc.available === false) {
    return <p className="text-sm text-slate-400">{wc.note}</p>;
  }
  return (
    <div>
      <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">
        Pearson correlations ({wc.overlap_rows.toLocaleString()} overlapping hours)
      </p>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(wc.correlations || []).map((c) => (
          <li key={c.variable} className="flex items-center justify-between rounded-lg bg-surface/50 px-3 py-2">
            <span className="text-sm capitalize text-slate-300">{c.variable.replace("_", " ")}</span>
            <span className="text-right">
              <span className="font-bold text-white tabular-nums">
                {c.pearson != null ? `${c.pearson > 0 ? "+" : ""}${c.pearson}` : "—"}
              </span>
              {c.interpretation && (
                <span className="block text-[11px] text-slate-500">{c.interpretation}</span>
              )}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Correlations describe association, not causation, and are only shown when real weather
        overlaps your uploaded timestamps ({unit}).
      </p>
    </div>
  );
}