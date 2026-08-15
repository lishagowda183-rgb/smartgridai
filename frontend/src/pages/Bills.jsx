import { useState } from "react";
import { Link } from "react-router-dom";
import SectionCard from "../components/cards/SectionCard.jsx";
import ErrorState from "../components/cards/ErrorState.jsx";
import HouseholdForm, { HouseholdBillResult } from "../components/bills/HouseholdForm.jsx";
import HouseholdWhatIf, { HouseholdWhatIfResult } from "../components/bills/HouseholdWhatIf.jsx";
import { useApi } from "../hooks/useApi.js";
import * as api from "../services/api.js";
import { formatKWh } from "../utils/format.js";

const TARIFF_KEY = "smartgridai.household.tariff";

function getInitialTariff() {
  try {
    return localStorage.getItem(TARIFF_KEY) || "household_slabs";
  } catch {
    return "household_slabs";
  }
}

function persistTariff(name) {
  try {
    localStorage.setItem(TARIFF_KEY, name);
  } catch {
    /* ignore */
  }
}

export default function Bills() {
  const dashboard = useApi(api.getDashboard);
  const tariffs = useApi(api.getHouseholdTariffs);

  const [household, setHousehold] = useState(null);
  const [whatIf, setWhatIf] = useState(null);
  const [calcBusy, setCalcBusy] = useState(false);
  const [whatIfBusy, setWhatIfBusy] = useState(false);
  const [calcError, setCalcError] = useState(null);
  const [whatIfError, setWhatIfError] = useState(null);
  const [selectedTariff, setSelectedTariff] = useState(getInitialTariff);

  const runCalculate = async (payload) => {
    setCalcBusy(true);
    setCalcError(null);
    if (
      payload.monthly_kwh === null ||
      payload.monthly_kwh === undefined ||
      Number.isNaN(Number(payload.monthly_kwh)) ||
      Number(payload.monthly_kwh) < 0
    ) {
      setCalcBusy(false);
      setCalcError("Monthly consumption must be a non-negative number of kWh.");
      setHousehold(null);
      return;
    }
    try {
      const res = await api.calculateHouseholdBill(payload);
      setHousehold(res);
    } catch (err) {
      setCalcError(`Unable to calculate your household bill right now. (${err.message || err})`);
      setHousehold(null);
    } finally {
      setCalcBusy(false);
    }
  };

  const runWhatIf = async (payload) => {
    setWhatIfBusy(true);
    setWhatIfError(null);
    if (
      payload.monthly_kwh === null ||
      payload.monthly_kwh === undefined ||
      Number.isNaN(Number(payload.monthly_kwh)) ||
      Number(payload.monthly_kwh) < 0
    ) {
      setWhatIfBusy(false);
      setWhatIfError("Base consumption must be a non-negative number of kWh.");
      setWhatIf(null);
      return;
    }
    try {
      const res = await api.calculateHouseholdWhatIf(payload);
      setWhatIf(res);
    } catch (err) {
      setWhatIfError(`Unable to calculate your household bill right now. (${err.message || err})`);
      setWhatIf(null);
    } finally {
      setWhatIfBusy(false);
    }
  };

  const data = dashboard.data;
  const isOnboarding = dashboard.error
    ? String(dashboard.error).toLowerCase().includes("uploaded")
    : data?.onboarding;

  const rawTariffs = (tariffs.data && tariffs.data.tariffs) || [];
  const tariffList = rawTariffs.map((t) => t?.name || t);
  if (!tariffList.length) tariffList.push("household_flat", "household_slabs", "household_tou");

  const bill = data?.household_bill;

  const apiError =
    dashboard.error && !isOnboarding
      ? String(dashboard.error)
      : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Household Electricity Bill</h1>
        <p className="text-sm text-slate-400">
          Household billing in INR/kWh — a data-driven estimate from your next-month forecast plus the
          interactive bill simulator.
        </p>
      </div>

      {isOnboarding ? (
        <SectionCard title="Start with your data" subtitle="Bills are computed from your uploaded consumption">
          <div className="flex flex-col items-start gap-4 py-4 text-center sm:flex-row sm:text-left">
            <div className="text-3xl" aria-hidden="true">
              🧾
            </div>
            <div className="flex-1">
              <p className="text-sm text-slate-200">
                Upload your household electricity data to calculate a data-based bill.
              </p>
              <Link
                to="/forecast"
                className="mt-3 inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-500"
              >
                Go to Forecast / Upload Data
              </Link>
            </div>
          </div>
        </SectionCard>
      ) : (
        <>
          {apiError && (
            <SectionCard title="Billing unavailable" subtitle="We could not reach the billing service">
              <ErrorState
                message="Unable to calculate your household bill right now."
                onRetry={() => {
                  dashboard.setError(null);
                  dashboard.refresh();
                }}
              />
              {apiError !== "Unable to calculate your household bill right now." && (
                <p className="mt-2 text-xs text-slate-500" data-testid="billing-error-detail">
                  {apiError}
                </p>
              )}
            </SectionCard>
          )}

          <SectionCard
            title="Next Month Bill Estimate"
            subtitle="From your 30-day household forecast · official backend tariff engine"
          >
            {bill ? (
              <div className="space-y-3">
                <p className="text-xs text-slate-400">
                  Forecasted consumption{" "}
                  <b className="text-slate-200">{formatKWh(bill.forecasted_monthly_kwh)}/month</b> over{" "}
                  {bill.forecasted_period || "the next month"} — varies with your tariff structure, so try
                  the simulator below to compare tariffs.
                </p>
                <HouseholdBillResult bill={bill} />
              </div>
            ) : (
              <p className="text-sm text-slate-400">No bill estimate available yet.</p>
            )}
          </SectionCard>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <SectionCard
              title="Household Bill Simulator"
              subtitle="Manual kWh · pick any household tariff"
            >
              <HouseholdForm
                tariffs={tariffList}
                onSubmit={runCalculate}
                busy={calcBusy}
                error={calcError}
                initialTariff={selectedTariff}
                onPersistPreference={(t) => {
                  setSelectedTariff(t);
                  persistTariff(t);
                }}
              />
              <HouseholdBillResult bill={household} />
            </SectionCard>

            <SectionCard
              title="What If My Consumption Changes?"
              subtitle="+10% / −10% / custom — all scenarios calculated by FastAPI"
            >
              <HouseholdWhatIf
                tariff={selectedTariff}
                onSubmit={runWhatIf}
                busy={whatIfBusy}
                error={whatIfError}
              />
              <HouseholdWhatIfResult result={whatIf} />
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}