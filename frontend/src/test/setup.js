import "@testing-library/jest-dom";
import { vi } from "vitest";

// Recharts is heavy and pulls in ESM/CJS surprises under jsdom; stub it in tests.
vi.mock("recharts", async () => {
  const React = await import("react");
  const passthrough = (props) => React.createElement("div", { "data-testid": "chart-mock" });
  return {
    ResponsiveContainer: passthrough,
    LineChart: passthrough,
    Line: passthrough,
    BarChart: passthrough,
    Bar: passthrough,
    XAxis: passthrough,
    YAxis: passthrough,
    Tooltip: passthrough,
    Legend: passthrough,
    CartesianGrid: passthrough,
    ReferenceLine: passthrough,
    Cell: passthrough,
  };
});