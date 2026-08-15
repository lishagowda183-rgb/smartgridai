import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/layout/AppLayout.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Forecast from "./pages/Forecast.jsx";
import Analytics from "./pages/Analytics.jsx";
import Bills from "./pages/Bills.jsx";
import Agent from "./pages/Agent.jsx";
import Settings from "./pages/Settings.jsx";

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/agent" element={<Agent />} />
        <Route path="/forecast" element={<Forecast />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/bills" element={<Bills />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}