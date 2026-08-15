/* Realistic fixtures matching the Phase 7 FastAPI response shapes. */

export const health = {
  status: "ok",
  app: "SmartGridAI API",
  version: "1.0.0",
  prefix: "/api/v1",
  docs: "/docs",
  redoc: "/redoc",
  timestamp: "2026-08-14T12:00:00+00:00",
};

export const currentConsumption = () => ({
  generated_at: "t",
  unit: "MW",
  scope: "regional grid",
  series_start: "2015-01-08 05:00:00",
  series_end: "2018-12-31 22:00:00",
  count: 34860,
  mean_mw: 28697.0,
  min_mw: 17355.0,
  max_mw: 41015.0,
  latest: { timestamp: "2018-12-31 22:00:00", value_mw: 24455.0 },
  trailing_24h: Array.from({ length: 24 }, (_, i) => ({
    timestamp: `2018-12-31 ${String(i).padStart(2, "0")}:00:00`,
    value_mw: 24000 + i * 10,
  })),
});

export const hourlyForecast = (hours = 24) => ({
  generated_at: "t",
  horizon: `${hours}h`,
  horizon_hours: hours,
  unit: "MW",
  model: "consumption_only_xgboost.joblib",
  start: "2018-12-31 23:00:00",
  end: "2019-01-01 22:00:00",
  count: hours,
  points: Array.from({ length: hours }, (_, i) => ({
    timestamp: `2019-01-01 ${String(i % 24).padStart(2, "0")}:00:00`,
    value_mw: 25000 + (i % 10) * 500,
  })),
});

export const dailyForecast = () => ({
  generated_at: "t",
  horizon: "7d",
  unit: "MW",
  energy_unit: "MWh",
  model: "consumption_only_xgboost.joblib",
  days: Array.from({ length: 7 }, (_, i) => ({
    date: `2019-01-0${i + 1}`,
    mean_mw: 26000 + i * 200,
    energy_mwh: 624000 + i * 4800,
  })),
});

export const currentWeather = () => ({
  generated_at: "t",
  source: "ml/data/raw/weather_forecast.json",
  location: {
    latitude: 40.4375,
    longitude: -3.6875,
    timezone: "Europe/Madrid",
    timezone_abbreviation: "GMT+2",
    elevation: 666.0,
    utc_offset_seconds: 7200,
    _generated_at: "2026-08-13T19:30:00+00:00",
  },
  current: {
    time: "2026-08-13T19:30",
    temperature_c: 37.7,
    humidity_pct: 14,
    precipitation_mm: 0.0,
    wind_speed_kmh: 10.4,
    weather_code: 0,
    condition: "clear",
  },
  _generated_at: "2026-08-13T19:30:00+00:00",
});

export const weatherForecast = () => ({
  generated_at: "t",
  source: "ml/data/raw/weather_forecast.json",
  requested_days: 3,
  returned_hours: 72,
  points: Array.from({ length: 24 }, (_, i) => ({
    time: `2026-08-14T${String(i).padStart(2, "0")}:00`,
    temperature_c: 30 + (i % 6),
    humidity_pct: 20 + i,
    precipitation_mm: 0.0,
    wind_speed_kmh: 8.0,
    weather_code: 0,
    condition: "clear",
  })),
});

export const peakHours = () => ({
  generated_at: "t",
  source: "ml/data/processed/peak_analysis.json",
  summary: {
    peak_hour_of_day: 19,
    max_demand: { timestamp: "2017-01-18 19:00:00", value: 41015.0 },
    peak_to_average_ratio: 1.43,
  },
  average_by_hour: Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    mean_consumption: 23000 + (i === 19 ? 32000 : i * 300),
    median_consumption: 23000,
    std: 1600,
    count: 1450,
  })),
  morning_peak_days: 10,
  evening_peak_days: 10,
  top_historical_peak_periods: [],
  forecast: {
    model: "consumption_only_xgboost.joblib",
    horizon_days: 14,
    start: "2018-12-31 23:00:00",
    end: "2019-01-14 22:00:00",
    predicted_future_peak_periods: [
      { start: "2019-01-02 18:00:00", end: "2019-01-02 20:00:00", duration_hours: 3, peak_value: 35972.65, mean_value: 35588.19 },
    ],
  },
});

export const anomalies = () => ({
  generated_at: "t",
  source: "ml/data/processed/anomaly_report.json",
  counts_by_method: { isolation_forest: 349, nighttime: 64, rolling_zscore: 13, hourly_profile: 4 },
  counts_by_severity: { moderate: 417, high: 13 },
  returned: 3,
  total_matching: 430,
  anomalies: [
    { timestamp: "2015-01-20 19:00:00", value: 40207.0, method: "isolation_forest", type: "outlier", score: 0.59, severity: "moderate" },
    { timestamp: "2015-02-10 03:00:00", value: 40110.0, method: "nighttime", type: "outlier", score: 0.71, severity: "high" },
    { timestamp: "2015-03-01 08:00:00", value: 38990.0, method: "rolling_zscore", type: "spike", score: 0.77, severity: "high" },
  ],
});

export const weatherRelationship = () => ({
  generated_at: "t",
  n_rows: 34860,
  unit: "MW",
  correlations: [
    { variable: "temperature", pearson: 0.103, interpretation: "very weak positive" },
    { variable: "humidity", pearson: -0.129, interpretation: "very weak negative" },
    { variable: "precipitation", pearson: 0.01, interpretation: "very weak positive" },
    { variable: "wind_speed", pearson: 0.035, interpretation: "very weak positive" },
  ],
  temperature_buckets: [
    { bucket: "0..3", min_temp: 0.1, max_temp: 2.9, mean_consumption_mw: 26500.0, count: 1200 },
    { bucket: "9..12", min_temp: 9.1, max_temp: 11.9, mean_consumption_mw: 27800.0, count: 3500 },
    { bucket: "30..33", min_temp: 30.1, max_temp: 32.9, mean_consumption_mw: 29900.0, count: 900 },
  ],
});

export const weeklyAnalytics = () => ({
  generated_at: "t",
  unit: "MW",
  type: "day_of_week",
  points: [0, 1, 2, 3, 4, 5, 6].map((d) => ({
    day_of_week: d,
    day_name: "Mon",
    mean_mw: 28500 + (d >= 5 ? -1200 : d * 100),
    count: 400,
  })),
});

export const monthlyAnalytics = () => ({
  generated_at: "t",
  unit: "MW",
  type: "month_of_year",
  points: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((m) => ({
    month: m,
    month_name: "X",
    mean_mw: 27000 + (m === 1 || m === 8 ? 2600 : (m % 4) * 300),
    count: 700,
  })),
});

export const regionalBill = () => ({
  generated_at: "t",
  currency: "INR",
  mode: "regional_grid",
  units: {
    scope: "regional_grid",
    scope_label: "Regional Grid Energy Cost",
    consumption_unit: "MW",
    energy_unit: "MWh",
    kwh_per_mwh: 1000,
    tariff_unit: "INR/MWh",
  },
  tariff: { name: "time_of_use", display_name: "Time of Use", currency: "INR" },
  horizon: "1m",
  _served_from: "cache",
  current_bill: {
    period_label: "2018-12",
    reporting_period: "2018-12",
    consumption_unit: "MW",
    energy_unit: "MWh",
    tariff_unit: "INR/MWh",
    hours: 744,
    energy_mwh: 21494087.0,
    energy_kwh: 21494087000.0,
    peak_mwh: 8697000.0,
    off_peak_mwh: 12797087.0,
    energy_charge: 74188773000.0,
    fixed_charge: 250.0,
    additional_charges: 0.0,
    tax_pct: 5.0,
    taxes: 3709438662.5,
    total: 77898211912.5,
    sanity_notes: ["Series is regional-grid load (hourly MW), not a household meter."],
  },
  comparison: {
    current_month: "2018-12",
    previous_month: "2018-11",
    change_vs_previous_pct: 1.45,
    year_ago_month: "2017-12",
    change_yoy_pct: -0.45,
  },
  monthly_estimated_bill: { total: 75730917119.24, period_label: "estimated_next_30d" },
  forecasted_bill: { total: 75730917119.24, period_label: "forecast 1m" },
  what_if: {
    consume_plus_10pct: { total: 85688033077.5, change_pct: 10.0 },
    consume_minus_10pct: { total: 70108390771.5, change_pct: -10.0 },
    peak_shift_savings: {
      applicable: true,
      period_label: "2018-12",
      shift_pct: 10.0,
      peak_mwh_in_bill: 8697085.0,
      shifted_mwh: 869708.5,
      peak_rate_per_mwh: 4000.0,
      off_peak_rate_per_mwh: 2000.0,
      estimated_savings: 1739417000.0,
      new_estimated_total: 76158794912.5,
    },
  },
});

export const householdTariffs = () => [
  { name: "household_flat", display_name: "Household Flat", currency: "INR" },
  { name: "household_slabs", display_name: "Household Slabs", currency: "INR" },
  { name: "household_tou", display_name: "Household ToU", currency: "INR" },
];

export const householdCalculate = () => ({
  scope: "household",
  scope_label: "Household Bill Simulator",
  reporting_period: "1 month",
  consumption_unit: "kWh",
  energy_unit: "kWh",
  tariff_unit: "INR/kWh",
  monthly_consumption_kwh: 350,
  energy_kwh: 350,
  energy_charge: 1700.0,
  fixed_charge: 200.0,
  additional_charges: 25.0,
  tax_pct: 5.0,
  taxes: 96.25,
  total: 2021.25,
  peak_kwh: 0,
  off_peak_kwh: 350,
  currency: "INR",
});

export const householdWhatIf = () => ({
  scope: "household",
  scope_label: "Household Bill Simulator",
  reporting_period: "1 month",
  tariff_unit: "INR/kWh",
  base: { monthly_consumption_kwh: 350, total: 2021.25 },
  plus_10pct: { consumption_kwh: 385, total: 2221.0, change_pct: 9.88 },
  minus_10pct: { consumption_kwh: 315, total: 1821.5, change_pct: -9.88 },
  custom: { monthly_consumption_kwh: 300, total: 1741.0, change_pct: -13.86 },
  bill_difference: { from_consumption_kwh: 350, to_consumption_kwh: 300, amount: -280.25, pct: -13.86 },
  estimated_savings: { applicable: true, shift_pct: 10, savings_per_month: 38.5, assumption: "10% of peak-period kWh shifted." },
});

export const agentChat = () => ({
  answer:
    "Your household is forecast to use about 9,300 kWh in the next 7 days. These figures come entirely from your uploaded file my_energy.csv (household, kWh).",
  tools_used: ["get_household_overview"],
  data_points: [
    { label: "Average daily", value: 1330, unit: "kWh" },
    { label: "Next 7 days", value: 9321, unit: "kWh" },
  ],
  scope: "household",
  timestamp: "2026-08-14T12:00:00+00:00",
  conversation_id: "conv-test-1",
  model: "mock-router",
  mode: "mock",
});

// --- Phase 11: user upload + flexible forecasting -------------------------------
export const uploadedDataset = () => ({
  dataset_id: "ds_test1",
  filename: "my_energy.csv",
  rows: 17520,
  rows_total: 17520,
  removed_rows: { unparseable_timestamps: 0, non_numeric_consumption: 0, negative: 0, duplicate_timestamps: 0 },
  start_date: "2024-01-01 00:00:00",
  end_date: "2025-12-31 23:00:00",
  frequency: "hourly",
  timestamp_column: "timestamp",
  consumption_column: "consumption",
  unit: "kWh",
  energy_unit: "kWh",
  scope: {
    scope: "household",
    unit: "kWh",
    detected_by: "magnitude",
    need_selection: false,
    note: "detected via magnitude heuristic",
  },
  validation_status: "valid",
  warnings: [],
  statistics: { min: 210.0, max: 489.0, mean: 342.0, median: 340.0, std: 40.0 },
  created_at: "2026-08-15T00:00:00+00:00",
});

export const datasetDetail = () => ({
  ...uploadedDataset(),
  preview: Array.from({ length: 5 }, (_, i) => ({
    timestamp: `2024-01-01 ${String(i).padStart(2, "0")}:00:00`,
    consumption: 320 + i * 10,
  })),
});

const forecastPoints = () =>
  Array.from({ length: 30 }, (_, i) => ({
    timestamp: `2026-01-${String(i + 1).padStart(2, "0")} 00:00:00`,
    predicted_consumption: 8800 + (i % 7) * 60,
    lower_bound: 8500,
    upper_bound: 10000,
    classification: ["LOW", "MEDIUM", "HIGH"][i % 3],
  }));

const historicalTail = () =>
  Array.from({ length: 14 }, (_, i) => ({
    timestamp: `2025-12-${String(18 + i).padStart(2, "0")} 00:00:00`,
    value: 8700 + (i % 4) * 50,
  }));

export const forecastResult = () => ({
  dataset_id: "ds_test1",
  filename: "my_energy.csv",
  horizon: { value: 30, unit: "days", days: 30 },
  forecast_type: "medium_term",
  forecast_type_label: "Medium-term (8 days – 6 months)",
  unit: "kWh",
  energy_unit: "kWh",
  scope: "household",
  displayed: "daily",
  display_granularity: "daily",
  status: "MEDIUM",
  trend: "STABLE",
  warning: null,
  summary: {
    average: 8890,
    minimum: 8500,
    maximum: 9961,
    total: 266700,
    change_percent: 1.39,
    high_periods: 10,
    medium_periods: 10,
    low_periods: 10,
    periods: 30,
    granularity: "daily",
  },
  classification: {
    low_threshold: 8546.96,
    high_threshold: 9457.62,
    method: "percentiles of the uploaded history (p33 / p66)",
    counts: { LOW: 10, MEDIUM: 10, HIGH: 10 },
    percentages: { LOW: 33.3, MEDIUM: 33.3, HIGH: 33.3 },
    thresholds: { low: 8546.96, high: 9457.62 },
    note: "Thresholds are the 33rd/66th percentiles of the uploaded historical consumption distribution.",
    historical_mean: 8890,
    forecast_mean: 9013.61,
    forecast_change_percent: 1.39,
    historical_90th_percentile: 9850,
    high_period_count: 4,
    high_period_percentage: 13.3,
    forecast_peak: 9961.5,
    status: "MEDIUM",
    reason: "Forecast consumption is in line with the household historical baseline. Forecast average 9013.61 kWh vs historical average 8890 kWh (+1.4%). 4 of 30 predicted daily periods (13.3%) are at or above the household's historical 90th percentile.",
    warning: null,
  },
  peak: {
    timestamp: "2026-01-17 00:00:00",
    value: 9961.5,
    peak_hour: null,
    peak_time_label: "2026-01-17",
    average: 8890,
    peak_to_average_ratio: 1.12,
  },
  points: forecastPoints(),
  historical: historicalTail(),
  intervals_available: true,
  weather: {
    status: "none",
    label: "unavailable",
    weather_status: "none",
    weather_available: false,
    weather_source: null,
    weather_features_used: [],
    weather_note: "No future weather data is available for the forecast period; the model uses only the uploaded history.",
    note: "No future weather data is available for the forecast period; the model uses only the uploaded history.",
  },
  recommendations: [
    {
      id: "stable_demand",
      message: "Demand is expected to remain fairly stable compared with the historical baseline.",
      basis: "Change vs baseline and classification shares are within normal bounds.",
    },
  ],
  household_bill: {
    total: 216490.38,
    forecasted_monthly_kwh: 8890.0,
    tariff_unit: "INR/kWh",
    assumption: "Bill is estimated from the forecasted monthly kWh via the backend bill engine.",
  },
  festivals: {
    analysis: [
      {
        festival_name: "Diwali",
        date: "2025-10-20",
        data_available: true,
        normal_average_kwh: 8900.0,
        festival_average_kwh: 11214.0,
        difference_kwh: 2314.0,
        difference_percent: 26.0,
        observation_count: 14,
        classification: "HIGHER_THAN_NORMAL",
        baseline_method: "same weekday (+ hour of day for sub-daily data) over the same season (+/-30 days), excluding festival windows",
      },
      {
        festival_name: "Raksha Bandhan",
        date: "2025-08-09",
        data_available: false,
        observation_count: 2,
        minimum_observations: 12,
        note: "Insufficient historical household data to estimate a festival-specific effect.",
      },
    ],
    upcoming: [
      {
        festival_name: "Diwali",
        date: "2026-11-08",
        window_start: "2026-11-05",
        window_end: "2026-11-11",
        national_holiday: false,
        festival_data_available: true,
        historical_effect_percent: 26.0,
        historical_classification: "HIGHER_THAN_NORMAL",
        festival_effect_percent: 26.0,
        note: "Based on historical household data.",
      },
      {
        festival_name: "Christmas",
        date: "2026-12-25",
        window_start: "2026-12-22",
        window_end: "2026-12-28",
        national_holiday: true,
        festival_data_available: false,
        historical_effect_percent: null,
        historical_classification: null,
        festival_effect_percent: null,
        note: "Insufficient historical household data to estimate a festival-specific effect.",
      },
    ],
    applied: [
      {
        festival_name: "Diwali",
        date: "2026-11-08",
        window_start: "2026-11-05",
        window_end: "2026-11-11",
        national_holiday: false,
        festival_data_available: true,
        historical_effect_percent: 26.0,
        historical_classification: "HIGHER_THAN_NORMAL",
        festival_effect_percent: 26.0,
        applied_multiplier: 1.26,
        note: "Based on historical household data.",
      },
    ],
    calendar_note:
      "Festival dates are a curated pan-Indian approximation (lunisolar/Eid dates vary regionally and by lunar sighting). Customize via FESTIVAL_CALENDAR_JSON for state/region-specific accuracy.",
    note: "Festival/calendar dates for the forecast period are KNOWN from the deterministic calendar.",
    weather_note: "Weather is available and combined with festival/calendar features where they overlap.",
    weather_available: false,
  },
  generated_at: "2026-08-15T00:00:00+00:00",
});

const householdPoints = () =>
  Array.from({ length: 30 }, (_, i) => ({
    timestamp: `2026-01-${String(i + 1).padStart(2, "0")} 00:00:00`,
    predicted_consumption: 9100 + (i % 7) * 60,
    lower_bound: 8600,
    upper_bound: 10100,
    classification: ["MEDIUM", "HIGH", "MEDIUM"][i % 3],
    peak_flag: i === 17,
    weather_available: false,
  }));

const householdHistorical = () =>
  Array.from({ length: 14 }, (_, i) => ({
    timestamp: `2025-12-${String(18 + i).padStart(2, "0")} 00:00:00`,
    value: 8900 + (i % 4) * 50,
  }));

export const householdDashboard = () => ({
  dataset_id: "ds_test1",
  filename: "my_energy.csv",
  scope: "household",
  unit: "kWh",
  energy_unit: "kWh",
  frequency: "hourly",
  rows: 17520,
  start_date: "2024-01-01 00:00:00",
  end_date: "2025-12-31 23:00:00",
  current: {
    timestamp: "2025-12-31 22:00:00",
    value: 342.5,
    unit: "kWh",
    frequency: "hourly",
    trailing_total: 9100.0,
  },
  today: { date: "2025-12-30", value: 9310.0, unit: "kWh" },
  tomorrow: { date: "2025-12-31", value: 9380.0, unit: "kWh" },
  week: {
    start_date: "2025-12-30",
    end_date: "2026-01-05",
    total: 65520.0,
    average_daily: 9360.0,
    change_percent: 3.2,
    unit: "kWh",
  },
  month: {
    total: 280800.0,
    average_daily: 9360.0,
    days: 30,
    change_percent: 1.4,
    granularity: "daily",
    unit: "kWh",
  },
  peak: {
    timestamp: "2026-01-17 00:00:00",
    value: 9847.5,
    peak_hour: null,
    peak_time_label: "2026-01-17",
    average: 9360.0,
    peak_to_average_ratio: 1.05,
  },
  status: "MEDIUM",
  model: "seasonaltrend",
  model_features: ["trend", "seasonality"],
  trend: "stable",
  display_label: "Next 7 days (daily)",
  weather: {
    status: "none",
    label: "unavailable",
    weather_status: "none",
    weather_available: false,
    weather_source: null,
    weather_features_used: [],
    weather_note: "No future weather data overlaps this forecast period; the forecast uses your historical consumption patterns.",
    note: "No future weather data overlaps this forecast period; the forecast uses your historical consumption patterns.",
  },
  weather_now: {
    generatedAt: "2026-08-15T00:00:00+00:00",
    generated_at: "2026-08-15T00:00:00+00:00",
    source: "ml/data/raw/weather_forecast.json",
    location: {
      latitude: 40.4375,
      longitude: -3.6875,
      timezone: "Europe/Madrid",
      timezone_abbreviation: "GMT+2",
      elevation: 666.0,
      _generated_at: "2026-08-13T19:30:00+00:00",
    },
    observation: {
      time: "2026-08-13T19:30",
      temperature_c: 33.4,
      humidity_pct: 22,
      precipitation_mm: 0.0,
      wind_speed_kmh: 12.6,
      weather_code: 0,
      condition: "clear",
    },
    _generated_at: "2026-08-13T19:30:00+00:00",
  },
  recommendations: [
    {
      id: "stable_demand",
      message: "Consumption is expected to stay fairly stable over the next week.",
      basis: "Change vs baseline within normal bounds.",
    },
  ],
  household_bill: {
    scope: "household",
    scope_label: "Household Bill Simulator",
    reporting_period: "1 month",
    tariff_unit: "INR/kWh",
    monthly_consumption_kwh: 9360.0,
    energy_charge: 24560.0,
    fixed_charge: 200.0,
    additional_charges: 25.0,
    tax_pct: 5.0,
    taxes: 1239.25,
    total: 26024.25,
    forecasted_period: "next 30 days",
    forecasted_monthly_kwh: 9360.0,
  },
  points: householdPoints(),
  historical_tail: householdHistorical(),
  display_granularity: "daily",
  onboarding: false,
  generated_at: "2026-08-15T00:00:00+00:00",
});

const hourRows = (base) =>
  Array.from({ length: 24 }, (_, i) => {
    const mean = i >= 18 && i <= 22 ? base * 1.6 : base * (0.7 + (i % 5) * 0.06);
    return { value: i, mean: Math.round(mean), median: Math.round(mean), std: 40, min: 210, max: 489, count: 730 };
  });

export const householdAnalytics = () => ({
  dataset_id: "ds_test1",
  filename: "my_energy.csv",
  unit: "kWh",
  rows: 17520,
  by_hour: hourRows(382),
  by_day_of_week: [0, 1, 2, 3, 4, 5, 6].map((d) => ({
    value: d,
    day_name: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][d],
    mean: d >= 5 ? 340 : 395,
    median: 338,
    std: 45,
    min: 210,
    max: 489,
    count: 2500,
  })),
  by_month: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((m) => ({
    value: m,
    month_name: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1],
    mean: m === 8 ? 410 : 368,
    median: 365,
    std: 48,
    min: 210,
    max: 489,
    count: 1460,
  })),
  monthly_trend: ["2024-01", "2024-02", "2024-03"].map((m, i) => ({
    month: m,
    total: 26800 + i * 900,
    average_daily: 864.0 + i * 29,
  })),
  distribution: [230, 300, 380, 450].map((bin, i) => ({
    bin: `${bin - 70}–${bin}`,
    count: 1000 - i * 150,
  })),
  peak_hours: {
    peak_hours: [18, 19, 20].map((h) => ({ hour: h, mean: 611 })),
    peak_to_average_ratio: 1.6,
    note: "Evening usage dominates (h18–h22).",
  },
  weather_correlations: {
    available: false,
    note: "Historical weather only covers 2015–2018, which does not overlap your uploaded 2024–2025 data, so no weather correlation is shown.",
  },
  anomalies: {
    available: true,
    count: 2,
    threshold: 3,
    window: 24,
    anomalies: [
      { timestamp: "2024-06-15 19:00:00", observed: 489, historical_avg: 382, deviation: 107, zscore: 4.1, severity: "high" },
      { timestamp: "2024-12-03 08:00:00", observed: 460, historical_avg: 370, deviation: 90, zscore: 3.4, severity: "moderate" },
    ],
  },
  generated_at: "2026-08-15T00:00:00+00:00",
});

export const datasetList = () => ({
  datasets: [
    {
      dataset_id: "ds_test1",
      filename: "my_energy.csv",
      rows: 17520,
      frequency: "hourly",
      start_date: "2024-01-01 00:00:00",
      end_date: "2025-12-31 23:00:00",
      scope: { scope: "household", unit: "kWh" },
    },
  ],
  total: 1,
  active_dataset_id: "ds_test1",
});

/**
 * Build a complete api-service mock module (vi.fn stubs resolving to the
 * fixtures above). Pass the `vi` from vitest.
 */
export function createApiModule(vi) {
  return {
    getHealth: vi.fn().mockResolvedValue(health),
    getCurrentConsumption: vi.fn().mockResolvedValue(currentConsumption()),
    getConsumptionHistory: vi.fn().mockResolvedValue({ points: currentConsumption().trailing_24h }),
    getHourlyForecast: vi.fn().mockImplementation((h = 24) => Promise.resolve(hourlyForecast(h))),
    getDailyForecast: vi.fn().mockResolvedValue(dailyForecast()),
    getMonthlyForecast: vi.fn().mockResolvedValue({ months: [] }),
    getCurrentWeather: vi.fn().mockResolvedValue(currentWeather()),
    getWeatherForecast: vi.fn().mockResolvedValue(weatherForecast()),
    getHourlyAnalytics: vi.fn().mockResolvedValue({ points: [] }),
    getWeeklyAnalytics: vi.fn().mockResolvedValue(weeklyAnalytics()),
    getMonthlyAnalytics: vi.fn().mockResolvedValue(monthlyAnalytics()),
    getPeakHours: vi.fn().mockResolvedValue(peakHours()),
    getWeatherRelationship: vi.fn().mockResolvedValue(weatherRelationship()),
    getAnomalies: vi.fn().mockResolvedValue(anomalies()),
    getRegionalTariffs: vi.fn().mockResolvedValue({ tariffs: ["domestic_slabs", "simple_flat", "time_of_use"] }),
    getRegionalBill: vi.fn().mockResolvedValue(regionalBill()),
    getHouseholdTariffs: vi.fn().mockResolvedValue({
      tariffs: ["household_flat", "household_slabs", "household_tou"],
    }),
    calculateHouseholdBill: vi.fn().mockResolvedValue(householdCalculate()),
    calculateHouseholdWhatIf: vi.fn().mockResolvedValue(householdWhatIf()),
    chatWithAgent: vi.fn().mockResolvedValue(agentChat()),
    uploadDataset: vi.fn().mockResolvedValue(uploadedDataset()),
    getDataset: vi.fn().mockResolvedValue(datasetDetail()),
    generateForecast: vi.fn().mockResolvedValue(forecastResult()),
    listDatasets: vi.fn().mockResolvedValue(datasetList()),
    getDashboard: vi.fn().mockResolvedValue(householdDashboard()),
    getHouseholdAnalytics: vi.fn().mockResolvedValue(householdAnalytics()),
    exportForecastCsv: vi.fn().mockResolvedValue(undefined),
    exportSummaryCsv: vi.fn().mockResolvedValue(undefined),
    default: { BASE_URL: "http://test/api/v1" },
  };
}