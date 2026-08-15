/**
 * Deterministic recommendation cards. Each card includes the computed `basis`
 * that triggered it, so claims are traceable to real forecast results.
 */
export default function RecommendationsList({ recommendations = [] }) {
  if (!recommendations.length) return null;
  return (
    <ul className="space-y-2">
      {recommendations.map((rec) => (
        <li key={rec.id} className="rounded-lg border border-panel-edge bg-surface/40 p-3">
          <div className="flex items-start gap-2">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="mt-0.5 h-4 w-4 shrink-0 text-brand-300">
              <path d="M9 12l2 2 4-4M12 3l7 4v5c0 4-3 6.5-7 8-4-1.5-7-4-7-8V7l7-4z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div>
              <p className="text-sm text-slate-200">{rec.message}</p>
              <p className="mt-0.5 text-xs text-slate-500">Basis: {rec.basis}</p>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}