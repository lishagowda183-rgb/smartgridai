import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApiModule } from "./fixtures.js";

const api = vi.hoisted(() => ({}));
vi.mock("../services/api.js", () => api);

import Dashboard from "../pages/Dashboard.jsx"; // eslint-disable-line import/first

const renderPage = (child) => render(<MemoryRouter>{child}</MemoryRouter>);

beforeEach(() => {
  for (const key of Object.keys(api)) delete api[key];
  Object.assign(api, createApiModule(vi));
});

describe("Dashboard", () => {
  it("renders household KPIs, forecast, peak, model and bill from the mocked dashboard", async () => {
    renderPage(<Dashboard />);

    expect(await screen.findByText("Current Consumption")).toBeInTheDocument();
    expect(await screen.findByText("343")).toBeInTheDocument(); // latest household reading kWh
    expect(screen.getByText("Today (Forecast)")).toBeInTheDocument();
    expect(screen.getByText("Tomorrow (Forecast)")).toBeInTheDocument();
    expect(screen.getByText("This Week (Forecast)")).toBeInTheDocument();
    expect(screen.getByText("Next Month (Forecast)")).toBeInTheDocument();
    expect(screen.getByText("Estimated Bill")).toBeInTheDocument();
    expect(await screen.findByText(/26,024.25/)).toBeInTheDocument(); // household bill ₹ from forecast
    expect(screen.getByText("Consumption Forecast")).toBeInTheDocument();
    expect(screen.getByText("Predicted Peak")).toBeInTheDocument();
    expect(screen.getByText("seasonaltrend")).toBeInTheDocument();
  });

  it("shows the honest weather-unavailable note instead of fabricating weather data", async () => {
    renderPage(<Dashboard />);
    expect(
      await screen.findByText(/No future weather data overlaps this forecast period/i)
    ).toBeInTheDocument();
  });

  it("renders the always-on weather section with status, source and current observation", async () => {
    renderPage(<Dashboard />);
    expect((await screen.findAllByText("Weather")).length).toBeGreaterThan(0);
    // Current observation metrics come from the dashboard weather_now block.
    expect(screen.getByText("Temperature")).toBeInTheDocument();
    expect(screen.getByText("Humidity")).toBeInTheDocument();
    expect(screen.getByText("Precipitation")).toBeInTheDocument();
    expect(screen.getByText("Wind")).toBeInTheDocument();
    expect(screen.getAllByText(/33.4/).length).toBeGreaterThan(0); // temperature °C from observation
    expect(screen.getByText("clear")).toBeInTheDocument(); // condition chip
    // Honest explicit source is always shown for the weather context (the
    // persisted snapshot path when the forecast itself has no weather_source).
    expect(screen.getByText(/Source: ml\/data\/raw\/weather_forecast.json/i)).toBeInTheDocument();
  });

  it("renders an onboarding call-to-action before any upload exists", async () => {
    api.getDashboard.mockRejectedValueOnce(
      new Error("No household consumption data uploaded yet. Upload a CSV/XLSX file to unlock your smart energy dashboard.")
    );
    renderPage(<Dashboard />);
    expect(await screen.findByText("Get started")).toBeInTheDocument();
    expect(screen.getByText("Upload consumption data")).toBeInTheDocument();
    expect(screen.queryByText("Current Consumption")).not.toBeInTheDocument();
  });

  it("renders an error state when the dashboard API fails", async () => {
    api.getDashboard.mockRejectedValueOnce(new Error("backend down"));
    renderPage(<Dashboard />);
    expect(await screen.findByText(/backend down/i)).toBeInTheDocument();
  });
});