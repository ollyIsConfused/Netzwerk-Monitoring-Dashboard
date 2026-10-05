import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage, Device, Vlan } from "../../api/client";
import { Icon } from "../../components/Icon";
import { ConfirmDialog, Modal, Notice } from "../../components/Modal";

function VlanDialog({ vlan, onClose, onSaved }: { vlan: Vlan | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(vlan?.name ?? "");
  const [tag, setTag] = useState(vlan ? String(vlan.tag) : "");
  const [description, setDescription] = useState(vlan?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const payload = { name: name.trim(), tag: Number(tag), description: description.trim() || null };
    try {
      if (vlan) await api.patch(`/vlans/${vlan.id}`, payload);
      else await api.post("/vlans", payload);
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={vlan ? `VLAN bearbeiten: ${vlan.name}` : "VLAN anlegen"} onClose={onClose} size="sm">
      <form className="form" onSubmit={submit}>
        <label className="field">
          <span>Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="DMZ" required />
        </label>
        <label className="field">
          <span>VLAN-Tag (1–4094)</span>
          <input
            className="input"
            type="number"
            min={1}
            max={4094}
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>Beschreibung</span>
          <textarea
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="z. B. Webserver, öffentlich erreichbar"
          />
        </label>
        {error && <Notice kind="error">{error}</Notice>}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Abbrechen
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {vlan ? "Speichern" : "Anlegen"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function VlansAdminPage() {
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Vlan | "new" | null>(null);
  const [deleting, setDeleting] = useState<Vlan | null>(null);

  const load = useCallback(async () => {
    try {
      const [vlansRes, devicesRes] = await Promise.all([api.get<Vlan[]>("/vlans"), api.get<Device[]>("/devices")]);
      setVlans(vlansRes.data);
      setDevices(devicesRes.data);
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err, "VLANs konnten nicht geladen werden."));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const deviceCount = (vlanId: number) => devices.filter((d) => d.vlan_id === vlanId).length;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>VLANs</h1>
          <p>Gruppieren die Geräte in der Übersicht - so, wie dein Netz segmentiert ist.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>
          <Icon name="plus" />
          VLAN anlegen
        </button>
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      <section className="card">
        {vlans.length === 0 ? (
          <div className="empty">Noch keine VLANs.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Tag</th>
                  <th>Name</th>
                  <th>Beschreibung</th>
                  <th>Geräte</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {vlans.map((vlan) => (
                  <tr key={vlan.id}>
                    <td className="num">{vlan.tag}</td>
                    <td>{vlan.name}</td>
                    <td className="muted">{vlan.description || "–"}</td>
                    <td className="num">{deviceCount(vlan.id)}</td>
                    <td className="actions">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon"
                        onClick={() => setEditing(vlan)}
                        aria-label={`${vlan.name} bearbeiten`}
                      >
                        <Icon name="edit" size={14} />
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon btn-danger"
                        onClick={() => setDeleting(vlan)}
                        aria-label={`${vlan.name} löschen`}
                      >
                        <Icon name="trash" size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {editing && (
        <VlanDialog vlan={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={load} />
      )}
      {deleting && (
        <ConfirmDialog
          title="VLAN löschen"
          message={
            <>
              VLAN <b>{deleting.name}</b> löschen?
              {deviceCount(deleting.id) > 0 &&
                ` Die ${deviceCount(deleting.id)} Geräte darin bleiben erhalten und stehen danach unter „Ohne VLAN“.`}
            </>
          }
          onConfirm={async () => {
            await api.delete(`/vlans/${deleting.id}`);
            await load();
          }}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
