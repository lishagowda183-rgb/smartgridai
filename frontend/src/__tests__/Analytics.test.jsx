import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApiModule } from "./fixtures.js";

const api = vi.hoisted(() => ({}));
vi.mock("../services/api.js", () => api);

import Analytics from "../pages/Analytics.jsx"; // eslint-disable-line import/first

const renderPage = (child) => render(<MemoryRouter>{child}</MemoryRouter>);

beforeEach(() => {
  for (const key of Object.keys(api)) delete api[key];
  Object.assign(api, createApiModule(vi));
});

describe("Analytics page", () => {
  it("renders hourly, day-of-week, monthly pattern and trend sections from household data", async () => {
    renderPage(<Analytics />);

    expect(await screen.findByText("Usage Analytics")).toBeInTheDocument();
    expect(await screen.findByText("Hourly Pattern")).toBeInTheDocument();
    expect(screen.getByText("Day-of-Week Pattern")).toBeInTheDocument();
    expect(screen.getByText("Monthly Pattern")).toBeInTheDocument();
    expect(screen.getByText("Monthly Trend")).toBeInTheDocument();
    expect(screen.getByText("Peak Hours")).toBeInTheDocument();
    expect(screen.getByText("Distribution")).toBeInTheDocument();
    expect(screen.getByText("Anomalies")).toBeInTheDocument();
    expect(screen.getByText("Weather vs Consumption")).toBeInTheDocument();
  });

  it("reports anomalies with observed vs typical values", async () => {
    renderPage(<Analytics />);
    expect(await screen.findByText("Unusual readings")).toBeInTheDocument();
    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(screen.getByText("2024-06-15 19:00:00")).toBeInTheDocument();
  });

  it("never fabricates weather correlations when weather does not overlap the history", async () => {
    renderPage(<Analytics />);
    expect(
      await screen.findByText(/does not overlap your uploaded 2024–2025 data/i)
    ).toBeInTheDocument();
    expect(screen.queryByText("Pearson correlations")).not.toBeInTheDocument();
  });

  it("renders an onboarding call-to-action before any upload exists", async () => {
    api.getHouseholdAnalytics.mockRejectedValueOnce(
      new Error("No household consumption data uploaded yet. Upload a CSV/XLSX file to unlock your smart energy dashboard.")
    );
    renderPage(<Analytics />);
    expect(await screen.findByText("Get started")).toBeInTheDocument();
    expect(screen.getByText("Upload consumption data")).toBeInTheDocument();
  });

  it("renders an error state when the analytics API fails", async () => {
    api.getHouseholdAnalytics.mockRejectedValueOnce(new Error("analytics unavailable"));
    renderPage(<Analytics />);
    expect(await screen.findByText(/analytics unavailable/i)).toBeInTheDocument();
  });
});