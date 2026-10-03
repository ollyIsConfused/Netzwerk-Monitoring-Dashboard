import { NavLink, Outlet } from "react-router";
import { useAuth } from "../api/AuthContext";

export function Layout() {
  const { username, role, logout } = useAuth();

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", minHeight: "100vh" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 24px",
          borderBottom: "1px solid #d0d7de",
        }}
      >
        <nav style={{ display: "flex", gap: 16 }}>
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/alerts">Alarme</NavLink>
        </nav>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <span style={{ fontSize: 14, color: "#57606a" }}>
            {username} ({role})
          </span>
          <button onClick={logout}>Abmelden</button>
        </div>
      </header>
      <main style={{ padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}
