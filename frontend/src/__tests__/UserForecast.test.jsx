import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApiModule, uploadedDataset, forecastResult } from "./fixtures.js";

const api = vi.hoisted(() => ({}));
vi.mock("../services/api.js", () => api);

import UploadWorkspace from "../components/forecast/UploadWorkspace.jsx"; // eslint-disable-line import/first

function makeFile(name = "my_energy.csv") {
  return new File(["timestamp,consumption\n2024-01-01 00:00:00,320\n"], name, { type: "text/csv" });
}

async function uploadFlow() {
  render(<UploadWorkspace />);
  const input = screen.getByLabelText(/choose csv\/xlsx/i);
  fireEvent.change(input, { target: { files: [makeFile()] } });
  await userEvent.click(screen.getByRole("button", { name: /upload & validate/i }));
  await screen.findByText("VALID");
  return input;
}

beforeEach(() => {
  for (const key of Object.keys(api)) delete api[key];
  Object.assign(api, createApiModule(vi));
});

describe("UploadWorkspace (Phase 11)", () => {
  it("renders the workspace heading and horizon presets", async () => {
    render(<UploadWorkspace />);
    expect(await screen.findByText(/upload your data/i)).toBeInTheDocument();
    expect(screen.getByText("1 Day")).toBeInTheDocument();
    expect(screen.getByText("30 Days")).toBeInTheDocument();
    expect(screen.getByText("2 Years")).toBeInTheDocument();
  });

  it("uploads a file, shows the validation report and preview", async () => {
    await uploadFlow();
    expect(api.uploadDataset).toHaveBeenCalled();
    expect(screen.getByText("my_energy.csv")).toBeInTheDocument();
    expect(screen.getByText("VALID")).toBeInTheDocument();
    expect(screen.getByText("Household")).toBeInTheDocument();
    expect(screen.getByText("hourly")).toBeInTheDocument();
    expect(api.getDataset).toHaveBeenCalledWith("ds_test1");
    expect(screen.getByText("2024-01-01 00:00:00")).toBeInTheDocument();
  });

  it("surfaces an upload error to the user", async () => {
    api.uploadDataset.mockRejectedValueOnce(new Error("unsupported file type '.txt'"));
    render(<UploadWorkspace />);
    const input = screen.getByLabelText(/choose csv\/xlsx/i);
    fireEvent.change(input, { target: { files: [makeFile("bad.txt")] } });
    await userEvent.click(screen.getByRole("button", { name: /upload & validate/i }));
    expect(await screen.findByText(/unsupported file type/i)).toBeInTheDocument();
  });

  it("generates a 30-day forecast and renders the results dashboard", async () => {
    await uploadFlow();
    await userEvent.click(screen.getByText("30 Days"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));

    await waitFor(() => {
      expect(api.generateForecast).toHaveBeenCalledWith({
        dataset_id: "ds_test1",
        horizon_value: 30,
        horizon_unit: "days",
      });
    });

    // Summary cards + forecast type label
    expect(await screen.findByText(/Average predicted/i)).toBeInTheDocument();
    expect(screen.getByText(/Medium-term \(8 days – 6 months\)/i)).toBeInTheDocument();
    // Bounds note only when intervals are unavailable
    expect(screen.queryByText(/Prediction interval unavailable/i)).not.toBeInTheDocument();
    // Classification + thresholds
    expect(screen.getByText(/Thresholds \(kWh\)/i)).toBeInTheDocument();
    // Peak analysis
    expect(screen.getByText(/Peak-to-average ratio/i)).toBeInTheDocument();
    // Recommendations
    expect(screen.getByText(/fairly stable compared/i)).toBeInTheDocument();
    // Weather note always rendered by the shared WeatherSection
    expect(screen.getByText(/No future weather data is available/i)).toBeInTheDocument();
  });

  it("renders the weather section with honest status, source and features used", async () => {
    const result = forecastResult();
    result.weather = {
      status: "full",
      label: "available",
      weather_status: "full",
      weather_available: true,
      weather_source: "Open-Meteo",
      weather_features_used: ["temperature", "humidity"],
      weather_note: "Weather-aware forecast: future weather is available and can be used for this period.",
      note: "Weather-aware forecast: future weather is available and can be used for this period.",
    };
    api.generateForecast.mockResolvedValue(result);

    await uploadFlow();
    await userEvent.click(screen.getByText("30 Days"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));

    expect(await screen.findByText(/Weather-aware forecast/i)).toBeInTheDocument();
    // Explicit source + exact features that entered the model (never hidden).
    expect(screen.getByText(/Source: Open-Meteo/i)).toBeInTheDocument();
    expect(screen.getByText(/weather features used: temperature, humidity/i)).toBeInTheDocument();
  });

  it("renders the explainable consumption-status section", async () => {
    await uploadFlow();
    await userEvent.click(screen.getByText("30 Days"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));

    await screen.findByText(/Consumption status/i);
    expect(screen.getAllByText(/Average consumption/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/High periods/i)).toBeInTheDocument();
    expect(screen.getByText(/Forecast peak/i)).toBeInTheDocument();
    // Explainable "why" string with actual numbers.
    expect(screen.getByText(/household historical baseline/i)).toBeInTheDocument();
    // Household-relative framing is always called out.
    expect(screen.getByText(/this dataset's own historical distribution/i)).toBeInTheDocument();
  });

  it("shows the model-diagnostic warning when the forecast is far below baseline", async () => {
    const result = forecastResult();
    result.warning =
      "The forecast average (350 kWh) is significantly below the uploaded historical baseline (9000 kWh, change -96.1%).";
    result.classification.warning = result.warning;
    result.trend = "DECREASING";
    api.generateForecast.mockResolvedValue(result);

    await uploadFlow();
    await userEvent.click(screen.getByText("30 Days"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));

    expect(await screen.findByText(/Model diagnostic:/i)).toBeInTheDocument();
    expect(screen.getByText(/significantly below the uploaded historical baseline/i)).toBeInTheDocument();
  });

  it("uses a custom horizon (2 years) when selected", async () => {
    await uploadFlow();
    await userEvent.click(screen.getByText("Custom"));
    const number = screen.getByLabelText(/number/i);
    fireEvent.change(number, { target: { value: "2" } });
    const unit = screen.getByLabelText(/unit/i);
    fireEvent.change(unit, { target: { value: "years" } });
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));

    await waitFor(() => {
      expect(api.generateForecast).toHaveBeenCalledWith({
        dataset_id: "ds_test1",
        horizon_value: 2,
        horizon_unit: "years",
      });
    });
  });

  it("shows the household bill estimate and exports CSV", async () => {
    await uploadFlow();
    await userEvent.click(screen.getByText("30 Days"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));
    await screen.findByText(/Estimated household bill/i);
    expect(screen.getByText(/INR\/kWh/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /export csv/i }));
    await waitFor(() => {
      expect(api.exportForecastCsv).toHaveBeenCalledWith({
        dataset_id: "ds_test1",
        horizon_value: 30,
        horizon_unit: "days",
      });
    });
  });

  it("labels long-term weather limitation when the backend reports it", async () => {
    const longTerm = forecastResult();
    longTerm.forecast_type = "long_term";
    longTerm.weather.status = "not_available";
    longTerm.weather.note =
      "Long-term forecast uses historical weather relationships and seasonal patterns. Exact future weather is not available at this horizon.";
    longTerm.household_bill = null;
    api.generateForecast.mockResolvedValue(longTerm);

    await uploadFlow();
    await userEvent.click(screen.getByText("1 Year"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));
    const notes = await screen.findAllByText(/historical weather relationships and seasonal patterns/i);
    expect(notes.length).toBeGreaterThanOrEqual(1);
    // A bill is only ever attached for household scope (regional grid never).
    expect(screen.queryByText(/Estimated household bill/i)).not.toBeInTheDocument();
  });

  it("renders the festival / calendar awareness section from the backend block", async () => {
    await uploadFlow();
    await userEvent.click(screen.getByText("30 Days"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));

    expect(await screen.findByText(/Festival \/ calendar awareness/i)).toBeInTheDocument();
    // Calendar dates for the forecast period are KNOWN, not guessed.
    expect(screen.getByText(/KNOWN from the deterministic calendar/i)).toBeInTheDocument();
    // Upcoming festivals: Diwali (observed effect) + Christmas (national holiday).
    expect(screen.getAllByText("Diwali").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Christmas")).toBeInTheDocument();
    expect(screen.getByText("National holiday")).toBeInTheDocument();
    expect(screen.getAllByText(/Higher usage/i).length).toBeGreaterThanOrEqual(1);
    // The observed Diwali effect was applied to the forecast.
    expect(screen.getByText(/Forecast adjusted ×1.26/i)).toBeInTheDocument();
    expect(screen.getByText(/festival window.*using your observed history/i)).toBeInTheDocument();
    // Household analysis rows (data_available + insufficient).
    expect(screen.getByText(/What your history shows/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Insufficient data/i).length).toBeGreaterThanOrEqual(1);
  });

  it("does not fabricate an effect when historical data is insufficient", async () => {
    const noEffect = forecastResult();
    noEffect.festivals = {
      analysis: [
        {
          festival_name: "Diwali",
          date: "2025-10-20",
          data_available: false,
          observation_count: 3,
          minimum_observations: 12,
          note: "Insufficient historical household data to estimate a festival-specific effect.",
        },
      ],
      upcoming: [
        {
          festival_name: "Diwali",
          date: "2025-10-20",
          window_start: "2025-10-17",
          window_end: "2025-10-23",
          national_holiday: false,
          festival_data_available: false,
          historical_effect_percent: null,
          historical_classification: null,
          festival_effect_percent: null,
          note: "Insufficient historical household data to estimate a festival-specific effect.",
        },
      ],
      applied: [],
      calendar_note: "calendar note",
      note: "Festival/calendar dates for the forecast period are KNOWN from the deterministic calendar.",
      weather_note: "weather note",
      weather_available: false,
    };
    api.generateForecast.mockResolvedValue(noEffect);

    await uploadFlow();
    await userEvent.click(screen.getByText("30 Days"));
    await userEvent.click(screen.getByRole("button", { name: /generate forecast/i }));

    expect(await screen.findByText(/Insufficient data/i)).toBeInTheDocument();
    // The same honesty message appears in the analysis row and the upcoming block.
    expect(screen.getAllByText(/Insufficient historical household data/i).length).toBeGreaterThanOrEqual(1);
    // No multiplier badge and no "adjusted" banner when nothing was applied.
    expect(screen.queryByText(/Forecast adjusted ×/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/was adjusted for/i)).not.toBeInTheDocument();
  });
});