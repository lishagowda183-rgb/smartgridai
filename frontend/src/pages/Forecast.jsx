import UploadWorkspace from "../components/forecast/UploadWorkspace.jsx";

export default function Forecast() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Household Consumption Forecast</h1>
        <p className="text-sm text-slate-400">
          Upload your household consumption (CSV/XLSX, kWh) and generate a flexible forecast — short-term
          forecasts are weather-aware when real future weather overlaps the period.
        </p>
      </div>

      <UploadWorkspace />

      <p className="rounded-lg bg-surface/40 px-3 py-2 text-xs text-slate-500">
        All values are produced by the backend forecasting engine from <b>your uploaded data</b> — no values
        are invented on the client, and no regional-grid dataset is used.
      </p>
    </div>
  );
}