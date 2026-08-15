import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { chartTime } from "../../utils/format.js";

/**
 * Regional Grid Demand Forecast — actual tail + predicted consumption.
 * Bounds are shown only if the API provides them (current model does not).
 */
export default function DemandForecastChart({ actual = [], predicted = [], bounds = null }) {
  const data = [
    ...actual.map((p) => ({ time: chartTime(p.timestamp), actual: p.value_mw })),
    ...predicted.map((p) => ({
      time: chartTime(p.timestamp),
      predicted: p.value_mw,
      lower: bounds?.lower?.[p.timestamp],
      upper: bounds?.upper?.[p.timestamp],
    })),
  ];

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2c4d" />
          <XAxis dataKey="time" tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} minTickGap={40} />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickLine={false}
            width={54}
            label={{ value: "MW", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
          />
          <Tooltip
            labelStyle={{ color: "#e2e8f0" }}
            formatter={(value, name) => [`${Number(value).toLocaleString()} MW`, name]}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "#cbd5e1" }} />
          {actual.length > 0 && <Line name="Actual" dataKey="actual" stroke="#64748b" strokeWidth={1.5} dot={false} />}
          <Line name="Predicted" dataKey="predicted" stroke="#3362fb" strokeWidth={2.5} dot={false} strokeDasharray="6 3" />
          {bounds && <Line name="Upper bound" dataKey="upper" stroke="#3362fb" strokeOpacity={0.25} strokeDasharray="3 3" dot={false} />}
          {bounds && <Line name="Lower bound" dataKey="lower" stroke="#3362fb" strokeOpacity={0.25} strokeDasharray="3 3" dot={false} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}