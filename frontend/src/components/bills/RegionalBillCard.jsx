import { BillLine, ScopeTag } from "./BillCommon.jsx";
import ErrorState from "../cards/ErrorState.jsx";
import EmptyState from "../cards/EmptyState.jsx";
import { StatSkeleton } from "../cards/Skeleton.jsx";
import { formatInr, formatMWh, formatNumber } from "../../utils/format.js";

export default function RegionalBillCard({ report, loading, error, onRecompute, recomputing }) {
  if (loading) return <StatSkeleton />;
  if (error) return <ErrorState message={error} />;
  if (!report) return <EmptyState message="Regional bill report not available." />;

  const cur = report.current_bill || {};
  const units = report.units || {};
  const comparison = report.comparison || {};
  const savings = report.what_if?.peak_shift_savings;
  const sanity = cur.sanity_notes || [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <ScopeTag scope={units.scope || "regional_grid"} />
        <span className="text-xs text-slate-400">
          Reporting period <b className="text-slate-200">{cur.period_label || "—"}</b> · {units.tariff_unit || "INR/MWh"}
        </span>
        {report._served_from && (
          <span className="text-[10px] uppercase tracking-wide text-slate-500">
            served from {report._served_from}
          </span>
        )}
      </div>

      <div className="rounded-xl border border-panel-edge bg-surface/40 p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-slate-400">Regional Grid Energy Cost</p>
            <p className="mt-1 text-3xl font-bold text-white tabular-nums">{formatInr(cur.total)}</p>
            <p className="mt-1 text-xs text-slate-500">
              {formatMWh(cur.energy_mwh)} consumed · {formatNumber(cur.energy_kwh)} kWh equivalent
            </p>
          </div>
          <div className="text-right text-xs text-slate-400">
            {comparison.previous_month && (
              <p>
                vs {comparison.previous_month}{" "}
                <b className={comparison.change_vs_previous_pct >= 0 ? "text-rose-400" : "text-emerald-400"}>
                  {comparison.change_vs_previous_pct >= 0 ? "+" : ""}
                  {comparison.change_vs_previous_pct}%
                </b>
              </p>
            )}
            {comparison.year_ago_month && (
              <p>
                YoY vs {comparison.year_ago_month}{" "}
                <b className={comparison.change_yoy_pct >= 0 ? "text-rose-400" : "text-emerald-400"}>
                  {comparison.change_yoy_pct >= 0 ? "+" : ""}
                  {comparison.change_yoy_pct}%
                </b>
              </p>
            )}
          </div>
        </div>

        <div className="mt-4 divide-y divide-panel-edge border-t border-panel-edge">
          <BillLine label={`Energy charge (${units.energy_unit || "MWh"})`} value={formatInr(cur.energy_charge)} />
          <BillLine label="Fixed charge" value={formatInr(cur.fixed_charge)} />
          {cur.additional_charges > 0 && (
            <BillLine label="Additional charges" value={formatInr(cur.additional_charges)} />
          )}
          <BillLine label={`Tax (${cur.tax_pct ?? 0}%)`} value={formatInr(cur.taxes)} />
          <BillLine label="Total regional energy cost" value={formatInr(cur.total)} bold />
        </div>

        {cur.peak_mwh != null && (
          <p className="mt-3 text-xs text-slate-400">
            Peak {formatMWh(cur.peak_mwh, 3)} · Off-peak {formatMWh(cur.off_peak_mwh, 3)}
          </p>
        )}
      </div>

      {savings?.applicable && (
        <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-4">
          <p className="text-sm font-semibold text-emerald-300">Estimated peak-shift savings</p>
          <p className="mt-1 text-2xl font-bold text-white">{formatInr(savings.estimated_savings)}</p>
          <p className="mt-1 text-xs text-slate-400">{savings.assumption}</p>
          <p className="mt-1 text-xs text-slate-500">
            Estimated single-month figure for {savings.period_label}; not a guaranteed recurring amount.
          </p>
        </div>
      )}

      {sanity.length > 0 && (
        <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-200/90">
          <b>Sanity note:</b> {sanity.join(" ")}
        </div>
      )}

      <p className="rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-400">
        This is a <b>regional-scale analytical estimate</b> based on grid demand data. It is{" "}
        <b>not a household electricity bill</b>.
      </p>

      {onRecompute && (
        <button
          type="button"
          onClick={onRecompute}
          disabled={recomputing}
          className="rounded-lg border border-panel-edge bg-panel px-3 py-2 text-xs font-medium text-slate-200 hover:bg-panel-edge/60 disabled:opacity-50"
        >
          {recomputing ? "Recomputing (iterated forecast)…" : "Recompute regional bill report"}
        </button>
      )}
    </div>
  );
}