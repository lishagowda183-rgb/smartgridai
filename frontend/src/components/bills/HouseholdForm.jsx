import { useState } from "react";
import { BillLine, ScopeTag } from "./BillCommon.jsx";

export default function HouseholdForm({
  tariffs = [],
  onSubmit,
  busy,
  error,
  initialTariff = "household_slabs",
  onPersistPreference,
}) {
  const [monthlyKwh, setMonthlyKwh] = useState("350");
  const [tariff, setTariff] = useState(initialTariff);
  const [peakShare, setPeakShare] = useState("40");
  const [validationError, setValidationError] = useState(null);

  const submit = (e) => {
    e.preventDefault();
    const raw = String(monthlyKwh).trim();
    if (raw === "") {
      setValidationError("Enter a monthly consumption in kWh.");
      return;
    }
    const num = Number(raw);
    if (Number.isNaN(num)) {
      setValidationError("Monthly consumption must be a valid number of kWh.");
      return;
    }
    if (num < 0) {
      setValidationError("Monthly consumption cannot be negative.");
      return;
    }
    setValidationError(null);
    onSubmit({
      monthly_kwh: num,
      tariff,
      peak_share_pct: Number(peakShare),
    });
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="text-xs text-slate-400">Monthly consumption</span>
          <div className="mt-1 flex overflow-hidden rounded-lg border border-panel-edge bg-surface/50">
            <input
              type="number"
              min="0"
              step="any"
              value={monthlyKwh}
              onChange={(e) => setMonthlyKwh(e.target.value)}
              className="w-full bg-transparent px-3 py-2 text-sm text-white outline-none"
              aria-label="Monthly consumption kWh"
            />
            <span className="flex items-center border-l border-panel-edge px-3 text-xs text-slate-400">kWh</span>
          </div>
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Household tariff</span>
          <select
            value={tariff}
            onChange={(e) => {
              setTariff(e.target.value);
              onPersistPreference?.(e.target.value);
            }}
            className="mt-1 w-full rounded-lg border border-panel-edge bg-surface/50 px-3 py-2 text-sm text-white outline-none"
            aria-label="Household tariff"
          >
            {tariffs.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Peak share % (TOU only)</span>
          <input
            type="number"
            min="0"
            max="100"
            step="any"
            value={peakShare}
            onChange={(e) => setPeakShare(e.target.value)}
            className="mt-1 w-full rounded-lg border border-panel-edge bg-surface/50 px-3 py-2 text-sm text-white outline-none"
            aria-label="Peak share percent"
          />
        </label>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-500 disabled:opacity-50"
        >
          {busy ? "Calculating…" : "Calculate Bill"}
        </button>
        {error && <span className="text-xs text-rose-400">{error}</span>}
        {validationError && <span className="text-xs text-rose-400">{validationError}</span>}
      </div>
    </form>
  );
}

export function HouseholdBillResult({ bill }) {
  if (!bill) return null;
  return (
    <div className="mt-4 rounded-xl border border-panel-edge bg-surface/40 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTag scope={bill.scope || "household"} />
        <span className="text-xs text-slate-400">
          {bill.tariff_unit || "INR/kWh"} · {bill.reporting_period || "1 month"}
        </span>
      </div>
      {bill.assumption && <p className="mt-2 text-xs text-slate-400">{bill.assumption}</p>}
      <div className="mt-3 divide-y divide-panel-edge border-t border-panel-edge">
        <BillLine label={`Consumption (${bill.consumption_unit || "kWh"})`} value={`${Number(bill.monthly_consumption_kwh).toLocaleString()} kWh`} />
        <BillLine label="Energy charge" value={bill.energy_charge != null ? `₹${Number(bill.energy_charge).toLocaleString()}` : "—"} />
        <BillLine label="Fixed charge" value={bill.fixed_charge != null ? `₹${Number(bill.fixed_charge).toLocaleString()}` : "—"} />
        {(bill.additional_charges > 0 || bill.additional_charges == null) && (
          <BillLine label="Additional charges" value={bill.additional_charges != null ? `₹${Number(bill.additional_charges).toLocaleString()}` : "—"} />
        )}
        <BillLine label={`Tax (${bill.tax_pct ?? 0}%)`} value={bill.taxes != null ? `₹${Number(bill.taxes).toLocaleString()}` : "—"} />
        <BillLine label={`Total bill (${bill.currency ?? "INR"})`} value={`₹${Number(bill.total).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} bold />
      </div>
      {bill.peak_kwh != null && (
        <p className="mt-2 text-xs text-slate-400">
          Peak {Number(bill.peak_kwh).toLocaleString()} kWh · Off-peak {Number(bill.off_peak_kwh).toLocaleString()} kWh
        </p>
      )}
    </div>
  );
}