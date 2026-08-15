export default function SectionCard({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`rounded-xl border border-panel-edge bg-panel ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-panel-edge px-4 py-3">
        <div>
          <h2 className="font-semibold text-white tracking-tight">{title}</h2>
          {subtitle && <p className="text-xs text-slate-400">{subtitle}</p>}
        </div>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}