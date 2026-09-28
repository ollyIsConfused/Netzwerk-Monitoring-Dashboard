import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../api/AuthContext";

export function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (isAuthenticated) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await login(username, password);
    } catch {
      setError("Anmeldung fehlgeschlagen. Bitte Benutzername/Passwort prüfen.");
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", marginTop: 100 }}>
      <form
        onSubmit={handleSubmit}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          width: 320,
          padding: 24,
          border: "1px solid #d0d7de",
          borderRadius: 8,
          background: "#fff",
        }}
      >
        <h2 style={{ margin: 0 }}>Netzwerk-Monitoring</h2>
        <input
          placeholder="Benutzername"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
        <input
          placeholder="Passwort"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <div style={{ color: "#cf222e", fontSize: 14 }}>{error}</div>}
        <button type="submit">Anmelden</button>
      </form>
    </div>
  );
}
