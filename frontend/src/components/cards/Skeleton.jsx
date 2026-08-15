export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-md bg-panel-edge/70 ${className}`} />;
}

export function StatSkeleton() {
  return (
    <div className="rounded-xl border border-panel-edge bg-panel p-4">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-7 w-32" />
      <Skeleton className="mt-2 h-3 w-20" />
    </div>
  );
}