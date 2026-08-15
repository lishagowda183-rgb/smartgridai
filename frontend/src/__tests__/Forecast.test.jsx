import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApiModule } from "./fixtures.js";

const api = vi.hoisted(() => ({}));
vi.mock("../services/api.js", () => api);

import Forecast from "../pages/Forecast.jsx"; // eslint-disable-line import/first

beforeEach(() => {
  for (const key of Object.keys(api)) delete api[key];
  Object.assign(api, createApiModule(vi));
});

describe("Forecast page", () => {
  it("renders the household forecast heading and hosts the upload workspace", async () => {
    render(<Forecast />);
    expect(await screen.findByText("Household Consumption Forecast")).toBeInTheDocument();
    expect(await screen.findByText(/upload your data/i)).toBeInTheDocument();
    expect(screen.getByText("1 Day")).toBeInTheDocument();
    expect(screen.getByText("30 Days")).toBeInTheDocument();
  });

  it("states that all values come from the uploaded data", async () => {
    render(<Forecast />);
    expect(
      await screen.findByText(/All values are produced by the backend forecast/i)
    ).toBeInTheDocument();
  });
});