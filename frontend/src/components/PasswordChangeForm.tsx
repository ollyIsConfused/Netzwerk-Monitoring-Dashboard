import { FormEvent, useState } from "react";
import { api, apiErrorMessage, TokenResponse } from "../api/client";
import { useAuth } from "../api/AuthContext";
import { Notice } from "./Modal";

/** Passwort aendern - fuer "Mein Konto" und die Pflicht-Seite nach Start-/Einmal-Passwort. */
export function PasswordChangeForm({
  currentLabel = "Aktuelles Passwort",
  submitLabel = "Passwort ändern",
  onChanged,
}: {
  currentLabel?: string;
  submitLabel?: string;
  onChanged: () => void;
}) {
  const { applyToken } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== repeat) {
      setError("Die neuen Passwörter stimmen nicht überein.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await api.post<TokenResponse>("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      // Alte Tokens gelten nicht mehr - mit dem neuen bleibt diese Sitzung angemeldet
      applyToken(response.data);
      setCurrent("");
      setNext("");
      setRepeat("");
      onChanged();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label className="field">
        <span>{currentLabel}</span>
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
      {error && <Notice kind="error">{error}</Notice>}
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {submitLabel}
        </button>
      </div>
    </form>
  );
}
