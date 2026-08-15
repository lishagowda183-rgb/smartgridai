# SmartGridAI — Household Electricity Consumption Forecasting & AI Energy Assistant

Portfolio project built incrementally. **Phase 1** establishes a clean, reproducible
electricity-consumption dataset pipeline: acquisition → validation → automated tests → EDA.
**Phase 2** adds feature engineering (timestamp / lag / rolling features), a strictly
chronological train/validation/test split, and three naive baseline forecasting methods
evaluated with MAE / RMSE / MAPE. **Phase 3** trains Random Forest and XGBoost forecasters
on the Phase 2 features, evaluates them with MAE / RMSE / MAPE / R², compares them against
the naive baselines on the same chronological splits, and persists the best model.
**Phase 4** integrates hourly weather data (temperature / humidity / precipitation / wind
speed / condition) from the Open-Meteo API — matched to consumption timestamps with **no
future-data leakage** — retrains a consumption-only vs a weather-aware XGBoost model, and
reports whether weather actually improves forecasting accuracy (MAE / RMSE / MAPE / R²)
plus weather-consumption visualizations.
**Phase 5** adds peak-hour analysis (historical peak hours, average-by-hour profile, maximum
demand, peak-to-average ratio, morning/evening peaks, and predicted future peak periods via
an iterated multi-step forecast) and anomaly detection (rolling z-score spikes/drops,
hourly-profile deviations, abnormal nighttime usage, and Isolation Forest), each with
severity scoring, reports, and visualizations.
**Phase 6** adds a fully configurable electricity tariff engine: per-unit, slab-based, fixed
charges, taxes/additional charges and optional peak/off-peak rates (defined in
`ml/tariffs/*.json`, never hard-coded), driving current/historical/forecasted/monthly-estimated
bills, bill comparison with percentage change, and what-if scenarios (± consumption, and
peak-to-off-peak shift savings) — all arithmetic computed deterministically in backend code.
**Phase 7** wraps the whole Phase 1–6 pipeline in a FastAPI backend (`backend/app/`): versioned
REST endpoints under `/api/v1` for consumption history, iterated ML forecasts, weather,
analytics, peak hours, anomalies and bills (Regional Grid Energy Cost + Household Bill
Simulator), with Pydantic validation, structured JSON errors, CORS, automatic Swagger/ReDoc
docs and a pytest suite — no React or agentic AI yet.
**Phase 8** adds a production-built React single-page dashboard (`frontend/`) that consumes the
Phase 7 API: live KPIs, an actual-vs-predicted demand forecast chart, Open-Meteo weather cards,
peak-hour analysis with predicted future peaks, anomaly alerts, the full analytics page
(including a new read-only `/analytics/weather-relationship` endpoint with real temperature
correlations) and both billing modes (Regional Grid Energy Cost vs Household Bill Simulator) —
built with Vite, React Router, Recharts and Tailwind CSS, verified with Vitest.
**Phase 9** adds an Agentic AI Energy Assistant: a provider-agnostic agent (`backend/app/agent/`)
that answers natural-language questions by selecting from a **whitelist of safe tools** that
call the Phase 1–8 services, ML models and billing engine — never arbitrary code or raw data
access. It ships with a deterministic **mock provider** for keyless runs and full test coverage,
plus an OpenAI-compatible provider (`httpx`, no new dependencies) for real LLMs. Answers are
**grounded in real tool outputs and clearly labelled** with scope (regional grid vs household)
and mode (mock vs provider) — nothing is ever fabricated.
**Phase 11** lets users bring their own data: upload a consumption CSV/XLSX, auto-detect scope
(household kWh vs regional MW) and frequency, validate it, then generate flexible forecasts
(1 day → 2 years) that run **only on the uploaded data** — never the project's regional series.
**Phase 12** repositions the product as a **household** app: the dashboard, analytics page,
bills page and the AI assistant are now driven **entirely by the user's uploaded household
data** (kWh / INR), with honest onboarding (a clear "upload your data" prompt before any
stage shows fabricated numbers), an upload-driven household dashboard
(`GET /forecast/dashboard`), upload-driven household analytics (`GET /analytics/household`),
and a **household-only agent allowlist**. Weather is **never fabricated**: forecasts are
weather-aware only when real future weather genuinely overlaps the period; analytics show
weather-consumption correlations only when historical weather overlaps the upload; otherwise
both surfaces state plainly that weather is unavailable for that data/period.
**Every non-agent number in the UI is computed by the backend pipeline (forecast / analytics /
bill engines) from the user's own uploaded data, never fabricated.**
**Phase 4.1** makes weather a core household forecasting feature: the API auto-refreshes the
Open-Meteo snapshot when it is missing or stale, every forecast + the dashboard always render
explicit weather status/source/feature metadata (`weather_status`, `weather_available`,
`weather_source`, `weather_features_used`), and the AI assistant answers weather-relationship
questions with grounded numbers. Honesty stays strict: future weather is never fabricated,
fetch failures never block forecasting, and long-term forecasts are labelled
historical/seasonal-only.

## Phase 1 Scope (implemented)

Dataset → Validation → Testing → EDA. No forecasting models, weather APIs, or applications yet.

- **Dataset:** [Hourly Energy Demand Generation and Weather](https://www.kaggle.com/datasets/nicholasjhana/energy-consumption-generation-prices-and-weather) (hourly 2015–2018).
- **Target column:** `total load actual` (MW, hourly average power over the **whole regional grid** centered on Madrid/ENTSO-E Spain — NOT household consumption).
- **Output:** cleaned hourly series + structured quality report with PASS/WARN/FAIL status.

## Phase 2 Scope (implemented)

Feature Engineering → Baseline Forecasting → Evaluation → Testing → EDA notebook.
No advanced ML models, weather integration, or applications yet.

- **Timestamp features:** `hour`, `day`, `day_of_week`, `day_of_month`, `week_of_year`,
  `month`, `quarter`, `year`, `is_weekend`.
- **Lag features:** `lag_1`, `lag_2`, `lag_3`, `lag_24`, `lag_48`, `lag_72`, `lag_168`.
- **Rolling features (backward-looking, no leakage):** `rolling_mean_3h`, `rolling_mean_6h`,
  `rolling_mean_12h`, `rolling_mean_24h`, `rolling_mean_7d`.
- **Split:** chronological 70/15/15 (no shuffle) → train 2015-01-08→2017-10-22,
  validation 2017-10-22→2018-05-27, test 2018-05-28→2018-12-31.
- **Baselines:** previous-hour, previous-day, 24h moving average; evaluated with
  MAE / RMSE / MAPE. Best baseline: **previous-hour** (test MAE ≈ 1047 MW, ~3.7% MAPE).

## Phase 3 Scope (implemented)

Machine learning forecasting → comparison → best-model persistence. No weather
integration, billing, FastAPI service, or applications yet.

- **Models:** Random Forest and XGBoost regressors trained on the Phase 2 feature
  matrix (timestamp + lag + rolling features). Hyperparameters selected on the
  validation split (validation MAE); XGBoost uses early stopping on validation.
- **Chronological validation:** no shuffling anywhere; features are backward-looking
  only, so no target leakage reaches validation/test.
- **Metrics:** MAE, RMSE, MAPE and R² on both validation and test splits.
- **Comparison:** ML models vs the Phase 2 baselines → `model_comparison.json`.
  Best model selected by lowest validation MAE.
- **Artifacts:** trained models (`ml/models/*.joblib`), per-model metrics
  (`model_metrics.json`), validation+test predictions (`predictions.csv`) and a
  forecast-vs-actual plot (`forecast_plot.png`).

## Phase 4 Scope (implemented)

Weather-aware forecasting → consumption-only vs weather-aware comparison. No billing,
FastAPI service, React dashboard, or agentic AI yet.

- **Weather source:** Open-Meteo API — historical hourly archive + current & N-day hourly
  forecast (`ml/data/raw/weather_hourly.parquet`, `weather_forecast.json`).
- **Weather variables:** temperature, relative humidity, precipitation, wind speed,
  weather code (WMO) → derived coarse `condition` category.
- **Timestamp matching:** weather merged onto the Phase 2/3 feature matrix by **exact
  timestamp equality** — no lagging, no forward/backward fill — so each row only ever sees
  the weather observed at its own hour (exogenous, no future-data leakage).
- **Models:** two XGBoost variants with identical Phase 3 hyperparameter tuning (early
  stopping on validation): `consumption_only` vs `weather_aware` (base + weather features).
- **Comparison:** MAE / RMSE / MAPE / R² on validation and test → `weather_comparison.json`
  with per-metric improvement deltas and a `weather_improves` verdict; `predictions_weather.csv`.
- **Visualizations:** temperature vs consumption, humidity vs consumption, weather-condition &
  rain vs consumption, and actual vs consumption-only vs weather-aware forecast (`plot_*.png`).

## Phase 5 Scope (implemented)

Peak-hour analysis + anomaly detection. No billing, FastAPI service, React dashboard, or
agentic AI yet.

- **Peak analysis** (`ml/scripts/peak_hours.py` → `peak_analysis.json` + `peak_hours_plot.png`):
  average consumption by hour of day, global maximum demand, peak-to-average ratio,
  per-day morning (06–11) and evening (17–22) peaks, top historical peak periods (contiguous
  runs ≥ 95th percentile), and **predicted future peak periods** detected on an iterated
  multi-step forecast (next 14 days past the data end) using the best consumption-only model.
- **Anomaly detection** (`ml/scripts/anomaly_detection.py` → `anomaly_report.json` +
  `anomalies_plot.png`): rolling z-score (spikes/drops vs a trailing 7-day window), hourly-profile
  z-score (unusually high/low vs the same hour historically), abnormal nighttime usage, and
  Isolation Forest on the Phase 2 lag+rolling features. Every anomaly is returned with
  timestamp, value, method, type, score and a severity bucket (moderate / high / critical).

## Phase 6 Scope (implemented)

Electricity bill + tariff engine. No billing UI, FastAPI service, React dashboard, or
agentic AI yet.

- **Tariffs** (`ml/tariffs/*.json`, `ml/scripts/tariffs.py`): per-unit rates, slab/tier
  pricing, fixed charges, taxes & additional charges, and optional peak/off-peak rates —
  fully data-driven and validated on load, with `simple_flat`, `domestic_slabs` and
  `time_of_use` samples.
- **Units & scope:** the consumption series is **hourly regional-grid load in MW**
  (`CONSUMPTION_UNIT=MW`), not household consumption. Summing the hourly MW values over a
  billing period yields energy in **MWh** (`ENERGY_UNIT=MWh`); `energy_kwh =
  energy_mwh × KWH_PER_MWH (1000)`. The pipeline records these units explicitly in the
  quality report, bill report and every computed bill, and `bill_report.json` carries a
  `sanity_notes` warning whenever a period's energy is far beyond household scale.
- **Bills** (`ml/scripts/bill_engine.py` → `bill_report.json` + `bill_history.csv` +
  `bill_history_plot.png`): current bill (latest full month), historical bills (every month),
  forecasted bill for an arbitrary user horizon (`2d` / `30d` / `1m` / `2m` / `1y` via an
  iterated forecast), monthly estimated bill, month-over-month & year-over-year comparison
  with percentage increase/decrease, and what-if scenarios: consumption ±10% and
  peak-to-off-peak shift savings.
- **Peak-shift savings:** reported as a **single-period estimate tied to one month** (e.g.
  "Estimated December 2018 peak-shift savings"), with an explicit assumption that
  `PEAK_SHIFT_PERCENT` of that month's peak-period energy is hypothetically shifted from the
  peak to the off-peak tariff. It is **not** presented as a recurring monthly amount.
  `peak_shift_savings_by_month.csv` gives the same estimate labeled separately for every
  calendar month.
- **Scale note:** because the underlying series is whole-region grid load, the reported
  bills are **regional-scale analytical estimates** (tens of billions of ₹/month), **not**
  household electricity bills. Values are intentionally not reduced or normalized to look
  household-sized — they are mathematically correct for the dataset's scope.
- **Currency:** configurable (`CURRENCY_SYMBOL`, default `INR`).

### Two-Mode Bill Architecture (Phase 6)

The bill layer is split into **two fully separate modes**, each with its own scope label and
units so results can never be confused. Every computed bill carries the same field set:

| Field | Regional mode | Household mode |
|---|---|---|
| `scope` | `regional_grid` | `household` |
| `scope_label` | `Regional Grid Energy Cost` | `Household Bill Simulator` |
| `consumption_unit` | `MW` | `kWh` |
| `energy_unit` | `MWh` (+ `energy_kwh`) | `kWh` |
| `tariff_unit` | `INR/MWh` | `INR/kWh` |
| `reporting_period` | calendar month (e.g. `2018-12`) | `1 month` |

**Regional Grid Energy Cost** (`ml/scripts/tariffs.py` + `bill_engine.py`), unchanged:
prices the hourly regional-load MW series → MWh → kWh against the per-MWh tariffs in
`ml/tariffs/*.json`. **It is never presented as a household electricity bill** — it is a
regional-scale analytical grid cost.

**Household Bill Simulator** (`ml/scripts/household_bills.py` + `ml/household_tariffs/*.json`):
a separate scalar calculator where the user provides a single **monthly consumption in
kWh/units** plus options — tariff type (flat / slabs / time-of-use), slab rates, fixed
charges, taxes and optional peak/off-peak rates. For example, `350 kWh` under the sample
`household_slabs` tariff (0–100 @ ₹3.5, 100–300 @ ₹5.0, >300 @ ₹7.0 per kWh, ₹200 fixed,
₹25 additional, 5% tax) produces a realistic total of **₹2,021.25** (energy ₹1,700 +
fixed/additional ₹225 + tax 5%). Time-of-use splits use an explicit `peak_share_pct` assumption
(default 40%) documented on the bill.

**Household what-if analysis** (`household_bills.household_what_if`): +10% consumption,
−10% consumption, arbitrary custom kWh, the estimated bill difference (amount + %), and
estimated peak → off-peak shift savings (TOU only).

Both modes share one schema contract (scope / units / tariff unit / reporting period), which
is written into every regional bill result and `bill_report.json` so a future FastAPI + React
dashboard can switch between **Regional Grid Analytics** and **Household Bill Simulator**
(roadmap, not implemented yet).

## Phase 7 Scope (implemented)

FastAPI backend exposing the Phase 1–6 pipeline through versioned REST endpoints. No React
dashboard or agentic AI yet.

- **Server:** `backend/app/` — FastAPI app with typed Pydantic schemas (`schemas.py`),
  a service layer (`services/`) that reuses the `ml/scripts/` modules as libraries, thin
  routes under `api/routes/`, startup caching of the series + forecast model, CORS, logging
  and structured JSON errors (no stack traces / secrets).
- **Run:** `python backend/run.py` (or `uvicorn backend.app.main:app`) → binds
  `API_HOST:API_PORT` from `.env` (defaults `127.0.0.1:8000`).
- **Docs:** Swagger UI at `http://127.0.0.1:8000/docs`, ReDoc at
  `http://127.0.0.1:8000/redoc`, OpenAPI JSON at `/api/v1/openapi.json`.
- **Real data, no fakes:** consumption comes from `consumption_hourly.parquet`, forecasts from
  the trained `consumption_only_xgboost` model via `peak_hours.iterated_forecast`, weather from
  the persisted Open-Meteo `weather_forecast.json` (read-only, **never** a live API call),
  peaks/anomalies/bills from the Phase 5/6 persisted reports.

### Endpoints (all under `/api/v1`)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health (`{"status":"ok", ...}`) |
| GET | `/consumption/current` | Latest reading, trailing 24 h window, series summary (MW) |
| GET | `/consumption/history` | Paged slice; optional `start`, `end`, `limit`, `offset` |
| GET | `/forecast/hourly` | Iterated forecast, `hours=24\|48\|72` (MW) |
| GET | `/forecast/daily` | Daily mean MW + total MWh (`days`) |
| GET | `/forecast/monthly` | Monthly mean MW + total MWh (`months`) |
| GET | `/weather/current` | Current observation + WMO `condition`, from persisted JSON |
| GET | `/weather/forecast` | Hourly forecast (`days`) from persisted JSON |
| GET | `/analytics/hourly` | Average consumption by hour of day |
| GET | `/analytics/weekly` | Average consumption by day of week |
| GET | `/analytics/monthly` | Average consumption by month of year |
| GET | `/analytics/peak-hours` | Peak-hour analysis (persisted `peak_analysis.json`) |
| GET | `/analytics/weather-relationship` | Pearson correlations (temp/humidity/precip/wind) + temperature-bucket demand from `weather_features_hourly.parquet` |
| GET | `/anomalies` | Detected anomalies; `severity`, `method`, `limit` filters |
| GET | `/bills/regional/tariffs` | Available regional tariff names |
| GET | `/bills/regional` | Regional bill report — cached by default; `?tariff=&horizon=&recompute=true` regenerates |
| GET | `/bills/household/tariffs` | Available household tariff names |
| POST | `/bills/household/calculate` | Household bill for `{monthly_kwh, tariff, peak_share_pct}` |
| POST | `/bills/household/what-if` | Household scenarios `{monthly_kwh, tariff, plus/minus %, custom_kwh, peak_shift_pct}` |
| POST | `/agent/chat` | AI assistant chat `{message, conversation_id}` (Phase 9) |
| POST | `/forecast/upload` | Upload CSV/XLSX consumption file → validated dataset (Phase 11) |
| GET | `/forecast/datasets` | Recent uploaded datasets + active household dataset (Phase 12) |
| GET | `/forecast/datasets/{dataset_id}` | Uploaded dataset metadata + preview |
| POST | `/forecast/generate` | Flexible forecast `{dataset_id, horizon_value, horizon_unit, scope?}` (Phase 11) |
| GET | `/forecast/export` / `/forecast/export/summary` | Forecast points / summary CSV exports |
| GET | `/forecast/dashboard` | Upload-driven household dashboard payload (Phase 12) |
| GET | `/analytics/household` | Upload-driven household analytics (patterns, peaks, anomalies, weather overlap) (Phase 12) |

### Regional vs Household billing in the API

The two-mode contract is preserved on every bill response. `/bills/regional` returns
`mode="regional_grid"` with `consumption_unit=MW`, `energy_unit=MWh`, `tariff_unit=INR/MWh`
and `reporting_period` = calendar month — regional-scale analytical grid cost (tens of
billions of ₹/month), **not** a household bill. `/bills/household/*` returns
`scope="household"`, `consumption_unit/energy_unit=kWh`, `tariff_unit=INR/kWh`,
`reporting_period="1 month"` for a single household. They are never mixed.

### Tests

`tests/test_api.py` (31 tests) exercises every endpoint with FastAPI's `TestClient`
(`httpx`): real artifacts + trained model, no network calls, deterministic household math
(the 350 kWh `household_slabs` example = **₹2,021.25**) and structured errors
(422 validation, 400 bad parameters, 404 unknown tariff). Full suite:

```bash
pytest                         # Phase 1–12: 252 tests
```

### Example requests

```bash
python backend/run.py &
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/api/v1/forecast/hourly?hours=24"
curl "http://127.0.0.1:8000/api/v1/anomalies?severity=high&limit=10"
curl "http://127.0.0.1:8000/api/v1/bills/regional"
curl -X POST http://127.0.0.1:8000/api/v1/bills/household/calculate \
  -H "Content-Type: application/json" \
  -d '{"monthly_kwh":350,"tariff":"household_slabs"}'
```

## Phase 8 Scope (implemented)

React + Vite single-page dashboard consuming the Phase 7 API. Plain JavaScript (`.jsx`, no
TypeScript), Tailwind CSS v4 (`@tailwindcss/vite`), React Router 6, Recharts, Axios,
Vite proxy-free (calls the FastAPI server directly at `VITE_API_BASE_URL`). No agentic AI.

- **App:** `frontend/` — `src/main.jsx` → `src/App.jsx` routes `/` (Dashboard),
  `/agent` (AI Assistant), `/forecast`, `/analytics`, `/bills`, `/settings`; unknown paths
  redirect to `/`.
- **Data layer:** `src/services/api.js` (single Axios instance, `VITE_API_BASE_URL`
  default `http://localhost:8000/api/v1`; `/health` is requested from the server root),
  `src/hooks/useApi.js` (`{data, loading, error, refresh}`) and `usePolling.js`.
- **Pages (Phase 12, household-first):** Dashboard (onboarding CTA → current/today/tomorrow/
  week/month KPIs, upload-driven forecast chart, peak, model/weather/trend components, bill
  estimate, recommendations), Forecast (**hosts the `UploadWorkspace`** — upload → validate →
  flexible forecast 1 day–2 years → bill/export; no regional forecast UI), Analytics
  (hourly/day-of-week/month patterns, monthly trend, distribution, peak hours, rolling
  z-score anomalies, honest weather-correlation panel), Bills (upload-driven next-month bill
  estimate + the household simulator and what-if tools), Settings (API `/health` connection
  state, household datasets view, cosmetic currency preference).
- **Onboarding everywhere:** Dashboard/Analytics/Bills render a clear “Upload consumption
  data” call-to-action (no sample/synthetic figures) until a household dataset exists; the
  weather-unavailable note is shown explicitly whenever the forecast/analytics lack real
  weather overlap.
- **Charts (`src/components/charts/`):** `UploadForecastChart` (history + predicted with
  bounds + peak markers), `TrendBarChart` (generic bars) and the Phase 8 charts
  (`DemandForecastChart`, `PeakHourChart`, `WeatherRelationshipChart`) remain available.
- **Weather relationship (Phase 8 endpoint):** `GET /analytics/weather-relationship`
  reads `weather_features_hourly.parquet` (34 860 real aligned hours) and returns Pearson
  correlations per weather variable plus mean demand per ~3 °C temperature bucket. Real
  values: temperature **+0.10**, humidity **−0.13**, precipitation **+0.01**, wind **+0.04**
  — labelled “very weak/weak”, never presented as causation.
- **Unit-safety is enforced in the UI:** the household app always uses `kWh` / `INR/kWh`.
  React never recomputes tariffs — every bill/what-if number comes from FastAPI (e.g. 350
  kWh under `household_slabs` = **₹2,021.25**; ±10 % scenarios and custom kWh via
  `/bills/household/what-if`). No regional MW figures appear anywhere in the household UI.
- **Settings currency** is a cosmetic `localStorage` display preference (default `INR`);
  the backend always prices in INR.

### Frontend setup & scripts

```bash
cd frontend
cp ../.env.example .env.example       # already present; see VITE_API_BASE_URL
npm install
npm test                              # Vitest + Testing Library (27 tests, jsdom)
npm run dev                           # http://127.0.0.1:5173 (dev server)
npm run build                         # production build -> frontend/dist
```

Environment variables (see `frontend/.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | FastAPI base for all endpoints except `/health` (server root) |
| `VITE_LIVE_REFRESH_MS` | `60000` | Dashboard live-poll interval for weather + current consumption |

To run headlessly with the live backend: start `python backend/run.py` first, then
`npm run dev` (or build + `npm run preview`). The dashboard is intentionally kept
dependency-light (no proxy, no websockets).

## Phase 9 Scope (implemented)

Agentic AI Energy Assistant (`backend/app/agent/`) behind `POST /api/v1/agent/chat`, surfaced in
the React dashboard as the **AI Assistant** page (`/agent`, nav entry “AI Assistant”). The agent
does **not** call arbitrary code: every question is answered by selecting from a fixed set of
**household-only whitelisted tools** that wrap the upload, forecast, analytics, weather, anomaly
and household-billing services (Phase 12 re-scope: the regional-grid tools were removed from the
allowlist so the assistant can never answer with regional MW figures).

- **Tools (whitelist, `tools.py`)** — Phase 12 set:
  `get_active_dataset`, `get_household_overview`, `get_user_forecast`,
  `get_user_analytics`, `get_user_anomalies`, `get_weather` (Madrid snapshot, read-only),
  `calculate_household_bill`, `calculate_household_what_if`. Each has a JSON-schema style
  parameter spec validated in-process; unknown tools/parameters are rejected
  (`AGENT_TOOL_VALIDATION`, 422). Tools that need an upload return an onboarding result
  (`available: false` + message) instead of fabricated numbers.
- **Providers (`provider.py`):**
  - `MockProvider` (default, `LLM_PROVIDER=mock`) — keyword-routed, deterministic: answers are
    composed **only from real tool payloads** (e.g. 350 kWh under `household_slabs` =
    **₹2,021.25**), never invented numbers. Responses carry `mode: "mock"`.
  - `OpenAICompatibleProvider` (`LLM_PROVIDER=openai_compatible` or `openai`) — `httpx`
    `POST {LLM_BASE_URL}/chat/completions` with tool-calling, temperature 0. Requires
    `LLM_API_KEY`; missing config returns `AGENT_NOT_CONFIGURED` (503). No new pip deps.
- **Workflow (`service.py`):** optional clarifying question → tool selection → execute →
  ground the answer in the real result → repeat up to `AGENT_MAX_TOOL_ROUNDS`. Conversation
  context is remembered in a light in-memory store (TTL `AGENT_CONVERSATION_TTL_S`): the
  household kWh/tariff from “My house uses 350 units” is reused for follow-ups like
  “what if I reduce it by 10%?”. If the user asks a question the tools cannot answer honestly
  (e.g. a bill question without any kWh figure), the agent asks for the missing input instead
  of inventing a value.
- **Grounding rules (prompt + code):** the answer never fabricates numbers or causation; the
  agent only talks about the user's own household data; weather is only cited when the backend
  reports real overlap; anomaly reports state expected value/deviation.
- **Response contract (`schemas.py`):** `AgentChatRequest {message, conversation_id}` →
  `AgentChatResponse {answer, tools_used, data_points[{label,value,unit}], scope, timestamp,
  conversation_id, model, mode}`; `data_points` are deterministically extracted from the tool
  payloads so the UI can render cards. `message` must be 1–2000 non-blank chars (422).
- **Errors (`errors.py`):** `AGENT_NOT_CONFIGURED` (503), `LLM_PROVIDER_ERROR` (502),
  `AGENT_TOOL_ERROR` (502), `AGENT_TOOL_VALIDATION` (422).
- **Config (`config.py`):** `LLM_PROVIDER` (default `mock`), `LLM_MODEL`, `LLM_API_KEY`,
  `LLM_BASE_URL` (default `https://api.openai.com/v1`), `LLM_TIMEOUT_S` (60),
  `AGENT_MAX_TOOL_ROUNDS` (5), `AGENT_CONVERSATION_TTL_S` (3600),
  `AGENT_MAX_MESSAGE_CHARS` (2000). See `.env.example`.
- **Frontend (`pages/Agent.jsx`):** chat bubbles, household suggestion chips (overview, bill,
  what-if, forecast, patterns, anomalies), tool-used chips, data-point cards, a `Household`
  scope badge, a “mock mode” label when `mode === "mock"`, clear-conversation button, and
  reuse of `conversation_id` across turns.
- **Security & observability:** the agent can only call the whitelisted household tools; logs
  contain `request_id`, tool names and durations only — never API keys, chain-of-thought or
  full conversations. `.env` (with any real key) is gitignored.
- **Testing:** `tests/test_agent.py` (34 tests: whitelist, per-tool real data, household scope,
  determinism, conversation context, endpoint + 422s, config/provider error paths) +
  frontend `Agent.test.jsx` (4 tests). Full suite: **backend 252 passed, frontend 27 passed**,
  production build OK. Real-LLM behaviour is **not verified in this repo** (no API key) — the
  OpenAI-compatible provider is covered by the same tests via a stubbed transport;
  `LLM_PROVIDER=mock` is the safe default.

### Agent API

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "My house uses 350 units. How much is my bill?"}'
```

Example follow-up (reuse the returned `conversation_id`): “What if I reduce it by 10%?” →
`calculate_household_what_if` → new bill ₹1,764.00 (−12.73 %). Interactive docs at
`/docs`.

## Phase 11 Scope (implemented)

Bring-your-own-data workflows: upload a consumption file (CSV/XLSX), inspect the
auto-detection + validation report, then generate a forecast that runs **only on
your uploaded data** — never the project's regional-grid series.

### Upload & validation

* `POST /api/v1/forecast/upload` (multipart) — accepts `.csv` / `.xlsx`, size
  capped at `MAX_UPLOAD_SIZE_MB` (25 MB default). Timestamp and consumption
  columns are auto-detected (alias names → parseable/numeric fallback), the
  series is cleaned (parse, sort, dedupe, drop NaN/negative) and a 13-check
  validation report (center = the Phase 1 quality report) returns
  `valid` / `warn` / `invalid` plus removal statistics.
* Frequency (`hourly`, `30min`, `15min`, `daily`, `weekly`, `monthly`) and scope
  (`household` kWh vs `regional_grid` MW/MWh) are inferred with an explicit
  heuristic; datasets that cannot be confidently classified set
  `scope.need_selection = true` and ask the user to pick.
* `GET /api/v1/forecast/datasets/{dataset_id}` — metadata + first-rows preview.
* Datasets live behind generated `dataset_id`s under `UPLOAD_DIR`
  (`ml/data/uploads/`, gitignored) and are cleared on startup / after
  `UPLOAD_TTL_S`.

### Flexible forecast

`POST /api/v1/forecast/generate` — payload `{dataset_id, horizon_value,
horizon_unit (days|months|years), scope?}`.

* Horizon bounds: 1–730 days. Strategy is chosen by horizon:
  * **1–7 days** → `short_term` — an XGBoost model retrained on the uploaded
    history (existing feature recipe + iterated forecast), scale-correct for
    that dataset. On non-sub-hourly data the deterministic seasonal model is used.
  * **8–180 days** → `medium_term` — seasonal/trend model (linear trend × month
    / day-of-week / hour factors fitted on the upload).
  * **>180 days** → `long_term` — seasonal/trend model aggregated to months,
    with weather explicitly labelled as *historical pattern, not future
    weather*. Future weather is never fabricated.
* Display granularity keeps point counts sane: native frequency for short-term,
  daily ≤ 30 days, weekly ≤ 180 days, monthly beyond.
* Returns: summary stats, LOW/MEDIUM/HIGH classification (from the 33rd/66th
  percentiles of the uploaded history at the same granularity as the display),
  peak analysis, history + forecast points, weather availability status,
  deterministic recommendations, and — for `household` scope on kWh data — an
  estimated monthly bill computed by the existing household bill engine
  (`ml/scripts/household_bills.py`). Regional scope **never** receives a
  household bill. A `scope` override lets users reclassify a dataset.

### Exports

`GET /api/v1/forecast/export` (points CSV) and
`GET /api/v1/forecast/export/summary` (compact summary CSV), keyed by
`dataset_id`, `horizon_value`, `horizon_unit`.

### Frontend

`frontend/src/pages/Forecast.jsx` is now the **household forecast page**: it hosts the
`UploadWorkspace` component as the primary flow — upload → validation report + preview →
horizon presets (1d/7d/30d/3mo/6mo/1y/2y) or custom → forecast dashboard (summary cards,
transition chart, classification bars, peak analysis, weather note, bill, recommendations,
CSV export). The old regional forecast section was removed in Phase 12 (the regional REST
endpoints remain in the backend but are not used by the UI).

```bash
curl -X POST http://127.0.0.1:8000/api/v1/forecast/upload \
  -F "file=@my_energy.csv"
# -> { "dataset_id": "ds_...", "validation_status": "valid", "scope": {...}, ... }

curl -X POST http://127.0.0.1:8000/api/v1/forecast/generate \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"ds_...","horizon_value":30,"horizon_unit":"days"}'
```

Phase 11 settings live in `backend/app/config.py` (and `.env.example`):
`MAX_UPLOAD_SIZE_MB`, `ALLOWED_UPLOAD_EXTENSIONS`, `UPLOAD_TTL_S`,
`MAX_DATASETS`, `MIN/MAX_FORECAST_DAYS`, `SHORT_TERM_MAX_DAYS`,
`MEDIUM_TERM_MAX_DAYS`, `LOW/HIGH_PERCENTILE`.

## Phase 12 Scope (implemented)

Household-only product: every screen (Dashboard, Analytics, Bills, Forecast, AI Assistant) is
driven **entirely by the user's uploaded household data** (kWh / INR), with honest onboarding
and no fabricated or sample figures anywhere.

- **Forecast response enrichment (`services/user_forecast.py`):** every `_run` response now
  includes `forecast_type_label`, `display_label`, `model`, `model_features`, `trend`,
  `status` and `scope_detected_by`, plus point-level `peak_flag`, `weather_available`,
  `temperature` and `humidity` (attached only for sub-daily short-term forecasts using real
  future weather). `export_csv` gained `peak_flag`, `weather_available`, `temperature`,
  `humidity` columns.
- **Household dashboard (`services/household_dashboard.py` + `GET /forecast/dashboard`):**
  `datasets(limit)`/`dashboard(dataset_id|None)` → current reading, today/tomorrow totals,
  this-week and next-month forecasts (reusing the weekly `7-day` + monthly `30-day` runs so
  the dashboard always agrees with the full forecast), predicted peak, model/status/trend,
  weather status, recommendations, an estimated household bill from the 30-day forecast, chart
  points + historical tail, and an onboarding payload. With no upload it returns `NotFoundError`
  → the UI shows a "Upload consumption data" call to action.
- **Household analytics (`services/household_analytics.py` + `GET /analytics/household`):**
  hour-of-day / day-of-week / month-of-year profiles, a per-month consumption trend,
  distribution histogram, top peak hours + peak-to-average ratio, rolling z-score anomalies
  (window, threshold, z-score, severity, observed vs historical average), and a
  **weather-correlation panel that is only populated when real weather overlaps the uploaded
  timestamps** — otherwise `available: false` with an explanatory note. Weather is never
  fabricated, and analytics never reference the regional series.
- **Forecast weather integrity:** short-term (≤ 7 days) weather-aware XGBoost is only used when
  real future weather genuinely overlaps the horizon; otherwise the deterministic seasonal
  model runs with `weather.status` labelling the limitation (the dashboard/analytics render the
  matching "weather data unavailable for this period" note).
- **Agent re-scope:** the allowlist is now household-only (8 tools, see Phase 9) and the mock
  router never answers with regional figures — bill questions without a kWh figure prompt for
  the missing input instead of guessing.
- **UI copy is household everywhere:** sidebar (“AI Assistant”, “Household · kWh · INR”), app
  header, page titles/descriptions, Bills (upload-driven estimate + simulator/what-if, regional
  tab removed), Forecast (upload workspace as the primary flow), Settings (API connection +
  household datasets view). Regional REST endpoints (`/consumption/*`, `/forecast/hourly`,
  `/analytics/weather-relationship`, `/bills/regional`, …) remain in the backend for the
  Phase 1–8 pipeline/tests but are intentionally unused by the household UI and agent.
- **Tests:** `tests/test_household_dashboard.py` (9 tests) covers the dashboard service +
  routes (dataset list, active dataset, onboarding 404, today/tomorrow/week/month/bill/peak
  fields, weather-not-full honesty); full suite **backend 252 passed / frontend 27 passed**,
  production build OK.

## Phase 13 Scope (implemented) — Festival / Holiday-Aware Forecasting

Indian festival/holiday awareness is now a first-class part of the SmartGridAI forecast
pipeline: a deterministic Indian festival calendar, a household-observed festival analysis
(learned strictly from the user's uploaded data), future-festival detection inside every
forecast horizon, and an evidence-gated multiplicative adjustment inside future festival
windows. Calendar facts are **never** derived from any LLM; household effects are **never**
assumed when history is missing.

Final report (14 items):

1. **Deterministic Indian festival / holiday calendar** — `backend/app/services/festival_calendar.py`
   ships a curated pan-Indian table (Diwali, Holi, Dussehra, Ganesh Chaturthi, Ugadi,
   Eid al-Fitr, Eid al-Adha, Onam, Pongal / Makar Sankranti, Raksha Bandhan, Janmashtami,
   Navratri — with year-by-year lunisolar dates) plus fixed national holidays (Republic Day,
   Independence Day, Gandhi Jayanti, Christmas). The table is configuration, not a model, and
   is fully overridable via `FESTIVAL_CALENDAR_JSON` for state/region-specific accuracy.
2. **Festival / calendar timestamp features** — `festival_features(...)` produces
   `is_festival`, `festival_name`, `is_holiday`, `is_weekend`, `days_before_festival`,
   `days_after_festival`, `festival_day`, `festival_window`. These are added to the short-term
   ML feature matrix and emitted as calendar-feature generators for the iterated forecast
   engine, so the XGBoost model can learn the household's observed festival pattern.
3. **Historical household observation layer** — `analyze_historical_festivals(...)` computes
   each festival's window average vs a comparable non-festival baseline (same weekday, same
   season ±30 days, hour-of-day matched for sub-daily data, festival windows excluded) and
   classifies the observed effect HIGHER / LOWER / SIMILAR against the household's **own**
   baseline.
4. **Insufficient-data honesty** — `FESTIVAL_MIN_OBSERVATIONS` (default 12) gates the effect.
   Below it the response says “Insufficient historical household data to estimate a
   festival-specific effect” and the forecast is left untouched — a lack of history never
   breaks forecasting and never invents an effect.
5. **Effects are never forced positive** — the multiplier is `festival_avg / normal_avg`
   exactly; a LOWER observation drives the forecast *down*, an observed negative effect is
   reported with its real sign, and all wording is “historically observed in your data”, never
   causality.
6. **Future-festival detection inside the horizon** — `upcoming_festivals(...)` returns every
   festival whose window falls inside the forecast period, with festival name, date, window and
   national-holiday flag, joined to the learned effect only when data is sufficient.
7. **Evidence-gated forecast adjustment** — `adjust_forecast(...)` multiplies forecast values
   inside future festival windows **only** when the household has sufficient data AND the
   observed effect is outside the SIMILAR band; the multiplier is clipped to 0.5–1.5 and every
   applied window is reported with its `applied_multiplier`.
8. **Response `festivals` block (all forecasts)** — every forecast response carries
   `{ analysis, upcoming, applied, calendar_note, note, weather_note, weather_available }`.
   Calendar facts and the household analysis are always computed, for household and
   regional-grid scope alike.
9. **Point-level festival flags** — every forecast point includes `is_festival`,
   `festival_name` and `is_holiday`, so the UI/charts can mark festival periods.
10. **Festival recommendations** — `festival_higher`, `festival_lower`, `festival_similar` and
    `festival_insufficient_data`, each grounded in the exact observed percentage with a
    traceable `basis`.
11. **Dashboard / AI context** — the household dashboard exposes a compact festivals summary so
    the AI Assistant can reference calendar facts; `weather_note` wording stays correct for
    both weather-enabled and long-term (no weather) horizons.
12. **UI: SMART Festival section** — a new `FestivalSection` in the upload workspace renders
    upcoming festivals with windows, national-holiday chips, the household-observed effect per
    festival, applied-multiplier badges, and transparency notes (calendar approximation +
    insufficient data).
13. **Configuration & documentation** — `.env.example` documents `FESTIVAL_WINDOW_BEFORE`,
    `FESTIVAL_WINDOW_AFTER`, `FESTIVAL_MIN_OBSERVATIONS`, `FESTIVAL_EFFECT_THRESHOLD_PCT` and
    `FESTIVAL_CALENDAR_JSON`; this README section + the 14-item report.
14. **Tests** — `tests/test_festival_calendar.py` (25 backend tests: calendar determinism,
     holiday dates, feature columns, HIGHER/LOWER/SIMILAR analysis, insufficient-data honesty,
     future-festival detection, adjustment/clip behaviour, response block, API integration,
     calendar override) plus 2 new frontend tests for the SMART Festival section. Full suite:
     **backend 291 passed / frontend 40 passed**, and the pre-existing Phase 1–12 behaviour is
     unchanged (non-festival forecasting paths are untouched when no festival data exists).

## Phase 14 Scope (implemented) — Natural, Context-Aware AI Energy Assistant

Phase 14 (the conversational *“Phase 4” assistant upgrade*) turns the Phase 9 AI Energy
Assistant from a keyword router into a natural, context-aware household assistant: it greets
and thanks without wasting tool calls, routes each question to the **fewest** relevant
household tools, remembers context across turns (kWh, tariff, last forecast horizon, last
festival), and keeps every number grounded in the deterministic backend engines. Scope stays
strictly household (kWh + INR) — no regional-grid/MW/MWh/Madrid/ENTSO-E tools — and
`LLM_PROVIDER=mock` remains the safe keyless default.

Final report (15 items):

1. **Deterministic intent layer** — new `backend/app/agent/intents.py`: pure-greeting detection
   (`hi` / `hello` / `thanks` / `bye` / `how are you`…), spec-style greetings with **“Hi! 👋”**,
   thanks/farewell acknowledgements, an off-topic reply, and an energy-keyword gate so
   *“hi, what is my bill?”* still routes to billing while a bare *“hi”* never calls tools.
2. **Greeting short-circuit in `AgentService.chat`** — pure greetings are answered
   deterministically **before any LLM/tool round**, so even a live provider never calls tools
   for a greeting. The mock provider additionally answers clearly off-topic chatter with the
   off-topic reply and **zero** tool calls; live prompts carry the same rule.
3. **Tool allowlist grows 8 → 11** with three thin, read-only adapters over the existing
   engines (`tools.py`): `get_current_consumption` (latest reading + today total straight from
   the uploaded series, no forecast), `get_household_classification` (LOW/MEDIUM/HIGH + reason
   from `household_dashboard`), and `get_festival_outlook` (the Phase 13 festival calendar +
   the household's **own** observed effect). Each has a parameter schema, onboarding-safe
   empty state, and deterministic `extract_points`.
4. **Custom-kWh what-if** — `calculate_household_what_if` now accepts a
   `target_consumption_kwh` (“what if I use 250 kWh instead of 350?”) in addition to the
   existing +/-% path, returning the ₹ delta via the **unchanged** `household_what_if(...)`
   engine; validation requires either a change % or a target.
5. **Rewritten `MockProvider` intent router** — routes on the **current turn** only (older
   turns no longer leak “next month”/“what if” keywords into intent detection) with explicit
   branches before the overview fallback: festival (incl. “Diwali/Holi/Pongal/Onam”),
   classification (“is my usage high / too high / compare to normal”), current consumption,
   next-week/next-month/thin forecast, weather words (“hot/cold/rain/temperature”), and
   “why do I use more on Sundays?” → usage patterns (correlation, never causation).
6. **Grounded answer formatters** for every registered tool (including the 3 new ones). The
   overview now narrates the estimated household bill and the real weather note when weather
   is unavailable; the weather formatter never interpolates `None` values (the old
   “None°C” bug is gone).
7. **Conversation memory slots** (`schemas.py`) — in-memory, TTL-capped (still **no
   database**) slots extended to `last_horizon_value/unit` and `last_festival` alongside the
   existing kWh + tariff; updated only from **real** tool results (forecast → horizon,
   festival outlook → next festival).
8. **Memory injection** (`service.py` + `prompts.py`) — the slots are serialized into the
   system prompt as a `Remembered household context` block and re-parsed by the provider, so
   follow-ups like *“what about for next week instead?”*, *“what if I use 250 instead?”* and
   festival “the next one” work across turns.
9. **`prompts.py` conversational rewrite** — natural tone (“Hi! 👋”, thank the user back,
   warm goodbyes), an explicit no-tool rule for pure greetings/thanks/off-topic, the
   fewest-tools routing guidance, and a reinforced “festivals are never assumed to mean high
   usage” grounding rule.
10. **Frontend** — `pages/Agent.jsx` suggestion buttons updated to the six required
    conversational prompts: bill, Diwali festival, next-month forecast, “is my consumption too
    high”, current consumption, and the custom-kWh what-if (the demo now exercises the new
    intents instead of the old overview/reduce-10% set).
11. **Backend tests** — 24 new cases in `tests/test_agent.py` (58 total): new-tool real-data
    + onboarding + validation, custom-kWh / change-or-target validation, festival horizon
    bounds, intent routing (greeting / thanks / bye / off-topic with **no** tools;
    festival; classification; current; next-month; custom what-if with memory), memory
    persistence (horizon value/unit, kWh), system-prompt context injection, festival
    follow-up recall, weather-word routing, and `extract_points` for the new tools. Full
    backend suite: **315 passed**.
12. **Frontend tests** — 8 new cases in `Agent.test.jsx` (12 total): the new suggestion
    buttons, verbatim suggestion send, conversation-id reuse across a thread, greeting reply
    with no tools/data cards, and the festival / current-consumption / classification /
    custom-kWh tool chips + data points + mock badge. Full frontend suite: **48 passed**,
    `npm run build` OK.
13. **Manual end-to-end verification** (mock provider, 3-year household CSV): *“hi”* → 👋
    greeting, no tools → tomorrow overview → next-month forecast → *“25 kWh bill”* (₹328.12)
    → *“Is 350 kWh too high?”* (MEDIUM + reason) → *“What if I use 250 kWh instead?”* (₹2,021.25
    → ₹1,391.25) → *“Will Diwali affect my usage?”* (festival outlook) → *“current
    consumption”* (latest reading) → *“why more on Sundays?”* (patterns) → *“thanks”* and an
    off-topic pasta question (both **zero** tool calls).
14. **Explicitly not changed** — the working household billing and forecast engines are
    untouched (the new tools call them as-is); no database was added; the assistant remains
    household-only (kWh + INR); `LLM_PROVIDER=mock` stays the default; greeting/off-topic
    decisions are deterministic and tool-free for both providers.
15. **Documentation** — this Phase 14 section and the 15-item report (README), following the
    repo's Phase-numbering convention (the work is the conversational “Phase 4” of the spec).

## Phase 4.1 Scope (implemented) — Weather as a Core Household Forecasting Feature

Phase 4.1 promotes the persisted Open-Meteo snapshot (Phase 4 artifact) into a first-class
household forecasting feature: the API now **auto-refreshes** weather when the snapshot is
missing or stale, every forecast and the dashboard **always** render explicit weather
status/source/feature metadata (never silently dropping weather), and the AI assistant can
answer *“how does weather affect my usage?”* and *“will the weather increase my usage?” *with
grounded numbers from the deterministic engines. Hard honesty constraints are preserved:
future weather is **never fabricated**, a fetch failure **never blocks forecasting**, the
existing model/ML paths are untouched, and all tests stay deterministic (no live API).

Final report (15 items):

1. **Refresh TTL** — `WEATHER_REFRESH_HOURS=6` (new in `ml/scripts/config.py`, next to
   `WEATHER_FORECAST_DAYS`; documented in `.env.example`). A snapshot newer than the TTL is
   kept; missing/stale snapshots are refetched automatically.
2. **`weather.ensure_snapshot()`** — best-effort auto-refresh in `backend/app/services/weather.py`.
   Uses the existing `download_weather.fetch_json(...)` + `_params(daily=True)`, writes the
   artifact with a fresh `_generated_at`, and invalidates the report cache. Returns
   `fresh` / `refreshed` / `cache_fallback` / `temporarily_unavailable` and **never raises**.
3. **Failure modes** — a failed fetch with a cached snapshot keeps the old data
   (`cache_fallback`) and a failed fetch with no snapshot reports
   `temporarily_unavailable`; forecasting continues in both cases (consumption-only path).
4. **Auto-fetch wired into forecasting** — `user_forecast.generate()` and
   `household_dashboard.dashboard()` both call `weather.ensure_snapshot()` before running, so
   every forecast and the dashboard use the best available weather without extra user steps.
5. **Additive weather metadata block** — every forecast response `weather` now carries, in
   addition to the existing `status/label/note`: `weather_status` (`full` / `partial` /
   `none` / `not_available`), `weather_available`, `weather_source` (`"Open-Meteo"` for short
   horizons; `"Open-Meteo (historical/seasonal patterns)"` for long term; else `None`),
   `weather_features_used` and `weather_note`. Existing keys are never dropped.
6. **Long-term honesty** — long-term forecasts keep `status="not_available"` with
   `weather_available=True` only via the explicitly labelled historical/seasonal-pattern
   source and the existing note (“…uses historical weather relationships and seasonal
   patterns”), so weather is never fabricated at horizons where exact future weather is
   unknowable.
7. **Short-term ML feature reporting** — when the model really joins weather, the
   `weather_features_used` list names the exact columns (`temperature`, `humidity`,
   `precipitation`, `wind_speed`, `condition`); otherwise it is empty and the UI says so.
   `_weather_block(...)` and `_weather_usage(...)` decide this strictly on real overlap.
8. **Dashboard weather section** — the dashboard response adds `weather_now`
   (`cache.current_summary()` → observation with temperature/humidity/precipitation/wind,
   location metadata, source path and `_generated_at`), alongside the extended `weather`
   block. The dashboard renders it always (see item 12).
9. **Grounding in module alias** — `household_dashboard.dashboard()` aliases the weather
   module as `weather_service` so the local weekly-result variable named `weather` cannot
   trigger an `UnboundLocalError`; the module-level import is unchanged otherwise.
10. **AI assistant weather routing** — `MockProvider` gained explicit branches:
    *“how does weather affect / impact / correlate with my usage”* → `get_user_analytics`
    (with weather correlations over the overlapping hours only); *“will the weather
    increase / reduce my usage”* → `get_weather` + `get_user_forecast`; a plain
    weather question still routes to `get_weather`. Grounded formatters added: the forecast
    answer appends the weather-aware status/features when `full`/`partial` or the long-term
    note otherwise; analytics appends weather correlations; classification appends a
    weather sentence when weather is available. `get_household_classification` result now
    passes the `weather` payload through.
11. **Frontend: shared `WeatherSection`** — new
    `frontend/src/components/weather/WeatherSection.jsx` renders three honest states
    (A: real weather → temp/humidity/precip/wind + status/source/features; B: long-term →
    historical/seasonal label; C: fetch failure → “temporarily unavailable” retry note) and
    is wired into **both** the household Dashboard (`now={data.weather_now}`) and the
    upload/forecast workspace (`weather={result.weather}`). The old inline weather notes
    were removed so the shared section is the single source of the note text (prevents
    duplicate DOM matches in the agent/dashboard UI).
12. **Frontend honesty rails** — `weatherBadge` in `frontend/src/utils/format.js` handles
    the `not_available` (“Historical weather patterns”) and `temporarily_unavailable`
    states, and `pages/Agent.jsx` added the suggestion *“How does weather affect my
    electricity usage?”*.
13. **Backend tests — Phase 4.1** — new `tests/test_weather_core.py` (16 cases, all
    deterministic, snapshot treated as fresh, live fetch monkeypatched): weather-block
    metadata for `full`/`partial`/`none`/`not_available`; response carries
    `weather_*` keys; long-term never fabricates weather; overlap → `full`; `ensure_snapshot`
    fresh/stale/missing/failure (`cache_fallback` + `temporarily_unavailable`); dashboard
    always has `weather` + `weather_now` with all four metrics; agent routing for
    “how does weather affect…” → analytics and “…weather increase…” → `get_weather` +
    `get_user_forecast`; classification formatter mentions weather when available; and a
    test proving **no network** is touched when the snapshot is fresh. Full backend suite:
    **331 passed**.
14. **Frontend tests — Phase 4.1** — updated `fixtures.js`
    (`householdDashboard()` gains `weather_now` + extended `weather`; `forecastResult()`
    gains the `weather_*` fields) plus new cases: the dashboard renders the weather section
    with status/source/current metrics and the forecast page renders the explicit
    `Open-Meteo` source + exact `weather_features_used` when weather is available. Full
    frontend suite: **50 passed**, `npm run build` OK.
15. **Documentation** — this Phase 4.1 section and the 15-item report (README), following
    the repo's Phase-numbering convention (weather as a core household feature, tracked as
    a dedicated increment of the spec's “Phase 4 weather” work).

## Repository Layout

```text
electricity-forecasting/
├── ml/
│   ├── data/
│   │   ├── raw/               # downloaded Kaggle dataset + Open-Meteo weather (gitignored)
│   │   ├── processed/         # quality_report.json, consumption_hourly.parquet,
│   │   │                      # features_hourly.parquet, data_splits.json,
│   │   │                      # baseline_report.json, model_metrics.json,
│   │   │                      # model_comparison.json, predictions.csv,
│   │   │                      # forecast_plot.png, weather_features_hourly.parquet,
│   │   │                      # weather_comparison.json, predictions_weather.csv,
│   │   │                      # plot_*.png (all gitignored)
│   │   └── uploads/           # Phase 11: uploaded datasets (ds_*.parquet/.json, gitignored)
│   ├── models/                # trained model artifacts (*.joblib, gitignored)
│   └── scripts/
│       ├── config.py          # env-driven configuration (shared)
│       ├── download_dataset.py
│       ├── validate_dataset.py
│       ├── feature_engineering.py  # Phase 2: features + chronological split
│       ├── baselines.py            # Phase 2: baselines + MAE/RMSE/MAPE
│       ├── forecasting.py          # Phase 3: metrics + model factories
│       ├── train_models.py         # Phase 3: train/persist RF + XGBoost
│       ├── evaluate_models.py      # Phase 3: comparison report + forecast plot
│       ├── download_weather.py     # Phase 4: fetch Open-Meteo weather (raw)
│       ├── weather_features.py     # Phase 4: exact-timestamp weather feature merge
│       ├── train_weather_models.py # Phase 4: consumption-only vs weather-aware XGBoost
│       ├── plot_weather.py         # Phase 4: weather-consumption visualizations
│       ├── peak_hours.py           # Phase 5: peak-hour analysis + iterated forecast
│       ├── anomaly_detection.py    # Phase 5: rolling/profile/night/IF anomalies
│       ├── tariffs.py              # Phase 6: tariff model + deterministic bill math
│       ├── household_bills.py       # Phase 6: household bill simulator (per-kWh)
│       ├── bill_engine.py          # Phase 6: regional grid bills, comparison + what-if
│       └── verify_bill_math.py     # Phase 6: independent bill cross-check (CLI)
│   ├── tariffs/                    # Phase 6: tariff definitions (simple_flat,
│   │                               #          domestic_slabs, time_of_use)
│   └── household_tariffs/          # Phase 6: household per-kWh tariffs (flat,
│                                   #          slabs, time_of_use)
├── backend/
│   ├── run.py               # start the API server (python backend/run.py)
│   └── app/
│       ├── main.py          # FastAPI app: CORS, logging, structured errors, /docs /redoc
│       ├── config.py        # API env settings (reuses ml/scripts/config for paths/units)
│       ├── schemas.py       # Pydantic request/response schemas
│       ├── errors.py        # typed API errors -> JSON error responses
│       ├── agent/           # Phase 9 + 14: tools.py, provider.py (mock/OpenAI-compatible),
│       │                    #          intents.py (Phase 14 conversational routing),
│       │                    #          prompts.py, schemas.py, service.py
│       ├── services/        # consumption, forecast, weather, analytics, anomalies, bills, cache,
│       │                    # upload_service, user_forecast, forecast_classification,
│       │                    # recommendations, household_dashboard (Phase 12), household_analytics,
│       │                    # festival_calendar (Phase 13)
│       └── api/routes/      # health, consumption, forecast, weather, analytics, anomalies, bills,
│                            # agent, forecast_user (incl. /dashboard + /datasets), household analytics
├── frontend/                # Phase 8: React dashboard (Vite + Tailwind v4 + Recharts)
│   ├── index.html
│   ├── vite.config.js       # react + tailwind plugins, jsdom vitest config
│   ├── package.json
│   ├── .env.example         # VITE_API_BASE_URL, VITE_LIVE_REFRESH_MS
│   └── src/
│       ├── main.jsx / App.jsx / index.css   # app shell + dark @theme + routing
│       ├── services/api.js                  # Axios client (all Phase 7 + 11 + 12 endpoints)
│       ├── hooks/useApi.js / usePolling.js  # data fetching + live polling
│       ├── utils/format.js                  # kWh/₹ formatting + scope/currency + chips
│       ├── components/{layout,cards,charts,weather,bills,alerts,forecast}/
│       │                  # forecast/ includes UploadWorkspace + FestivalSection (Phase 13)
│       ├── pages/{Dashboard,Forecast,Analytics,Bills,Settings,Agent}.jsx
│       └── __tests__/ + src/test/setup.js   # Vitest + Testing Library suite (40 tests)
├── notebooks/
│   ├── 01_eda.ipynb           # exploratory data analysis
│   ├── 02_feature_engineering.ipynb  # Phase 2: features + baselines EDA
│   └── 03_models.ipynb              # Phase 3: model comparison EDA
├── tests/
│   ├── test_dataset.py        # Phase 1 pytest suite
│   ├── test_features.py       # Phase 2 pytest suite
│   ├── test_models.py         # Phase 3 pytest suite
│   ├── test_weather.py        # Phase 4 pytest suite
│   ├── test_peak_anomaly.py   # Phase 5 pytest suite
│   ├── test_tariff_bill.py    # Phase 6 pytest suite
│   ├── test_household_bills.py # Phase 6 household bill simulator suite
│   ├── test_api.py            # Phase 7 FastAPI pytest suite
│   ├── test_agent.py          # Phase 9 agent suite (allowlist, tools, scopes, context)
│   ├── test_user_forecast.py  # Phase 11 upload + flexible forecasting suite
│   ├── test_household_dashboard.py # Phase 12 dashboard service + endpoints suite
│   └── test_festival_calendar.py # Phase 13 festival / holiday-aware forecasting suite
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows (bash): source .venv/Scripts/activate
python -m pip install -r requirements.txt
cp .env.example .env               # optional; defaults already match Phase 1
```

## Pipeline

```bash
# 1. Download dataset into ml/data/raw/ (idempotent)
python ml/scripts/download_dataset.py

# 2. Validate dataset -> ml/data/processed/quality_report.json + cleaned parquet
python ml/scripts/validate_dataset.py

# 3. Feature engineering -> features_hourly.parquet + data_splits.json
python ml/scripts/feature_engineering.py

# 4. Baselines -> baseline_report.json (MAE/RMSE/MAPE, best baseline)
python ml/scripts/baselines.py

# 5. Run automated tests (Phase 1 + Phase 2 + Phase 3)
pytest

# 6. Train ML models -> ml/models/*.joblib + model_metrics.json + predictions.csv
python ml/scripts/train_models.py

# 7. Compare models vs baselines -> model_comparison.json + forecast_plot.png
python ml/scripts/evaluate_models.py

# 8. Download hourly weather from Open-Meteo -> weather_hourly.parquet + weather_forecast.json
python ml/scripts/download_weather.py

# 9. Merge weather onto features (exact timestamps) -> weather_features_hourly.parquet
python ml/scripts/weather_features.py

# 10. Train consumption-only vs weather-aware XGBoost -> weather_comparison.json
python ml/scripts/train_weather_models.py

# 11. Weather-consumption visualizations -> plot_*.png
python ml/scripts/plot_weather.py

# 12. Peak-hour analysis + predicted future peaks -> peak_analysis.json + peak_hours_plot.png
python ml/scripts/peak_hours.py

# 13. Anomaly detection -> anomaly_report.json + anomalies_plot.png
python ml/scripts/anomaly_detection.py

# 14. Bill + tariff engine -> bill_report.json + bill_history.csv + bill_history_plot.png
python ml/scripts/bill_engine.py --tariff time_of_use --horizon 1m

# 15. Run automated tests (Phase 1 through Phase 6)
pytest

# 16. Run EDA headlessly
jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/02_feature_engineering.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/03_models.ipynb

# 17. Start the Phase 7 API (docs at /docs, /redoc)
python backend/run.py

# 18. Run all tests (Phase 1 through Phase 12)
pytest

# 19. Install + verify the Phase 8 dashboard (from frontend/)
cd frontend && npm install

# 20. Run the frontend test suite (Vitest + Testing Library, 40 tests)
npm test

# 21. Run the dashboard in dev mode against the running API
npm run dev                      # http://127.0.0.1:5173

# 22. Build the production bundle
npm run build                    # frontend/dist/

# 23. Run the full test suite (Phase 1 through Phase 13, backend)
pytest

# 24. Run the full frontend test suite
npm test                         # (from frontend/)
```

## Quality Report

`ml/data/processed/quality_report.json` contains structured results for every check
(required columns, types, timestamp parsing/ordering, duplicates, missing values, invalid/negative
consumption, date range, sampling frequency, missing intervals, min/max/mean/median, outliers)
and a final `PASS` / `WARN` / `FAIL` status.

## Model Comparison

`ml/data/processed/model_comparison.json` reports MAE / RMSE / MAPE / R² for every
model (random_forest, xgboost) and baseline (previous_hour, previous_day,
moving_average) on the validation and test splits, plus the `best_model` (lowest
validation MAE) and the exact split periods. Per-model training details live in
`model_metrics.json`; validation+test predictions in `predictions.csv`;
`forecast_plot.png` shows the best model vs the naive baseline on the test tail.

## Weather Comparison

`ml/data/processed/weather_comparison.json` reports MAE / RMSE / MAPE / R² on the
validation and test splits for both `consumption_only` and `weather_aware` XGBoost
variants (identical Phase 3 tuning, chronological splits), plus per-metric improvement
deltas and a `weather_improves` verdict (weather-aware test MAE < consumption-only test MAE).
Validation+test predictions live in `predictions_weather.csv`; `plot_*.png` visualize
temperature/humidity/condition/rain vs consumption and the actual vs consumption-only vs
weather-aware forecast on the test tail.

## Peak & Anomaly Reports

`ml/data/processed/peak_analysis.json` reports the average consumption by hour of day, global
maximum demand, peak-to-average ratio, morning/evening peak bands, the top historical peak
periods, and the **predicted future peak periods** (detected on a 14-day iterated forecast
beyond the data end). `peak_hours_plot.png` visualizes the by-hour profile and the forecast.

`ml/data/processed/anomaly_report.json` lists every detected anomaly with timestamp, value,
method (rolling_zscore / hourly_profile / nighttime / isolation_forest), type, score and a
severity bucket (moderate / high / critical), plus counts by method, type and severity.
`anomalies_plot.png` marks all anomalies on the consumption series, colored by severity.

## Bill Report

`ml/data/processed/bill_report.json` reports the current bill (latest full month), previous
month and year-ago bills with percentage increase/decrease, the monthly estimated bill, the
forecasted bill for a user horizon (`2d` / `30d` / `1m` / `2m` / `1y`) and what-if scenarios
(consumption ±10%, and peak-to-off-peak shift savings). Every figure comes from
`ml/scripts/tariffs.py` — deterministic Python, no LLM. `bill_history.csv` +
`bill_history_plot.png` give the full 2015–2018 monthly bill history.

**Mode / scope (important):** this report is the **Regional Grid Energy Cost** mode
(`mode` / `units.scope = "regional_grid"`, `scope_label = "Regional Grid Energy Cost"`). The
consumption series is hourly **regional-grid load in MW** (summed over the billing period →
**MWh**, and `energy_kwh = MWh × 1000`). The report records these units under `units`
(including `tariff_unit = INR/MWh`), and `current_bill.sanity_notes` warns that the billed
energy is region-scale. Reported bills are therefore **regional-scale analytical estimates
(tens of billions of ₹/month), NOT household electricity bills** — they are kept
mathematically correct for the dataset rather than shrunk to look residential. Every regional
bill result carries `scope`, `scope_label`, `consumption_unit`, `energy_unit`, `tariff_unit`
and `reporting_period` (the calendar month).

**Household Bill Simulator (separate mode):** the standalone household calculator lives in
`ml/scripts/household_bills.py` with its own per-kWh tariffs in `ml/household_tariffs/`. It
takes a monthly kWh figure plus tariff options and returns a bill with `scope="household"`,
`consumption_unit/energy_unit="kWh"`, `tariff_unit="INR/kWh"` and `reporting_period="1 month"`.
Its `household_what_if` supports ±10%, custom kWh, bill difference and estimated,
peak-shift savings. Example (350 kWh, `household_slabs`): **₹2,021.25**.

**Peak-shift savings (labeling):** the figure in `what_if.peak_shift_savings` is an
**estimated single-month savings** for `current_bill.period_label`, with an explicit
`assumption` stating that `PEAK_SHIFT_PERCENT` of that month's peak-period energy is
hypothetically shifted from the peak to the off-peak tariff. It is **not** a guaranteed
recurring monthly amount; `what_if.peak_shift_savings_by_month` records the equivalent
single-month estimate labeled separately for each calendar month (also persisted to
`peak_shift_savings_by_month.csv`). The step-by-step computation can be independently
re-verified with:

```bash
python ml/scripts/bill_engine.py --tariff time_of_use --horizon 1m   # regenerate report
python ml/scripts/verify_bill_math.py --tariff time_of_use            # independent cross-check
```

## Later Phases (not implemented)

None — the planned roadmap is complete. Possible future work: persistence for conversations,
retrieval-augmented Q&A over the raw dataset, or multi-user auth.

## License / Attribution

Data by [Kaggle user nicholasjhana](https://www.kaggle.com/datasets/nicholasjhana/energy-consumption-generation-prices-and-weather)
(hourly regional grid load, Spain/ENTSO-E). For personal/portfolio educational use.
