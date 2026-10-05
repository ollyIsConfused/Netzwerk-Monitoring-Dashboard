import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage, formatDateTime, ROLE_LABELS, User, UserRole } from "../../api/client";
import { useAuth } from "../../api/AuthContext";
import { Icon } from "../../components/Icon";
import { ConfirmDialog, Modal, Notice } from "../../components/Modal";

const ROLE_HELP: Record<UserRole, string> = {
  admin: "alles, inkl. Geräte, VLANs und Benutzer verwalten",
  operator: "sehen und Alarme quittieren",
  viewer: "nur ansehen",
};

function UserDialog({ user, onClose, onSaved }: { user: User | null; onClose: () => void; onSaved: () => void }) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<UserRole>(user?.role ?? "viewer");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (user) {
        await api.patch(`/users/${user.id}`, {
          email: email.trim(),
          role,
          is_active: isActive,
          ...(password ? { password } : {}),
        });
      } else {
        await api.post("/users", { username: username.trim(), email: email.trim(), role, password });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={user ? `Benutzer bearbeiten: ${user.username}` : "Benutzer anlegen"} onClose={onClose} size="sm">
      <form className="form" onSubmit={submit}>
        {!user && (
          <label className="field">
            <span>Benutzername</span>
            <input
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              pattern="[A-Za-z0-9._\-]{3,64}"
              title="3–64 Zeichen: Buchstaben, Ziffern, Punkt, Unterstrich, Bindestrich"
              autoComplete="off"
              required
            />
          </label>
        )}
        <label className="field">
          <span>E-Mail</span>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field">
          <span>Rolle</span>
          <select className="select" value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
            {(Object.keys(ROLE_LABELS) as UserRole[]).map((value) => (
              <option key={value} value={value}>
                {ROLE_LABELS[value]} - {ROLE_HELP[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{user ? "Neues Passwort (leer lassen = unverändert)" : "Passwort"}</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            maxLength={72}
            autoComplete="new-password"
            required={!user}
          />
          <small>Mindestens 8 Zeichen.</small>
        </label>
        {user && (
          <label className="checkbox">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Konto aktiv (aus = Anmeldung gesperrt)
          </label>
        )}
        {error && <Notice kind="error">{error}</Notice>}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Abbrechen
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {user ? "Speichern" : "Anlegen"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function UsersAdminPage() {
  const { username: currentUsername } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await api.get<User[]>("/users");
      setUsers(response.data);
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err, "Benutzer konnten nicht geladen werden."));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Benutzer</h1>
          <p>Wer das Dashboard sehen darf und was er tun darf.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>
          <Icon name="plus" />
          Benutzer anlegen
        </button>
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Benutzername</th>
                <th>E-Mail</th>
                <th>Rolle</th>
                <th>Status</th>
                <th>Angelegt</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>
                    {user.username}
                    {user.username === currentUsername && <span className="muted"> (du)</span>}
                  </td>
                  <td>{user.email}</td>
                  <td>
                    <span className={`badge badge-plain${user.role === "admin" ? " badge-role-admin" : ""}`}>
                      {ROLE_LABELS[user.role]}
                    </span>
                  </td>
                  <td>{user.is_active ? "aktiv" : <span className="muted">gesperrt</span>}</td>
                  <td className="num muted">{formatDateTime(user.created_at)}</td>
                  <td className="actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm btn-icon"
                      onClick={() => setEditing(user)}
                      aria-label={`${user.username} bearbeiten`}
                    >
                      <Icon name="edit" size={14} />
                    </button>
                    {user.username !== currentUsername && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon btn-danger"
                        onClick={() => setDeleting(user)}
                        aria-label={`${user.username} löschen`}
                      >
                        <Icon name="trash" size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {editing && (
        <UserDialog user={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={load} />
      )}
      {deleting && (
        <ConfirmDialog
          title="Benutzer löschen"
          message={
            <>
              Benutzer <b>{deleting.username}</b> löschen? Zum vorübergehenden Sperren lieber „Konto aktiv“ ausschalten.
            </>
          }
          onConfirm={async () => {
            await api.delete(`/users/${deleting.id}`);
            await load();
          }}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
