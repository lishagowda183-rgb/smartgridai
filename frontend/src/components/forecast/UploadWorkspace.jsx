import { useMemo, useState } from "react";
import SectionCard from "../cards/SectionCard.jsx";
import StatCard from "../cards/StatCard.jsx";
import ErrorState from "../cards/ErrorState.jsx";
import UploadForecastChart from "../charts/UploadForecastChart.jsx";
import ClassificationBars from "./ClassificationBars.jsx";
import RecommendationsList from "./RecommendationsList.jsx";
import FestivalSection from "./FestivalSection.jsx";
import WeatherSection from "../weather/WeatherSection.jsx";
import { HORIZON_PRESETS, formatValue, scopeBadge, chartTime } from "../../utils/format.js";
import * as api from "../../services/api.js";

const HORIZON_UNITS = ["days", "months", "years"];

function xLabelFor(granularity) {
  if (["hourly", "30min", "15min"].includes(granularity)) return chartTime;
  return (iso) => String(iso).slice(0, 10);
}

export default function UploadWorkspace() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dataset, setDataset] = useState(null);
  const [detail, setDetail] = useState(null);

  const [horizonMode, setHorizonMode] = useState("preset");
  const [customValue, setCustomValue] = useState("2");
  const [customUnit, setCustomUnit] = useState("days");
  const [horizon, setHorizon] = useState(HORIZON_PRESETS[0]);
  const [scopeOverride, setScopeOverride] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState("");
  const [result, setResult] = useState(null);

  const currentHorizon = useMemo(() => {
    if (horizonMode === "custom") {
      return { value: Math.max(1, parseInt(customValue || "1", 10) || 1), unit: customUnit };
    }
    return horizon;
  }, [horizonMode, horizon, customValue, customUnit]);

  async function handleUpload() {
    if (!file) {
      setUploadError("Choose a CSV or XLSX file first.");
      return;
    }
    setUploading(true);
    setUploadError("");
    setDataset(null);
    setDetail(null);
    setResult(null);
    try {
      const summary = await api.uploadDataset(file);
      setDataset(summary);
      const d = await api.getDataset(summary.dataset_id);
      setDetail(d);
    } catch (err) {
      setUploadError(err.message || "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  function pickPreset(p) {
    setHorizon(p);
    setHorizonMode("preset");
  }

  async function handleGenerate() {
    if (!dataset) return;
    setGenerating(true);
    setGenerateError("");
    setResult(null);
    try {
      const payload = {
        dataset_id: dataset.dataset_id,
        horizon_value: currentHorizon.value,
        horizon_unit: currentHorizon.unit,
      };
      if (scopeOverride) payload.scope = scopeOverride;
      const r = await api.generateForecast(payload);
      setResult(r);
    } catch (err) {
      setGenerateError(err.message || "Forecast generation failed.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleExport() {
    if (!result) return;
    try {
      await api.exportForecastCsv({
        dataset_id: result.dataset_id,
        horizon_value: result.horizon.value,
        horizon_unit: result.horizon.unit,
      });
    } catch (err) {
      setUploadError(err.message || "Export failed.");
    }
  }

  const chartHistorical = (result?.historical || []).map((p) => ({ timestamp: p.timestamp, value: p.value }));
  const chartPredicted = (result?.points || []).map((p) => ({
    timestamp: p.timestamp,
    value: p.predicted_consumption,
    lower: p.lower_bound,
    upper: p.upper_bound,
  }));

  const statusMeta = {
    valid: { text: "VALID", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
    warn: { text: "WARN", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" },
    invalid: { text: "INVALID", cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
  }[dataset?.validation_status] || null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Upload Your Data &amp; Flexible Forecast</h1>
        <p className="text-sm text-slate-400">
          Upload a CSV/XLSX consumption file. The forecast runs entirely on <b>your uploaded data</b> — never
          the project's regional-grid series. CSV/XLSX, timestamp + consumption columns are auto-detected.
        </p>
      </div>

      {/* ---- Upload ---- */}
      <SectionCard
        title="1 · Upload Data"
        subtitle={"Supported: CSV / XLSX — timestamp (timestamp/datetime/date/time) + consumption (load/demand/energy/kWh)"}
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="block min-w-56 flex-1">
            <span className="mb-1 block text-xs text-slate-400">Choose CSV/XLSX</span>
            <input
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-white hover:file:bg-brand-500"
            />
          </label>
          <button
            type="button"
            onClick={handleUpload}
            disabled={uploading || !file}
            className="rounded-lg bg-brand-600 px-4 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {uploading ? "Uploading…" : "Upload & Validate"}
          </button>
        </div>

        {uploadError && <div className="mt-3"><ErrorState message={uploadError} /></div>}

        {dataset && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-white">{dataset.filename}</span>
              {statusMeta && (
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${statusMeta.cls}`}>{statusMeta.text}</span>
              )}
              {dataset.scope?.scope && (
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${scopeBadge(dataset.scope.scope).cls}`}>
                  {scopeBadge(dataset.scope.scope).text}
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard label="Rows" value={dataset.rows.toLocaleString()} sub={`${dataset.rows_total.toLocaleString()} raw`} />
              <StatCard label="Date range" value={dataset.start_date?.slice(0, 10)} sub={`→ ${dataset.end_date?.slice(0, 10)}`} />
              <StatCard label="Frequency" value={dataset.frequency} />
              <StatCard label="Scope / unit" value={dataset.scope?.scope || "—"} unit={dataset.unit || ""} />
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-300">
                <span className="text-slate-500">Timestamp column:</span> <b>{dataset.timestamp_column}</b>
                <br />
                <span className="text-slate-500">Consumption column:</span> <b>{dataset.consumption_column}</b>
                {dataset.scope?.note && <div className="mt-1 text-slate-500">{dataset.scope.note}</div>}
              </div>
              <div className="rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-300">
                <span className="text-slate-500">Mean / Median / Max ({dataset.unit}):</span>{" "}
                <b>
                  {dataset.statistics?.mean?.toLocaleString()} / {dataset.statistics?.median?.toLocaleString()} /{" "}
                  {dataset.statistics?.max?.toLocaleString()}
                </b>
              </div>
            </div>

            {dataset.scope?.need_selection && (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                Scope could not be confidently detected — select Household or Regional Grid in the forecast
                settings below.
              </p>
            )}

            {dataset.warnings?.length > 0 && (
              <ul className="space-y-1">
                {dataset.warnings.map((w, i) => (
                  <li key={i} className="rounded bg-amber-500/10 px-3 py-1 text-xs text-amber-300">{w.message}</li>
                ))}
              </ul>
            )}

            <div className="overflow-x-auto rounded-lg border border-panel-edge">
              <table className="w-full text-left text-xs">
                <caption className="px-3 py-2 text-left text-slate-500">Data preview (first rows)</caption>
                <thead className="bg-surface/60 text-slate-400">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">Timestamp</th>
                    <th className="px-3 py-1.5 font-medium">Consumption</th>
                  </tr>
                </thead>
                <tbody className="text-slate-300">
                  {(detail?.preview || []).map((row, i) => (
                    <tr key={i} className="border-t border-panel-edge/60">
                      <td className="px-3 py-1">{row.timestamp}</td>
                      <td className="px-3 py-1">{row.consumption?.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </SectionCard>

      {/* ---- Forecast settings ---- */}
      <SectionCard title="2 · Forecast Settings" subtitle="Choose a horizon, then generate the forecast">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {HORIZON_PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => pickPreset(p)}
              className={`rounded-lg border px-2 py-2 text-center transition-colors ${
                horizonMode === "preset" && horizon.value === p.value && horizon.unit === p.unit
                  ? "border-brand-500/60 bg-brand-500/10"
                  : "border-panel-edge bg-panel hover:bg-panel-edge/50"
              }`}
            >
              <span className="block text-sm font-semibold text-white">{p.label}</span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => setHorizonMode(horizonMode === "custom" ? "preset" : "custom")}
            className={`rounded-lg border px-2 py-2 text-center transition-colors ${
              horizonMode === "custom" ? "border-brand-500/60 bg-brand-500/10" : "border-panel-edge bg-panel hover:bg-panel-edge/50"
            }`}
          >
            <span className="block text-sm font-semibold text-white">Custom</span>
          </button>
        </div>

        {horizonMode === "custom" && (
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="mb-1 block text-xs text-slate-400">Number</span>
              <input
                type="number"
                min="1"
                value={customValue}
                onChange={(e) => setCustomValue(e.target.value)}
                className="w-24 rounded-lg border border-panel-edge bg-surface px-3 py-1.5 text-sm text-white"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-400">Unit</span>
              <select
                value={customUnit}
                onChange={(e) => setCustomUnit(e.target.value)}
                className="rounded-lg border border-panel-edge bg-surface px-3 py-1.5 text-sm text-white"
              >
                {HORIZON_UNITS.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </label>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-400">Scope override (optional)</span>
            <select
              value={scopeOverride}
              onChange={(e) => setScopeOverride(e.target.value)}
              className="rounded-lg border border-panel-edge bg-surface px-3 py-1.5 text-sm text-white"
            >
              <option value="">Auto (detected)</option>
              <option value="household">Household · kWh</option>
              <option value="regional_grid">Regional Grid · MW/MWh</option>
            </select>
          </label>
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating || !dataset}
            className="rounded-lg bg-brand-600 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {generating ? "Forecasting…" : "Generate Forecast"}
          </button>
          {!dataset && <p className="text-xs text-slate-500">Upload a dataset first.</p>}
        </div>
        {generateError && <div className="mt-3"><ErrorState message={generateError} /></div>}
      </SectionCard>

      {/* ---- Results ---- */}
      {result && (
        <div className="space-y-6">
          <WeatherSection weather={result.weather} title="Weather" />

          <SectionCard
            title="3 · Forecast Results"
            action={
              <button
                type="button"
                onClick={handleExport}
                className="rounded-lg border border-brand-500/40 bg-brand-500/10 px-3 py-1 text-xs font-semibold text-brand-300 transition-colors hover:bg-brand-500/20"
              >
                &#8595; Export CSV
              </button>
            }
            subtitle={`${result.filename} — ${result.forecast_type_label} · ${result.horizon.value} ${result.horizon.unit} · displayed ${result.display_granularity}`}
          >
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard
                label="Average predicted"
                value={formatValue(result.summary.average, result.unit)}
                sub={`per ${result.display_granularity} period`}
              />
              <StatCard label="Expected total" value={formatValue(result.summary.total, result.energy_unit)} />
              <StatCard
                label="Peak"
                value={formatValue(result.summary.maximum, result.unit)}
                sub={`at ${result.peak.peak_time_label}`}
              />
              <StatCard
                label="Change vs baseline"
                value={`${result.summary.change_percent >= 0 ? "+" : ""}${result.summary.change_percent}%`}
                badge={
                  result.summary.change_percent > 0
                    ? { text: "▲ up", cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" }
                    : result.summary.change_percent < 0
                      ? { text: "▼ down", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" }
                      : { text: "flat", cls: "border-slate-500/30 bg-slate-500/10 text-slate-300" }
                }
              />
            </div>

            {(result.model || result.trend) && (
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                {result.model && (
                  <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-0.5 font-medium text-sky-300">
                    Model: {result.model}
                  </span>
                )}
                {result.trend && (
                  <span className="rounded-full border border-slate-500/30 bg-slate-500/10 px-2.5 py-0.5 font-medium capitalize text-slate-300">
                    {result.trend} trend
                  </span>
                )}
                {result.status && (
                  <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 font-medium text-amber-300">
                    Status: {result.status}
                  </span>
                )}
              </div>
            )}

            {!result.intervals_available && (
              <div className="mt-3 rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-500">
                Prediction interval unavailable for this model.
              </div>
            )}

            <div className="mt-4">
              <UploadForecastChart
                historical={chartHistorical}
                predicted={chartPredicted}
                unit={result.unit}
                xLabel={xLabelFor(result.display_granularity)}
              />
            </div>
          </SectionCard>

          <SectionCard title="Consumption status" subtitle="Household-relative: compared against this dataset's own historical distribution">
            <div className="flex items-center gap-3">
              <span className={`rounded-full border px-2.5 py-0.5 text-xs font-bold ${
                result.status === "HIGH"
                  ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
                  : result.status === "LOW"
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                    : "border-amber-500/30 bg-amber-500/10 text-amber-300"
              }`}>
                {result.status}
              </span>
              <span className="text-xs text-slate-400">
                Forecast average vs historical baseline:&nbsp;
                <b className="text-white">
                  {formatValue(result.classification.forecast_mean, result.unit)}
                </b>
                &nbsp;vs&nbsp;
                <b className="text-white">
                  {formatValue(result.classification.historical_mean, result.unit)}
                </b>
                &nbsp;({result.classification.forecast_change_percent >= 0 ? "+" : ""}
                {result.classification.forecast_change_percent}%)
              </span>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard
                label="Historical average"
                value={formatValue(result.classification.historical_mean, result.unit)}
                sub={`per ${result.display_granularity} period`}
              />
              <StatCard
                label="Forecast average"
                value={formatValue(result.classification.forecast_mean, result.unit)}
                sub={`per ${result.display_granularity} period`}
              />
              <StatCard
                label="High periods"
                value={`${result.classification.high_period_count} (${result.classification.high_period_percentage}%)`}
                sub="at/above historical p90"
              />
              <StatCard
                label="Forecast peak"
                value={formatValue(result.classification.forecast_peak, result.unit)}
                sub="over the forecast period"
              />
            </div>

            {result.classification.reason && (
              <p className="mt-3 rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-400">
                <span className="font-semibold text-slate-200">Why: </span>
                {result.classification.reason}
              </p>
            )}

            {(result.warning || result.classification.warning) && (
              <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                <span className="font-bold">Model diagnostic: </span>
                {result.warning || result.classification.warning}
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <SectionCard title="Low / Medium / High classification" subtitle={result.classification.note}>
              <ClassificationBars classification={result.classification} unit={result.unit} />
            </SectionCard>

            <SectionCard title="Peak analysis">
              <div className="space-y-2 text-sm">
                <p className="flex justify-between"><span className="text-slate-400">Predicted peak</span> <b className="text-white">{formatValue(result.peak.value, result.unit)}</b></p>
                <p className="flex justify-between"><span className="text-slate-400">Peak period</span> <b className="text-white">{result.peak.peak_time_label}</b></p>
                {result.peak.peak_hour != null && (
                  <p className="flex justify-between"><span className="text-slate-400">Peak hour</span> <b className="text-white">{String(result.peak.peak_hour).padStart(2, "0")}:00</b></p>
                )}
                <p className="flex justify-between"><span className="text-slate-400">Average consumption</span> <b className="text-white">{formatValue(result.peak.average, result.unit)}</b></p>
                <p className="flex justify-between"><span className="text-slate-400">Peak-to-average ratio</span> <b className="text-white">{result.peak.peak_to_average_ratio}</b></p>
              </div>
            </SectionCard>
          </div>

          {result.household_bill && (
            <SectionCard title="Estimated household bill" subtitle="Calculated by the backend bill engine (household scope only)">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <StatCard label="Forecasted monthly kWh" value={formatNumber(result.household_bill.forecasted_monthly_kwh, 1)} />
                <StatCard label="Tariff" value={result.household_bill.tariff_unit} sub={result.household_bill.total && "estimated monthly total"} />
                <StatCard
                  label="Estimated monthly bill"
                  value={`₹${Number(result.household_bill.total).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
                  badge={{ text: "household", cls: "border-teal-500/30 bg-teal-500/10 text-teal-300" }}
                />
              </div>
              {result.household_bill.assumption && (
                <p className="mt-3 rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-500">{result.household_bill.assumption}</p>
              )}
            </SectionCard>
          )}

          {result.festivals && (
            <FestivalSection festivals={result.festivals} />
          )}

          <SectionCard title="Recommendations" subtitle="Deterministic, computed from the forecast results above">
            <RecommendationsList recommendations={result.recommendations} />
          </SectionCard>

          {result.forecast_type === "long_term" && (
            <p className="rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-500">
              {result.weather?.note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}