import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { AlertEvent, api, onCountsChanged, ROLE_LABELS, User } from "../api/client";
import { useAuth } from "../api/AuthContext";
import { useTheme } from "../theme";
import { Icon, IconName } from "./Icon";

function NavItem({
  to,
  icon,
  label,
  count,
  countLabel,
}: {
  to: string;
  icon: IconName;
  label: string;
  count?: number;
  countLabel?: string;
}) {
  return (
    <NavLink to={to} end={to === "/"} className="nav-link">
      <Icon name={icon} />
      {label}
      {count ? (
        <span className="nav-count" aria-label={`${count} ${countLabel}`}>
          {count}
        </span>
      ) : null}
    </NavLink>
  );
}

export function Layout() {
  const { username, role, logout } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const [activeAlerts, setActiveAlerts] = useState(0);
  const [passwordRequests, setPasswordRequests] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await api.get<AlertEvent[]>("/alerts", { params: { active_only: true } });
        if (!cancelled) setActiveAlerts(response.data.filter((a) => a.level !== "recovered").length);
        if (role === "admin") {
          const users = await api.get<User[]>("/users");
          if (!cancelled) setPasswordRequests(users.data.filter((u) => u.password_reset_requested_at).length);
        }
      } catch {
        // Zaehler sind nur ein Hinweis; Fehler zeigt die jeweilige Seite an
      }
    }
    load();
    const interval = setInterval(load, 30000);
    const unsubscribe = onCountsChanged(load);
    return () => {
      cancelled = true;
      clearInterval(interval);
      unsubscribe();
    };
  }, [role]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="network" size={17} />
          </span>
          Netzwerk-Monitoring
        </div>

        <NavItem to="/" icon="dashboard" label="Übersicht" />
        <NavItem to="/alerts" icon="alert" label="Alarme" count={activeAlerts} countLabel="aktive Alarme" />

        {role === "admin" && (
          <>
            <div className="nav-section">Verwaltung</div>
            <NavItem to="/admin/devices" icon="server" label="Geräte" />
            <NavItem to="/admin/vlans" icon="network" label="VLANs" />
            <NavItem
              to="/admin/users"
              icon="users"
              label="Benutzer"
              count={passwordRequests}
              countLabel="offene Passwort-Anfragen"
            />
          </>
        )}

        <div className="sidebar-footer">
          <NavLink to="/account" className="nav-link user-chip" style={{ padding: "6px 10px" }}>
            <span className="avatar">{username?.slice(0, 1)}</span>
            <span>
              {username}
              <small>{role ? ROLE_LABELS[role] : ""}</small>
            </span>
          </NavLink>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              className="btn btn-ghost btn-icon"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Helles Design" : "Dunkles Design"}
              title={theme === "dark" ? "Helles Design" : "Dunkles Design"}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} />
            </button>
            <button type="button" className="btn btn-ghost" onClick={logout}>
              <Icon name="logout" />
              Abmelden
            </button>
          </div>
        </div>
      </aside>

      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
