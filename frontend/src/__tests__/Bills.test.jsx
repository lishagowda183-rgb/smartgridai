import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApiModule, householdDashboard, householdWhatIf } from "./fixtures.js";

const api = vi.hoisted(() => ({}));
vi.mock("../services/api.js", () => api);

import Bills from "../pages/Bills.jsx"; // eslint-disable-line import/first

const renderPage = (child) => render(<MemoryRouter>{child}</MemoryRouter>);

beforeEach(() => {
  for (const key of Object.keys(api)) delete api[key];
  Object.assign(api, createApiModule(vi));
});

describe("Bills page", () => {
  it("renders a data-driven next-month bill estimate from the household forecast", async () => {
    renderPage(<Bills />);

    expect(await screen.findByText("Next Month Bill Estimate")).toBeInTheDocument();
    expect(await screen.findByText(/9,360 kWh\/month/)).toBeInTheDocument();
    expect(await screen.findByText(/26,024.25/)).toBeInTheDocument();
    expect(screen.getByText("Household Bill Simulator")).toBeInTheDocument();
    expect(screen.getByText(/What If My Consumption Changes/i)).toBeInTheDocument();
  });

  it("calculates the household bill via the API and shows the result", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    await screen.findByLabelText(/Monthly consumption kWh/i);
    await user.click(screen.getByRole("button", { name: /Calculate Bill/i }));

    expect(api.calculateHouseholdBill).toHaveBeenCalledWith({
      monthly_kwh: 350,
      tariff: "household_slabs",
      peak_share_pct: 40,
    });
    expect(await screen.findByText(/2,021.25/)).toBeInTheDocument();
    // Full itemization (energy, fixed, tax, total) comes from the backend response.
    expect(screen.getAllByText("Energy charge").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Fixed charge").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/₹1,700/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/₹200/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders an error when the household calculation fails", async () => {
    api.calculateHouseholdBill.mockRejectedValueOnce(new Error("bill calc failed"));
    const user = userEvent.setup();
    renderPage(<Bills />);

    await screen.findByLabelText(/Monthly consumption kWh/i);
    await user.click(screen.getByRole("button", { name: /Calculate Bill/i }));

    expect(await screen.findByText(/Unable to calculate your household bill right now/i)).toBeInTheDocument();
    expect(screen.getByText(/bill calc failed/i)).toBeInTheDocument();
  });

  it("renders an onboarding call-to-action before any upload exists", async () => {
    api.getDashboard.mockRejectedValueOnce(
      new Error("No household consumption data uploaded yet. Upload a CSV/XLSX file to unlock your smart energy dashboard.")
    );
    renderPage(<Bills />);
    expect(await screen.findByText("Start with your data")).toBeInTheDocument();
    expect(screen.getByText("Upload your household electricity data to calculate a data-based bill.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go to Forecast \/ Upload Data/i })).toBeInTheDocument();
    expect(screen.queryByText("Next Month Bill Estimate")).not.toBeInTheDocument();
  });

  it("renders a visible error state when the dashboard API fails for a non-onboarding reason", async () => {
    api.getDashboard.mockRejectedValueOnce(new Error("boom"));
    renderPage(<Bills />);
    expect(await screen.findByText("Billing unavailable")).toBeInTheDocument();
    expect(screen.getByText("Unable to calculate your household bill right now.")).toBeInTheDocument();
  });

  it("never shows a regional grid energy cost section", async () => {
    renderPage(<Bills />);
    await screen.findByText("Next Month Bill Estimate");
    expect(screen.queryByText(/Regional Grid Energy Cost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/INR\/MWh/i)).not.toBeInTheDocument();
  });

  it("runs the +10% scenario through the API and shows 385 kWh and the new bill", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    await screen.findByText("Next Month Bill Estimate");
    await user.click(screen.getByRole("button", { name: /Scenario plus 10 percent/i }));

    expect(api.calculateHouseholdWhatIf).toHaveBeenCalledWith({
      monthly_kwh: 350,
      tariff: "household_slabs",
      custom_kwh: null,
      plus_pct: 10,
      minus_pct: 10,
      peak_share_pct: 40,
      peak_shift_pct: 10,
    });
    expect(await screen.findByText(/385 kWh/)).toBeInTheDocument();
    expect(await screen.findByText(/₹2,221/)).toBeInTheDocument();
  });

  it("runs the -10% scenario through the API and shows 315 kWh and a new bill", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    await screen.findByText("Next Month Bill Estimate");
    await user.click(screen.getByRole("button", { name: /Scenario minus 10 percent/i }));

    expect(api.calculateHouseholdWhatIf).toHaveBeenCalled();
    expect(await screen.findByText(/315 kWh/)).toBeInTheDocument();
    expect(await screen.findByText(/₹1,821.5/)).toBeInTheDocument();
  });

  it("runs a custom 300 kWh scenario through the API and shows the new bill", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    await screen.findByText("Next Month Bill Estimate");
    await user.type(screen.getByLabelText(/Custom kWh/i), "300");
    await user.click(screen.getByRole("button", { name: /Calculate Custom/i }));

    expect(api.calculateHouseholdWhatIf).toHaveBeenCalledWith(
      expect.objectContaining({ monthly_kwh: 350, tariff: "household_slabs", custom_kwh: 300 })
    );
    expect(screen.getAllByText(/300 kWh · -13.86%/).length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText(/₹1,741/)).toBeInTheDocument();
    // Base vs custom consumption + savings/difference from the backend.
    expect(screen.getByText(/350 → 300 kWh/)).toBeInTheDocument();
  });

  it("uses the flat household tariff when selected", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    await screen.findByLabelText(/Monthly consumption kWh/i);
    await user.selectOptions(screen.getByLabelText(/Household tariff/i), "household_flat");
    await user.click(screen.getByRole("button", { name: /Calculate Bill/i }));

    expect(api.calculateHouseholdBill).toHaveBeenCalledWith({
      monthly_kwh: 350,
      tariff: "household_flat",
      peak_share_pct: 40,
    });
  });

  it("uses the TOU household tariff when selected", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    await screen.findByLabelText(/Monthly consumption kWh/i);
    await user.selectOptions(screen.getByLabelText(/Household tariff/i), "household_tou");
    await user.click(screen.getByRole("button", { name: /Calculate Bill/i }));

    expect(api.calculateHouseholdBill).toHaveBeenCalledWith({
      monthly_kwh: 350,
      tariff: "household_tou",
      peak_share_pct: 40,
    });
  });

  it("rejects negative consumption without calling the API", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    const input = await screen.findByLabelText(/Monthly consumption kWh/i);
    await user.clear(input);
    await user.type(input, "-20");
    await user.click(screen.getByRole("button", { name: /Calculate Bill/i }));

    expect(await screen.findByText(/Monthly consumption cannot be negative/i)).toBeInTheDocument();
    expect(api.calculateHouseholdBill).not.toHaveBeenCalled();
  });

  it("rejects missing consumption without calling the API", async () => {
    const user = userEvent.setup();
    renderPage(<Bills />);

    const input = await screen.findByLabelText(/Monthly consumption kWh/i);
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: /Calculate Bill/i }));

    expect(await screen.findByText(/Enter a monthly consumption in kWh/i)).toBeInTheDocument();
    expect(api.calculateHouseholdBill).not.toHaveBeenCalled();
  });

  it("page is never blank — heading + CTA render when no dataset exists", async () => {
    api.getDashboard.mockRejectedValueOnce(
      new Error("No household consumption data uploaded yet. Upload a CSV/XLSX file to unlock your smart energy dashboard.")
    );
    renderPage(<Bills />);
    expect(await screen.findByText("Household Electricity Bill")).toBeInTheDocument();
    expect(screen.getByText("Start with your data")).toBeInTheDocument();
  });
});