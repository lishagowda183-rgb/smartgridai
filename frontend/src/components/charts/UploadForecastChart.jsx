import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { chartTime } from "../../utils/format.js";

/**
 * Historical + predicted consumption chart for the user upload workspace.
 *
 * Historical (solid) ends where the forecast (dashed) begins; a ReferenceLine
 * labeled "Forecast starts here" marks the transition. Prediction bounds are
 * drawn only when the backend provides them (intervals_available).
 *
 * `xLabel` maps a timestamp to an axis label (hourly -> short chartTime,
 * daily/weekly/monthly -> date), so long horizons never render thousands of
 * points.
 */
export default function UploadForecastChart({
  historical = [],
  predicted = [],
  unit = "kWh",
  xLabel = (t) => chartTime(t),
}) {
  const data = [
    ...historical.map((p) => ({
      time: xLabel(p.timestamp),
      label: p.timestamp,
      actual: p.value,
    })),
    ...predicted.map((p) => ({
      time: xLabel(p.timestamp),
      label: p.timestamp,
      predicted: p.value,
      lower: p.lower,
      upper: p.upper,
    })),
  ];

  const transitionIndex = historical.length;
  const transitionX = data[transitionIndex]?.time;
  const hasBounds = predicted.some((p) => p.lower != null && p.upper != null);

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2c4d" />
          <XAxis dataKey="time" tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} minTickGap={48} />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            tickLine={false}
            width={64}
            label={{ value: unit, angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
          />
          <Tooltip
            labelStyle={{ color: "#e2e8f0" }}
            formatter={(value, name) => [`${Number(value).toLocaleString()} ${unit}`, name]}
            labelFormatter={(label, payload) => payload?.[0]?.payload?.label || label}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "#cbd5e1" }} />
          {historical.length > 0 && (
            <Line name="Historical" dataKey="actual" stroke="#64748b" strokeWidth={1.5} dot={false} />
          )}
          <Line name="Forecast" dataKey="predicted" stroke="#3362fb" strokeWidth={2.5} dot={false} strokeDasharray="6 3" />
          {hasBounds && (
            <Line name="Upper bound" dataKey="upper" stroke="#3362fb" strokeOpacity={0.25} strokeDasharray="3 3" dot={false} />
          )}
          {hasBounds && (
            <Line name="Lower bound" dataKey="lower" stroke="#3362fb" strokeOpacity={0.25} strokeDasharray="3 3" dot={false} />
          )}
          {transitionX != null && (
            <ReferenceLine
              x={transitionX}
              stroke="#f59e0b"
              strokeDasharray="4 4"
              label={{
                value: "Forecast starts here",
                position: "top",
                fill: "#f59e0b",
                fontSize: 11,
              }}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}