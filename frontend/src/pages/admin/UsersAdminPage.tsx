import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  api,
  apiErrorMessage,
  formatDateTime,
  notifyCountsChanged,
  ROLE_LABELS,
  TemporaryPasswordResult,
  User,
  UserRole,
} from "../../api/client";
import { useAuth } from "../../api/AuthContext";
import { Icon } from "../../components/Icon";
import { ConfirmDialog, Modal, Notice } from "../../components/Modal";

const ROLE_HELP: Record<UserRole, string> = {
  admin: "alles, inkl. Geräte, VLANs und Benutzer verwalten",
  operator: "sehen und Alarme quittieren",
  viewer: "nur ansehen",
};

type TemporaryPasswordInfo = TemporaryPasswordResult & { username: string };

async function sendTemporaryPassword(user: Pick<User, "id" | "username">): Promise<TemporaryPasswordInfo> {
  const response = await api.post<TemporaryPasswordResult>(`/users/${user.id}/temporary-password`);
  return { ...response.data, username: user.username };
}

function UserDialog({
  user,
  isSelf,
  onClose,
  onSaved,
  onTemporaryPassword,
}: {
  user: User | null;
  isSelf: boolean;
  onClose: () => void;
  onSaved: () => void;
  onTemporaryPassword: (info: TemporaryPasswordInfo) => void;
}) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<UserRole>(user?.role ?? "viewer");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [password, setPassword] = useState("");
  // Beim Anlegen: Einmal-Passwort per E-Mail statt selbst eins auszudenken
  const [sendByMail, setSendByMail] = useState(true);
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
        onSaved();
        onClose();
        return;
      }
      const created = await api.post<User>("/users", {
        username: username.trim(),
        email: email.trim(),
        role,
        ...(sendByMail ? {} : { password }),
      });
      onSaved();
      if (sendByMail) {
        onTemporaryPassword(await sendTemporaryPassword(created.data));
      }
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
          <small>Hierhin gehen Einmal-Passwörter, wenn das Passwort vergessen wurde.</small>
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

        {!user && (
          <label className="checkbox">
            <input type="checkbox" checked={sendByMail} onChange={(e) => setSendByMail(e.target.checked)} />
            Einmal-Passwort erzeugen und per E-Mail schicken
          </label>
        )}
        {isSelf ? (
          <p className="muted" style={{ margin: 0 }}>
            Dein eigenes Passwort änderst du unter „Mein Konto“.
          </p>
        ) : (
          (user || !sendByMail) && (
            <label className="field">
              <span>{user ? "Neues Passwort setzen (leer lassen = unverändert)" : "Startpasswort"}</span>
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
              <small>Mindestens 8 Zeichen. Muss beim nächsten Anmelden durch ein eigenes ersetzt werden.</small>
            </label>
          )
        )}
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

function TemporaryPasswordDialog({ info, onClose }: { info: TemporaryPasswordInfo; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  // Zwischenablage gibt es im Browser nur ueber HTTPS oder localhost
  const canCopy = typeof navigator !== "undefined" && !!navigator.clipboard && window.isSecureContext;

  return (
    <Modal title={`Einmal-Passwort für ${info.username}`} onClose={onClose} size="sm">
      <div className="form">
        {info.email_sent ? (
          <Notice kind="success">
            Einmal-Passwort an <b>{info.email}</b> geschickt. {info.username} muss beim Anmelden sofort ein eigenes
            Passwort festlegen.
          </Notice>
        ) : (
          <>
            <Notice kind="error">
              Die E-Mail an {info.email} konnte nicht verschickt werden (SMTP nicht eingerichtet oder Fehler, Details im
              Backend-Log).
            </Notice>
            <p style={{ margin: 0 }}>
              Gib das Einmal-Passwort selbst an {info.username} weiter. Es wird <b>nur jetzt</b> angezeigt:
            </p>
            <div className="secret-box mono">{info.temporary_password}</div>
            {canCopy && (
              <button
                type="button"
                className="btn"
                onClick={async () => {
                  await navigator.clipboard.writeText(info.temporary_password ?? "");
                  setCopied(true);
                }}
              >
                <Icon name={copied ? "check" : "key"} size={14} />
                {copied ? "Kopiert" : "Kopieren"}
              </button>
            )}
          </>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Fertig
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function UsersAdminPage() {
  const { username: currentUsername } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState<TemporaryPasswordInfo | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await api.get<User[]>("/users");
      setUsers(response.data);
      setError(null);
      notifyCountsChanged();
    } catch (err) {
      setError(apiErrorMessage(err, "Benutzer konnten nicht geladen werden."));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openRequests = users.filter((user) => user.password_reset_requested_at);

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
      {openRequests.length > 0 && (
        <Notice kind="info">
          Passwort vergessen: {openRequests.map((user) => user.username).join(", ")}. Mit dem Schlüssel-Symbol bekommt
          der Benutzer ein Einmal-Passwort an seine E-Mail-Adresse.
        </Notice>
      )}

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
              {users.map((user) => {
                const isSelf = user.username === currentUsername;
                return (
                  <tr key={user.id}>
                    <td>
                      {user.username}
                      {isSelf && <span className="muted"> (du)</span>}
                    </td>
                    <td>{user.email}</td>
                    <td>
                      <span className={`badge badge-plain${user.role === "admin" ? " badge-role-admin" : ""}`}>
                        {ROLE_LABELS[user.role]}
                      </span>
                    </td>
                    <td>
                      <div className="cell-stack">
                        {user.is_active ? "aktiv" : <span className="muted">gesperrt</span>}
                        {user.password_reset_requested_at ? (
                          <span
                            className="badge badge-request"
                            title={`Angefragt am ${formatDateTime(user.password_reset_requested_at)}`}
                          >
                            <Icon name="key" size={13} />
                            Passwort vergessen
                          </span>
                        ) : (
                          user.must_change_password && <small className="muted">wartet auf eigenes Passwort</small>
                        )}
                      </div>
                    </td>
                    <td className="num muted">{formatDateTime(user.created_at)}</td>
                    <td className="actions">
                      {!isSelf && user.is_active && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm btn-icon"
                          onClick={() => setResetting(user)}
                          aria-label={`Einmal-Passwort an ${user.username} senden`}
                          title="Einmal-Passwort senden"
                        >
                          <Icon name="key" size={14} />
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon"
                        onClick={() => setEditing(user)}
                        aria-label={`${user.username} bearbeiten`}
                        title="Bearbeiten"
                      >
                        <Icon name="edit" size={14} />
                      </button>
                      {!isSelf && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm btn-icon btn-danger"
                          onClick={() => setDeleting(user)}
                          aria-label={`${user.username} löschen`}
                          title="Löschen"
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {editing && (
        <UserDialog
          user={editing === "new" ? null : editing}
          isSelf={editing !== "new" && editing.username === currentUsername}
          onClose={() => setEditing(null)}
          onSaved={load}
          onTemporaryPassword={setTemporaryPassword}
        />
      )}
      {resetting && (
        <ConfirmDialog
          title="Einmal-Passwort senden"
          message={
            <>
              Für <b>{resetting.username}</b> ein Einmal-Passwort erzeugen und an <b>{resetting.email}</b> schicken? Das
              bisherige Passwort gilt danach nicht mehr, angemeldete Sitzungen werden beendet.
            </>
          }
          confirmLabel="Einmal-Passwort senden"
          danger={false}
          onConfirm={async () => {
            setTemporaryPassword(await sendTemporaryPassword(resetting));
            await load();
          }}
          onClose={() => setResetting(null)}
        />
      )}
      {temporaryPassword && (
        <TemporaryPasswordDialog info={temporaryPassword} onClose={() => setTemporaryPassword(null)} />
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
