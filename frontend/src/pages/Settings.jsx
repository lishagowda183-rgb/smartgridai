import SectionCard from "../components/cards/SectionCard.jsx";
import ErrorState from "../components/cards/ErrorState.jsx";
import { useApi } from "../hooks/useApi.js";
import { getStoredCurrency, setStoredCurrency } from "../utils/format.js";
import * as api from "../services/api.js";

function Row({ label, value, muted }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-panel-edge/60 py-2.5">
      <span className="text-sm text-slate-400">{label}</span>
      <span className={`text-sm font-medium ${muted ? "text-slate-500" : "text-white"}`}>{value || "—"}</span>
    </div>
  );
}

export default function Settings() {
  const health = useApi(api.getHealth);
  const datasets = useApi(api.listDatasets);

  const currency = getStoredCurrency();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Settings</h1>
        <p className="text-sm text-slate-400">API connection, location and display preferences.</p>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <SectionCard title="API Connection" subtitle="SmartGridAI FastAPI backend">
          {health.error ? (
            <ErrorState message={`Backend unreachable: ${health.error}`} onRetry={health.refresh} />
          ) : health.loading ? (
            <p className="text-sm text-slate-400">Checking connection…</p>
          ) : (
            <div>
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                <span className="text-sm font-semibold text-emerald-300">Connected</span>
              </div>
              <div className="mt-3">
                <Row label="App" value={`${health.data.app} v${health.data.version}`} />
                <Row label="Status" value={health.data.status} />
                <Row label="Base URL" value={api.default.BASE_URL} />
                <Row label="Prefix" value={health.data.prefix} />
                <Row label="API timestamp" value={health.data.timestamp} muted />
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Household Data" subtitle="Your uploaded consumption datasets (local, ephemeral)">
          {datasets.error ? (
            <ErrorState message={datasets.error} onRetry={datasets.refresh} />
          ) : datasets.loading ? (
            <p className="text-sm text-slate-400">Loading datasets…</p>
          ) : datasets.data?.datasets?.length ? (
            <div>
              <p className="mb-2 text-sm text-slate-400">
                {datasets.data.total} dataset(s) · active:{" "}
                <b className="text-slate-200">{datasets.data.active_dataset_id ? "household" : "none"}</b>
              </p>
              <ul className="space-y-2">
                {datasets.data.datasets.map((d) => (
                  <li key={d.dataset_id} className="rounded-lg bg-surface/40 px-3 py-2 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium text-white">{d.filename}</span>
                      <span className="text-xs text-slate-500">{d.scope?.scope || "household"}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {d.rows} rows · {d.frequency} · {d.start_date} → {d.end_date}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-slate-400">Nothing uploaded yet — data stays on this machine.</p>
          )}
        </SectionCard>
      </div>

      <SectionCard title="Display Preferences" subtitle="Local-only (browser storage). Backend calculations are always in INR.">
        <div className="flex flex-wrap items-center gap-4">
          <label className="block">
            <span className="text-xs text-slate-400">Preferred currency (display only)</span>
            <select
              value={currency}
              onChange={(e) => {
                setStoredCurrency(e.target.value);
                window.location.reload();
              }}
              className="mt-1 rounded-lg border border-panel-edge bg-surface/50 px-3 py-2 text-sm text-white outline-none"
            >
              <option value="INR">₹ INR</option>
              <option value="USD">$ USD</option>
              <option value="EUR">€ EUR</option>
            </select>
          </label>
          <p className="text-xs text-slate-500">
            Bills are always computed in INR by the backend. This setting only changes how the symbol is
            rendered in the UI.
          </p>
        </div>
      </SectionCard>
    </div>
  );
}