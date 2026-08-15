/**
 * Formatting + scope/unit helpers. Currency display preference is cosmetic
 * only — the backend always calculates bills in INR.
 */

const CURRENCY_KEY = "smartgridai.ui.currency";

export function getStoredCurrency() {
  try {
    return localStorage.getItem(CURRENCY_KEY) || "INR";
  } catch {
    return "INR";
  }
}

export function setStoredCurrency(value) {
  try {
    localStorage.setItem(CURRENCY_KEY, value);
  } catch {
    /* ignore */
  }
}

export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function formatMW(value, digits = 0) {
  return `${formatNumber(value, digits)} MW`;
}

export function formatMWh(value, digits = 0) {
  return `${formatNumber(value, digits)} MWh`;
}

export function formatInr(value, digits = 2) {
  const sym = getStoredCurrency() === "INR" ? "₹" : getStoredCurrency() + " ";
  return `${sym}${formatNumber(value, digits)}`;
}

export function formatTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Short ISO timestamp for chart axes (e.g. "Dec 31 23:00"). */
export function chartTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit" });
}

// --- scope/unit metadata -------------------------------------------------------

export const REGIONAL_SCOPE = {
  scope: "regional_grid",
  label: "Regional Grid",
  demandUnit: "MW",
  energyUnit: "MWh",
  tariffUnit: "INR/MWh",
};

export const HOUSEHOLD_SCOPE = {
  scope: "household",
  label: "Household",
  consumptionUnit: "kWh",
  energyUnit: "kWh",
  tariffUnit: "INR/kWh",
  reportingPeriod: "1 month",
};

export function scopeBadge(scope) {
  if (scope === "household") return { text: "Household", cls: "bg-teal-500/15 text-teal-300 border-teal-500/30" };
  if (scope === "regional_grid") return { text: "Regional Grid", cls: "bg-brand-500/15 text-brand-300 border-brand-500/30" };
  return { text: scope || "—", cls: "bg-slate-500/15 text-slate-300 border-slate-500/30" };
}

// --- household energy helpers ---------------------------------------------------

export function formatKWh(value, digits = 1) {
  return `${formatNumber(value, digits)} kWh`;
}

export function formatEnergy(value, unit = "kWh", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${formatNumber(value, digits)} ${unit}`;
}

export function statusChip(status) {
  if (status === "HIGH") return { text: "High usage", cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" };
  if (status === "LOW") return { text: "Low usage", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
  return { text: "Medium usage", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
}

export function weatherBadge(weather) {
  const status = weather?.weather_status || weather?.status;
  if (status === "full") return { text: "Weather-aware", cls: "border-sky-500/30 bg-sky-500/10 text-sky-300" };
  if (status === "partial") return { text: "Weather partially available", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
  if (status === "not_available") return { text: "Historical weather patterns", cls: "border-indigo-500/30 bg-indigo-500/10 text-indigo-300" };
  if (status === "temporarily_unavailable") return { text: "Weather temporarily unavailable", cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" };
  return { text: "Consumption-only", cls: "border-slate-500/30 bg-slate-500/10 text-slate-300" };
}

export function trendBadge(trend) {
  const t = String(trend || "").toUpperCase();
  if (t === "INCREASING") return { text: "Increasing trend", cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" };
  if (t === "DECREASING") return { text: "Decreasing trend", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
  return { text: "Stable trend", cls: "border-slate-500/30 bg-slate-500/10 text-slate-300" };
}

// --- phase 11: generic-unit formatting + classification helpers ------------------

export function formatValue(value, unit, digits = 1) {
  return `${formatNumber(value, digits)} ${unit}`;
}

export const CLASS_LEVELS = {
  LOW: {
    label: "Low",
    color: "#10b981",
    barClass: "bg-emerald-500",
    chipClass: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  },
  MEDIUM: {
    label: "Medium",
    color: "#f59e0b",
    barClass: "bg-amber-500",
    chipClass: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  },
  HIGH: {
    label: "High",
    color: "#f43f5e",
    barClass: "bg-rose-500",
    chipClass: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  },
};

export function classChip(level) {
  const meta = CLASS_LEVELS[level] || { ...CLASS_LEVELS.MEDIUM, label: level || "—" };
  return meta;
}

export const HORIZON_PRESETS = [
  { label: "1 Day", value: 1, unit: "days" },
  { label: "7 Days", value: 7, unit: "days" },
  { label: "30 Days", value: 30, unit: "days" },
  { label: "3 Months", value: 3, unit: "months" },
  { label: "6 Months", value: 6, unit: "months" },
  { label: "1 Year", value: 1, unit: "years" },
  { label: "2 Years", value: 2, unit: "years" },
];