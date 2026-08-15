import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/** Average regional demand by hour of day (from /analytics/peak-hours). */
export default function PeakHourChart({ rows = [], peakHour = null }) {
  const data = rows.map((r) => ({
    hour: `${String(r.hour).padStart(2, "0")}:00`,
    mean_mw: r.mean_consumption,
  }));

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2c4d" />
          <XAxis dataKey="hour" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} interval={3} />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickLine={false}
            width={54}
            label={{ value: "MW", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
          />
          <Tooltip
            cursor={{ fill: "rgba(51,98,251,0.08)" }}
            labelStyle={{ color: "#e2e8f0" }}
            formatter={(value) => [`${Number(value).toLocaleString()} MW`, "Mean demand"]}
          />
          {peakHour !== null && peakHour !== undefined && (
            <ReferenceLine x={`${String(peakHour).padStart(2, "0")}:00`} stroke="#f59e0b" strokeWidth={1.5} />
          )}
          <Bar dataKey="mean_mw" fill="#3362fb" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}