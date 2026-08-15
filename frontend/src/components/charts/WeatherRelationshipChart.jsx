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
 * Weather–demand relationship from real aligned data
 * (/analytics/weather-relationship): mean demand per temperature bucket.
 */
export default function WeatherRelationshipChart({ buckets = [] }) {
  const data = buckets.map((b) => ({
    label: `${b.min_temp}°`,
    mean_consumption_mw: b.mean_consumption_mw,
    count: b.count,
  }));

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2c4d" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickLine={false}
            width={54}
            label={{ value: "Mean demand (MW)", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
          />
          <Tooltip
            cursor={{ fill: "rgba(51,98,251,0.08)" }}
            labelStyle={{ color: "#e2e8f0" }}
            formatter={(value, _n, item) => [
              `${Number(value).toLocaleString()} MW (${item?.payload?.count || 0} hrs)`,
              "Mean demand",
            ]}
          />
          <Bar dataKey="mean_consumption_mw" fill="#f59e0b" radius={[3, 3, 0, 0]} maxBarSize={40} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}