import { useEffect, useState } from "react";
import { api, ROLE_LABELS, User } from "../api/client";
import { Notice } from "../components/Modal";
import { PasswordChangeForm } from "../components/PasswordChangeForm";

export function AccountPage() {
  const [me, setMe] = useState<User | null>(null);
  const [changed, setChanged] = useState(false);

  useEffect(() => {
    api
      .get<User>("/auth/me")
      .then((response) => setMe(response.data))
      .catch(() => setMe(null));
  }, []);

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
        <div className="card-body form">
          {changed && (
            <Notice kind="success">
              Passwort geändert. Andere Geräte, auf denen du angemeldet warst, sind jetzt abgemeldet.
            </Notice>
          )}
          <PasswordChangeForm onChanged={() => setChanged(true)} />
        </div>
      </section>
    </div>
  );
}
