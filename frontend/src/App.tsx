import { Navigate, Route, BrowserRouter, Routes } from "react-router";
import { AuthProvider, useAuth } from "./api/AuthContext";
import { Layout } from "./components/Layout";
import { AccountPage } from "./pages/AccountPage";
import { AlertsPage } from "./pages/AlertsPage";
import { ChangePasswordRequiredPage } from "./pages/ChangePasswordRequiredPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DeviceDetailPage } from "./pages/DeviceDetailPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { LoginPage } from "./pages/LoginPage";
import { DevicesAdminPage } from "./pages/admin/DevicesAdminPage";
import { UsersAdminPage } from "./pages/admin/UsersAdminPage";
import { VlansAdminPage } from "./pages/admin/VlansAdminPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { isAuthenticated, mustChangePassword } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  // Start- oder Einmal-Passwort: das Backend erlaubt bis zum eigenen Passwort ohnehin nichts anderes
  if (mustChangePassword) return <ChangePasswordRequiredPage />;
  return children;
}

// Nur Komfort - die eigentliche Pruefung macht das Backend (403 fuer Nicht-Admins)
function RequireAdmin({ children }: { children: JSX.Element }) {
  const { role } = useAuth();
  if (role !== "admin") return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
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
            <Route path="/account" element={<AccountPage />} />
            <Route path="/admin/devices" element={<RequireAdmin><DevicesAdminPage /></RequireAdmin>} />
            <Route path="/admin/vlans" element={<RequireAdmin><VlansAdminPage /></RequireAdmin>} />
            <Route path="/admin/users" element={<RequireAdmin><UsersAdminPage /></RequireAdmin>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
