import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Generic bar trend (daily forecast, weekly trend, monthly trend).
 * Each row: { label, value (MW), valueLabel }
 */
export default function TrendBarChart({ rows = [], unit = "MW", color = "#3362fb", height = 280 }) {
  const data = rows.map((r) => ({ label: r.label, value: r.value, valueLabel: r.valueLabel || "" }));
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2c4d" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} interval="preserveStartEnd" />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickLine={false}
            width={54}
            label={{ value: unit, angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
          />
          <Tooltip
            cursor={{ fill: "rgba(51,98,251,0.08)" }}
            labelStyle={{ color: "#e2e8f0" }}
            formatter={(value, name, item) => {
              const label = item?.payload?.valueLabel || `${Number(value).toLocaleString()} ${unit}`;
              return [label, "Demand"];
            }}
          />
          <Bar dataKey="value" fill={color} radius={[3, 3, 0, 0]} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}