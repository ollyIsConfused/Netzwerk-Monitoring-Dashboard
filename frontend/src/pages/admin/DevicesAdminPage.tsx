import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  apiErrorMessage,
  Device,
  DeviceConfig,
  DeviceType,
  DEVICE_TYPE_LABELS,
  Vlan,
} from "../../api/client";
import { Icon } from "../../components/Icon";
import { ConfirmDialog, Modal, Notice } from "../../components/Modal";

interface DeviceForm {
  name: string;
  ip_address: string;
  device_type: DeviceType;
  vlan_id: string;
  is_active: boolean;
  snmp_enabled: boolean;
  snmp_community: string;
  snmp_version: string;
  snmp_port: string;
  snmp_interfaces: string;
  agent_enabled: boolean;
  agent_token: string;
}

const EMPTY_FORM: DeviceForm = {
  name: "",
  ip_address: "",
  device_type: "other",
  vlan_id: "",
  is_active: true,
  snmp_enabled: false,
  snmp_community: "",
  snmp_version: "2c",
  snmp_port: "161",
  snmp_interfaces: "",
  agent_enabled: false,
  agent_token: "",
};

function randomToken(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function DeviceDialog({
  device,
  vlans,
  onClose,
  onSaved,
}: {
  device: Device | null;
  vlans: Vlan[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<DeviceForm>(EMPTY_FORM);
  const [loaded, setLoaded] = useState(device === null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!device) return;
    // Zum Bearbeiten die volle Konfiguration (inkl. SNMP-Community) nachladen
    api
      .get<DeviceConfig>(`/devices/${device.id}/config`)
      .then(({ data }) => {
        setForm({
          name: data.name,
          ip_address: data.ip_address,
          device_type: data.device_type,
          vlan_id: data.vlan_id === null ? "" : String(data.vlan_id),
          is_active: data.is_active,
          snmp_enabled: data.snmp_enabled,
          snmp_community: data.snmp_community ?? "",
          snmp_version: data.snmp_version,
          snmp_port: String(data.snmp_port),
          snmp_interfaces: data.snmp_interfaces ?? "",
          agent_enabled: data.agent_enabled,
          agent_token: data.agent_token ?? "",
        });
        setLoaded(true);
      })
      .catch((err) => setError(apiErrorMessage(err, "Gerät konnte nicht geladen werden.")));
  }, [device]);

  function set<K extends keyof DeviceForm>(key: K, value: DeviceForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.snmp_enabled && !form.snmp_community.trim()) {
      setError("Für SNMP wird eine Community benötigt.");
      return;
    }
    if (form.agent_enabled && form.agent_token.trim().length < 16) {
      setError("Das Agent-Token muss mindestens 16 Zeichen haben - am besten „Generieren“ nutzen.");
      return;
    }
    setBusy(true);
    setError(null);
    const payload = {
      name: form.name.trim(),
      ip_address: form.ip_address.trim(),
      device_type: form.device_type,
      vlan_id: form.vlan_id === "" ? null : Number(form.vlan_id),
      is_active: form.is_active,
      snmp_enabled: form.snmp_enabled,
      snmp_community: form.snmp_community.trim() || null,
      snmp_version: form.snmp_version,
      snmp_port: Number(form.snmp_port) || 161,
      snmp_interfaces: form.snmp_interfaces.trim() || null,
      agent_enabled: form.agent_enabled,
      agent_token: form.agent_token.trim() || null,
    };
    try {
      if (device) await api.patch(`/devices/${device.id}`, payload);
      else await api.post("/devices", payload);
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={device ? `Gerät bearbeiten: ${device.name}` : "Gerät anlegen"} onClose={onClose}>
      {!loaded ? (
        error ? <Notice kind="error">{error}</Notice> : <p className="muted">Lade…</p>
      ) : (
        <form className="form" onSubmit={submit}>
          <div className="form-grid">
            <label className="field">
              <span>Name</span>
              <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required />
            </label>
            <label className="field">
              <span>IP-Adresse oder Hostname</span>
              <input
                className="input mono"
                value={form.ip_address}
                onChange={(e) => set("ip_address", e.target.value)}
                placeholder="192.168.30.15"
                required
              />
            </label>
            <label className="field">
              <span>Typ</span>
              <select
                className="select"
                value={form.device_type}
                onChange={(e) => set("device_type", e.target.value as DeviceType)}
              >
                {Object.entries(DEVICE_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>VLAN</span>
              <select className="select" value={form.vlan_id} onChange={(e) => set("vlan_id", e.target.value)}>
                <option value="">– keins –</option>
                {vlans.map((vlan) => (
                  <option key={vlan.id} value={vlan.id}>
                    {vlan.name} (VLAN {vlan.tag})
                  </option>
                ))}
              </select>
            </label>
            <label className="checkbox span-2">
              <input type="checkbox" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} />
              Überwachung aktiv (aus = Gerät wird nicht gepollt)
            </label>
          </div>

          <fieldset className="fieldset">
            <legend>SNMP (Bandbreite von Switch/Router)</legend>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.snmp_enabled}
                onChange={(e) => set("snmp_enabled", e.target.checked)}
              />
              SNMP-Abfrage aktivieren
            </label>
            {form.snmp_enabled && (
              <div className="form-grid">
                <label className="field">
                  <span>Community</span>
                  <input
                    className="input"
                    value={form.snmp_community}
                    onChange={(e) => set("snmp_community", e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <label className="field">
                  <span>Version</span>
                  <select
                    className="select"
                    value={form.snmp_version}
                    onChange={(e) => set("snmp_version", e.target.value)}
                  >
                    <option value="1">v1</option>
                    <option value="2c">v2c</option>
                  </select>
                </label>
                <label className="field">
                  <span>Port</span>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={65535}
                    value={form.snmp_port}
                    onChange={(e) => set("snmp_port", e.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Interface-Indizes</span>
                  <input
                    className="input mono"
                    value={form.snmp_interfaces}
                    onChange={(e) => set("snmp_interfaces", e.target.value)}
                    placeholder="1,2,3"
                  />
                </label>
              </div>
            )}
          </fieldset>

          <fieldset className="fieldset">
            <legend>Eigener Agent (z. B. CPU/Platte von NAS oder Webserver)</legend>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.agent_enabled}
                onChange={(e) => set("agent_enabled", e.target.checked)}
              />
              Agent darf Messwerte an /agent/push senden
            </label>
            {form.agent_enabled && (
              <label className="field">
                <span>Agent-Token</span>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    className="input mono"
                    value={form.agent_token}
                    onChange={(e) => set("agent_token", e.target.value)}
                    autoComplete="off"
                  />
                  <button type="button" className="btn" onClick={() => set("agent_token", randomToken())}>
                    <Icon name="key" size={14} />
                    Generieren
                  </button>
                </div>
              </label>
            )}
          </fieldset>

          {error && <Notice kind="error">{error}</Notice>}
          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose}>
              Abbrechen
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {device ? "Speichern" : "Anlegen"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function DevicesAdminPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Device | "new" | null>(null);
  const [deleting, setDeleting] = useState<Device | null>(null);

  const load = useCallback(async () => {
    try {
      const [devicesRes, vlansRes] = await Promise.all([api.get<Device[]>("/devices"), api.get<Vlan[]>("/vlans")]);
      setDevices(devicesRes.data);
      setVlans(vlansRes.data);
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err, "Geräte konnten nicht geladen werden."));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const vlanName = (id: number | null) => {
    const vlan = vlans.find((v) => v.id === id);
    return vlan ? `${vlan.name} (${vlan.tag})` : "–";
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Geräte</h1>
          <p>Was der Collector überwacht. Neue Geräte erscheinen nach dem nächsten Poll in der Übersicht.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>
          <Icon name="plus" />
          Gerät anlegen
        </button>
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      <section className="card">
        {devices.length === 0 ? (
          <div className="empty">Noch keine Geräte. Lege zuerst die VLANs an, dann die Geräte.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>IP-Adresse</th>
                  <th>Typ</th>
                  <th>VLAN</th>
                  <th>Abfrage</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {devices.map((device) => (
                  <tr key={device.id}>
                    <td>
                      <Link to={`/devices/${device.id}`}>{device.name}</Link>
                      {!device.is_active && (
                        <span className="badge badge-plain" style={{ marginLeft: 8 }}>
                          pausiert
                        </span>
                      )}
                    </td>
                    <td className="mono">{device.ip_address}</td>
                    <td>{DEVICE_TYPE_LABELS[device.device_type]}</td>
                    <td>{vlanName(device.vlan_id)}</td>
                    <td className="muted">
                      {["Ping", device.snmp_enabled && "SNMP", device.agent_enabled && "Agent"].filter(Boolean).join(" · ")}
                    </td>
                    <td className="actions">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon"
                        onClick={() => setEditing(device)}
                        aria-label={`${device.name} bearbeiten`}
                      >
                        <Icon name="edit" size={14} />
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon btn-danger"
                        onClick={() => setDeleting(device)}
                        aria-label={`${device.name} löschen`}
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
        <DeviceDialog
          device={editing === "new" ? null : editing}
          vlans={vlans}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Gerät löschen"
          message={
            <>
              <b>{deleting.name}</b> mit allen Messwerten, Schwellenwerten und Alarmen löschen? Das lässt sich nicht
              rückgängig machen. Zum vorübergehenden Abschalten lieber „Überwachung aktiv“ ausschalten.
            </>
          }
          onConfirm={async () => {
            await api.delete(`/devices/${deleting.id}`);
            await load();
          }}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
