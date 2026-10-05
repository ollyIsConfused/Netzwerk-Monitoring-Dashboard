import { FormEvent, useEffect, useState } from "react";
import { api, apiErrorMessage, ROLE_LABELS, User } from "../api/client";
import { Notice } from "../components/Modal";

export function AccountPage() {
  const [me, setMe] = useState<User | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<User>("/auth/me")
      .then((response) => setMe(response.data))
      .catch(() => setMe(null));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== repeat) {
      setMessage({ kind: "error", text: "Die neuen Passwörter stimmen nicht überein." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setRepeat("");
      setMessage({ kind: "success", text: "Passwort geändert. Beim nächsten Anmelden gilt das neue Passwort." });
    } catch (err) {
      setMessage({ kind: "error", text: apiErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 560 }}>
      <div className="page-header">
        <div>
          <h1>Mein Konto</h1>
          {me && (
            <p>
              {me.username} · {me.email} · {ROLE_LABELS[me.role]}
            </p>
          )}
        </div>
      </div>

      <section className="card">
        <div className="card-header">
          <h2>Passwort ändern</h2>
        </div>
        <form className="card-body form" onSubmit={submit}>
          <label className="field">
            <span>Aktuelles Passwort</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </label>
          <label className="field">
            <span>Neues Passwort</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              minLength={8}
              maxLength={72}
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
            <small>8–72 Zeichen. Sonderzeichen sind hier problemlos möglich.</small>
          </label>
          <label className="field">
            <span>Neues Passwort wiederholen</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              required
            />
          </label>
          {message && <Notice kind={message.kind}>{message.text}</Notice>}
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              Passwort ändern
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
