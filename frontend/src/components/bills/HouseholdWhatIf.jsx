import { useState } from "react";
import { BillLine } from "./BillCommon.jsx";

/**
 * Household what-if: +10% / -10% / custom consumption. All numbers come from
 * FastAPI (/bills/household/what-if); React never recomputes tariffs.
 */
export default function HouseholdWhatIf({ tariff, onSubmit, busy, error }) {
  const [customKwh, setCustomKwh] = useState("");
  const [shiftPct, setShiftPct] = useState("10");

  const submitBase = (e) => {
    e?.preventDefault?.();
    onSubmit({
      monthly_kwh: 350,
      tariff,
      custom_kwh: null,
      peak_share_pct: 40,
      peak_shift_pct: Number(shiftPct) || 0,
    });
  };

  const submitScenario = (scenario) => (e) => {
    e?.preventDefault?.();
    onSubmit({
      monthly_kwh: 350,
      tariff,
      custom_kwh: scenario.custom ? Number(customKwh) : null,
      plus_pct: scenario.plus != null ? scenario.plus : 10.0,
      minus_pct: scenario.minus != null ? scenario.minus : 10.0,
      peak_share_pct: 40,
      peak_shift_pct: Number(shiftPct) || 0,
    });
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-400">
        “What if my electricity consumption changes?” — all scenarios are calculated by the backend.
      </p>

      {error && <p className="text-xs text-rose-400">{error}</p>}

      <div className="flex flex-wrap items-end gap-3">
        <label>
          <span className="text-xs text-slate-400">Base monthly consumption</span>
          <input
            type="number"
            min="0"
            step="any"
            defaultValue={350}
            data-testid="whatif-base"
            className="mt-1 rounded-lg border border-panel-edge bg-surface/50 px-3 py-2 text-sm text-white outline-none"
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">Peak-shift % (TOU)</span>
          <input
            type="number"
            min="0"
            max="100"
            value={shiftPct}
            onChange={(e) => setShiftPct(e.target.value)}
            className="mt-1 w-20 rounded-lg border border-panel-edge bg-surface/50 px-3 py-2 text-sm text-white outline-none"
          />
        </label>
        <button type="button" onClick={submitBase} disabled={busy} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-500 disabled:opacity-50">
          {busy ? "Running…" : "Run Scenarios"}
        </button>
        <button type="button" onClick={submitScenario({ plus: 10, minus: 10, custom: false })} disabled={busy} aria-label="Scenario plus 10 percent" className="rounded-lg border border-panel-edge bg-panel px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-panel-edge/60 disabled:opacity-50">
          +10%
        </button>
        <button type="button" onClick={submitScenario({ plus: 10, minus: 10, custom: false })} disabled={busy} aria-label="Scenario minus 10 percent" className="rounded-lg border border-panel-edge bg-panel px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-panel-edge/60 disabled:opacity-50">
          −10%
        </button>
      </div>

      <form onSubmit={submitScenario({ custom: true })} className="flex flex-wrap items-end gap-3">
        <label>
          <span className="text-xs text-slate-400">Custom kWh</span>
          <input
            type="number"
            min="0"
            step="any"
            placeholder="300"
            value={customKwh}
            onChange={(e) => setCustomKwh(e.target.value)}
            className="mt-1 rounded-lg border border-panel-edge bg-surface/50 px-3 py-2 text-sm text-white outline-none"
            aria-label="Custom kWh"
          />
        </label>
        <button type="submit" disabled={busy} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-500 disabled:opacity-50">
          {busy ? "Running…" : "Calculate Custom"}
        </button>
      </form>
    </div>
  );
}

export function HouseholdWhatIfResult({ result }) {
  if (!result) return null;
  const base = result.base || {};
  const diff = result.bill_difference || {};
  const savings = result.estimated_savings;
  const inr = (v) => `₹${Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <div className="mt-4 rounded-xl border border-panel-edge bg-surface/40 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-surface/50 p-3">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">Base bill</p>
          <p className="mt-1 text-xl font-bold text-white">{inr(base.total)}</p>
          <p className="text-xs text-slate-400">{Number(base.monthly_consumption_kwh).toLocaleString()} kWh</p>
        </div>
        <div className="rounded-lg bg-surface/50 p-3">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">+10%</p>
          <p className="mt-1 text-xl font-bold text-white">{inr(result.plus_10pct?.total)}</p>
          <p className={`text-xs ${result.plus_10pct?.change_pct >= 0 ? "text-rose-400" : "text-emerald-400"}`}>
            {Number(result.plus_10pct?.consumption_kwh ?? base.monthly_consumption_kwh).toLocaleString()} kWh · {result.plus_10pct?.change_pct}%
          </p>
        </div>
        <div className="rounded-lg bg-surface/50 p-3">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">−10%</p>
          <p className="mt-1 text-xl font-bold text-white">{inr(result.minus_10pct?.total)}</p>
          <p className={`text-xs ${result.minus_10pct?.change_pct >= 0 ? "text-rose-400" : "text-emerald-400"}`}>
            {Number(result.minus_10pct?.consumption_kwh ?? base.monthly_consumption_kwh).toLocaleString()} kWh · {result.minus_10pct?.change_pct}%
          </p>
        </div>
      </div>

      {result.custom && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg bg-surface/50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Custom consumption</p>
            <p className="mt-1 text-xl font-bold text-white">{inr(result.custom.total)}</p>
            <p className="text-xs text-slate-400">{Number(result.custom.monthly_consumption_kwh).toLocaleString()} kWh · {result.custom.change_pct}%</p>
          </div>
          <div className="rounded-lg bg-surface/50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Bill difference</p>
            <p className={`mt-1 text-xl font-bold ${diff.amount >= 0 ? "text-rose-400" : "text-emerald-400"}`}>
              {diff.amount >= 0 ? "+" : ""}{inr(diff.amount)}
            </p>
            <p className="text-xs text-slate-400">
              {Number(diff.from_consumption_kwh).toLocaleString()} → {Number(diff.to_consumption_kwh).toLocaleString()} kWh · {diff.pct}%
            </p>
          </div>
        </div>
      )}

      {savings?.applicable && (
        <div className="mt-3 rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-3">
          <p className="text-xs font-semibold text-emerald-300">Estimated peak→off-peak shift savings</p>
          <p className="mt-1 text-xl font-bold text-white">{inr(savings.savings_per_month)}/month</p>
          <p className="mt-1 text-xs text-slate-400">{savings.assumption}</p>
        </div>
      )}

      <div className="mt-3 divide-y divide-panel-edge border-t border-panel-edge">
        <BillLine label="Tariff" value={result.tariff_unit || "INR/kWh"} muted />
        <BillLine label="Reporting period" value={result.reporting_period || "1 month"} muted />
      </div>
    </div>
  );
}