import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";
const API_ROOT = BASE_URL.replace(/\/api\/v1\/?$/, "") || "http://localhost:8000";

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 120000, // iterated forecasts can take a few seconds server-side
  headers: { "Content-Type": "application/json" },
});

const httpRoot = axios.create({
  baseURL: API_ROOT,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const detail = error.response?.data?.error;
    throw new Error(detail?.message || detail?.code || error.message || "Request failed");
  }
);

// --- health / meta -----------------------------------------------------------
export const getHealth = () => httpRoot.get("/health");

// --- consumption ---------------------------------------------------------------
export const getCurrentConsumption = () => http.get("/consumption/current");
export const getConsumptionHistory = (params = {}) =>
  http.get("/consumption/history", { params });

// --- forecast ------------------------------------------------------------------
export const getHourlyForecast = (hours) =>
  http.get("/forecast/hourly", { params: { hours } });
export const getDailyForecast = (days) =>
  http.get("/forecast/daily", { params: { days } });
export const getMonthlyForecast = (months) =>
  http.get("/forecast/monthly", { params: { months } });

// --- weather -------------------------------------------------------------------
export const getCurrentWeather = () => http.get("/weather/current");
export const getWeatherForecast = (days = 7) =>
  http.get("/weather/forecast", { params: { days } });

// --- analytics -----------------------------------------------------------------
export const getHourlyAnalytics = () => http.get("/analytics/hourly");
export const getWeeklyAnalytics = () => http.get("/analytics/weekly");
export const getMonthlyAnalytics = () => http.get("/analytics/monthly");
export const getPeakHours = () => http.get("/analytics/peak-hours");
export const getWeatherRelationship = () => http.get("/analytics/weather-relationship");

// --- anomalies -----------------------------------------------------------------
export const getAnomalies = (params = {}) => http.get("/anomalies", { params });

// --- bills ---------------------------------------------------------------------
export const getRegionalTariffs = () => http.get("/bills/regional/tariffs");
export const getRegionalBill = (params = {}) => http.get("/bills/regional", { params });
export const getHouseholdTariffs = () => http.get("/bills/household/tariffs");
export const calculateHouseholdBill = (payload) =>
  http.post("/bills/household/calculate", payload);
export const calculateHouseholdWhatIf = (payload) =>
  http.post("/bills/household/what-if", payload);

// --- agent (Phase 9) -----------------------------------------------------------
export const chatWithAgent = (message, conversationId) =>
  http.post("/agent/chat", { message, conversation_id: conversationId || null });

// --- user upload + flexible forecasting (Phase 11) ------------------------------
export const uploadDataset = (file) => {
  const form = new FormData();
  form.append("file", file);
  return http.post("/forecast/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const getDataset = (datasetId) => http.get(`/forecast/datasets/${datasetId}`);

export const generateForecast = (payload) => http.post("/forecast/generate", payload);

export const listDatasets = (limit = 5) =>
  http.get("/forecast/datasets", { params: { limit } });

export const getDashboard = (datasetId) =>
  http.get("/forecast/dashboard", { params: datasetId ? { dataset_id: datasetId } : {} });

export const getHouseholdAnalytics = (datasetId) =>
  http.get("/analytics/household", { params: datasetId ? { dataset_id: datasetId } : {} });

export const exportForecastCsv = async (params) => {
  const response = await http.get("/forecast/export", {
    params,
    responseType: "blob",
  });
  const url = window.URL.createObjectURL(new Blob([response]));
  const link = document.createElement("a");
  link.href = url;
  link.download = `forecast_${params.dataset_id}_${params.horizon_value}${params.horizon_unit}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const exportSummaryCsv = async (params) => {
  const response = await http.get("/forecast/export/summary", {
    params,
    responseType: "blob",
  });
  const url = window.URL.createObjectURL(new Blob([response]));
  const link = document.createElement("a");
  link.href = url;
  link.download = `forecast_summary_${params.dataset_id}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export default {
  BASE_URL,
  getHealth,
  getCurrentConsumption,
  getConsumptionHistory,
  getHourlyForecast,
  getDailyForecast,
  getMonthlyForecast,
  getCurrentWeather,
  getWeatherForecast,
  getHourlyAnalytics,
  getWeeklyAnalytics,
  getMonthlyAnalytics,
  getPeakHours,
  getWeatherRelationship,
  getAnomalies,
  getRegionalTariffs,
  getRegionalBill,
  getHouseholdTariffs,
  calculateHouseholdBill,
  calculateHouseholdWhatIf,
  chatWithAgent,
  uploadDataset,
  getDataset,
  generateForecast,
  listDatasets,
  getDashboard,
  getHouseholdAnalytics,
  exportForecastCsv,
  exportSummaryCsv,
};