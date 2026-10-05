import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, apiErrorMessage } from "../api/client";
import { useAuth } from "../api/AuthContext";
import { Icon } from "../components/Icon";
import { Notice } from "../components/Modal";

export function ForgotPasswordPage() {
  const { isAuthenticated } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isAuthenticated) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/auth/forgot-password", { username: username.trim(), email: email.trim() });
      setSent(true);
    } catch (err) {
      setError(apiErrorMessage(err, "Anfrage fehlgeschlagen."));
    } finally {
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
          <h1>Passwort vergessen</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Der Administrator bekommt eine Nachricht und schickt dir ein Einmal-Passwort an deine E-Mail-Adresse.
          </p>
        </div>

        {sent ? (
          <Notice kind="success">
            Anfrage verschickt. Wenn Benutzername und E-Mail-Adresse zu einem Konto passen, ist der Administrator
            benachrichtigt. Das Einmal-Passwort kommt per E-Mail, sobald er es verschickt hat.
          </Notice>
        ) : (
          <>
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
              <span>E-Mail-Adresse</span>
              <input
                className="input"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
              <small>Die Adresse, die bei deinem Konto hinterlegt ist.</small>
            </label>
            {error && <Notice kind="error">{error}</Notice>}
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "Senden…" : "Anfrage senden"}
            </button>
          </>
        )}
        <div className="login-links">
          <Link to="/login">Zurück zur Anmeldung</Link>
        </div>
      </form>
    </div>
  );
}
