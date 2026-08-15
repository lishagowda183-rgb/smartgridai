export default function PeakAlertBanner({ peakHour, maxDemand, ratio, forecastPeaks = [] }) {
  if (peakHour === null || peakHour === undefined) return null;

  const next = forecastPeaks[0];

  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5 text-amber-400">
          <path d="M12 9v4M12 17h.01" strokeLinecap="round" />
          <path d="M10.3 3.8L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.8a2 2 0 00-3.4 0z" />
        </svg>
        <span className="text-sm font-semibold text-amber-200">
          Peak expected around {peakHour}:00
        </span>
      </div>
      <p className="mt-1 text-xs text-amber-200/80">
        Historic average peak hour of day on the regional grid.
        {maxDemand != null && <> All-time maximum demand {Number(maxDemand.value).toLocaleString()} MW.</>}
        {ratio != null && <> Peak-to-average ratio {ratio}.</>}
      </p>
      {next && (
        <p className="mt-1 text-xs text-amber-200/70">
          Predicted future peak period: {next.start} → {next.end} (peak ~{Number(next.peak_value).toLocaleString()} MW).
        </p>
      )}
    </div>
  );
}