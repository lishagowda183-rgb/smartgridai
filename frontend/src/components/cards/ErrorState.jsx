export default function ErrorState({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-rose-500/30 bg-rose-500/5 px-4 py-8 text-center">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-8 w-8 text-rose-400">
        <path d="M12 9v4M12 17h.01" strokeLinecap="round" />
        <path d="M10.3 3.8L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.8a2 2 0 00-3.4 0z" />
      </svg>
      <p className="mt-2 text-sm text-rose-200">{message || "Something went wrong."}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-lg border border-panel-edge bg-panel px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-panel-edge/60"
        >
          Retry
        </button>
      )}
    </div>
  );
}