import { useState } from "react";
import Sidebar from "./Sidebar.jsx";

export default function AppLayout({ children }) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="flex h-full">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center gap-3 border-b border-panel-edge bg-surface px-4 lg:px-6">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            className="rounded-lg p-2 text-slate-300 hover:bg-panel-edge/60 lg:hidden"
            aria-label="Open navigation"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-6 w-6">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="text-sm text-slate-400">
            Household electricity forecasts · AI Energy Assistant
          </div>
          <div className="ml-auto hidden items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300 sm:flex">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            Live API
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">{children}</main>
      </div>
    </div>
  );
}