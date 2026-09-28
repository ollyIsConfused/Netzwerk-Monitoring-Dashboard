import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./api/AuthContext";
import { Layout } from "./components/Layout";
import { AlertsPage } from "./pages/AlertsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DeviceDetailPage } from "./pages/DeviceDetailPage";
import { LoginPage } from "./pages/LoginPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/devices/:deviceId" element={<DeviceDetailPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
