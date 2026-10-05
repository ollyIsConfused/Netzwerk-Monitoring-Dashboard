import { useNavigate } from "react-router-dom";
import { useAuth } from "../api/AuthContext";
import { Icon } from "../components/Icon";
import { PasswordChangeForm } from "../components/PasswordChangeForm";

/** Wird statt des Dashboards gezeigt, solange ein Start- oder Einmal-Passwort aktiv ist. */
export function ChangePasswordRequiredPage() {
  const { username, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="login-page">
      <div className="card login-card form">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="network" size={17} />
          </span>
          Netzwerk-Monitoring
        </div>
        <div>
          <h1>Eigenes Passwort festlegen</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Hallo {username}, du bist mit einem Start- oder Einmal-Passwort angemeldet. Lege jetzt ein eigenes
            Passwort fest, erst dann geht es weiter.
          </p>
        </div>
        <PasswordChangeForm
          currentLabel="Bisheriges Passwort (Start- bzw. Einmal-Passwort)"
          submitLabel="Passwort festlegen"
          onChanged={() => navigate("/", { replace: true })}
        />
        <button type="button" className="btn btn-ghost" onClick={logout}>
          <Icon name="logout" />
          Abmelden
        </button>
      </div>
    </div>
  );
}
