import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { apiErrorMessage } from "../api/client";
import { useAuth } from "../api/AuthContext";
import { Icon } from "../components/Icon";
import { Notice } from "../components/Modal";

export function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isAuthenticated) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
    } catch (err) {
      // Unterscheidet "falsches Passwort" von "Backend nicht erreichbar"
      setError(apiErrorMessage(err, "Anmeldung fehlgeschlagen."));
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="card login-card form" onSubmit={handleSubmit}>
        <div className="brand">
          <span className="brand-mark">
            <Icon name="network" size={17} />
          </span>
          Netzwerk-Monitoring
        </div>
        <div>
          <h1>Anmelden</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Mit deinem Benutzernamen, nicht der E-Mail-Adresse.
          </p>
        </div>
        <label className="field">
          <span>Benutzername</span>
          <input
            className="input"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label className="field">
          <span>Passwort</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <Notice kind="error">{error}</Notice>}
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Anmelden…" : "Anmelden"}
        </button>
      </form>
    </div>
  );
}
