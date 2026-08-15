export default function EmptyState({ message }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-panel-edge bg-surface/40 px-4 py-8 text-center">
      <div className="text-2xl" aria-hidden="true">🌤</div>
      <p className="mt-2 text-sm text-slate-400">{message || "No data available."}</p>
    </div>
  );
}