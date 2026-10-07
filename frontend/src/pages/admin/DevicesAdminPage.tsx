import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import {
  api,
  apiErrorMessage,
  Device,
  DeviceConfig,
  DeviceType,
  DEVICE_TYPE_LABELS,
  describeDeviceVlans,
  PortMode,
  SNMP_AUTH_PROTOCOLS,
  SNMP_PRIV_PROTOCOLS,
  SnmpVersion,
  Vlan,
} from "../../api/client";
import { Icon } from "../../components/Icon";
import { ConfirmDialog, Modal, Notice } from "../../components/Modal";

interface DeviceForm {
  name: string;
  ip_address: string;
  device_type: DeviceType;
  port_mode: PortMode;
  /** Access: das VLAN, Trunk: das native (ungetaggte) VLAN */
  vlan_id: string;
  tagged_vlan_ids: number[];
  /** Adresse des Geraets je getaggtem VLAN (optional), z. B. das Gateway beim Router */
  vlan_addresses: Record<number, string>;
  is_active: boolean;
  snmp_enabled: boolean;
  snmp_community: string;
  snmp_version: SnmpVersion;
  snmp_port: string;
  snmp_interfaces: string;
  snmp_v3_user: string;
  snmp_v3_auth_protocol: string;
  snmp_v3_auth_password: string;
  /** Leer = keine Verschluesselung, nur Anmeldung */
  snmp_v3_priv_protocol: string;
  snmp_v3_priv_password: string;
  agent_enabled: boolean;
  agent_token: string;
}

const EMPTY_FORM: DeviceForm = {
  name: "",
  ip_address: "",
  device_type: "other",
  port_mode: "access",
  vlan_id: "",
  tagged_vlan_ids: [],
  vlan_addresses: {},
  is_active: true,
  snmp_enabled: false,
  snmp_community: "",
  // Neue Geraete: v3 vorgeschlagen, v1/v2c bleiben waehlbar
  snmp_version: "3",
  snmp_port: "161",
  snmp_interfaces: "",
  snmp_v3_user: "",
  snmp_v3_auth_protocol: "sha",
  snmp_v3_auth_password: "",
  snmp_v3_priv_protocol: "aes",
  snmp_v3_priv_password: "",
  agent_enabled: false,
  agent_token: "",
};

// Mindestlaenge fuer SNMP-v3-Passwoerter (RFC 3414), wie im Backend
const SNMP_V3_MIN_PASSWORD = 8;

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
          port_mode: data.port_mode,
          vlan_id: data.vlan_id === null ? "" : String(data.vlan_id),
          tagged_vlan_ids: data.tagged_vlan_ids,
          vlan_addresses: Object.fromEntries(data.vlan_addresses.map((entry) => [entry.vlan_id, entry.ip_address])),
          is_active: data.is_active,
          snmp_enabled: data.snmp_enabled,
          snmp_community: data.snmp_community ?? "",
          snmp_version: data.snmp_version,
          snmp_port: String(data.snmp_port),
          snmp_interfaces: data.snmp_interfaces ?? "",
          snmp_v3_user: data.snmp_v3_user ?? "",
          snmp_v3_auth_protocol: data.snmp_v3_auth_protocol ?? "sha",
          snmp_v3_auth_password: data.snmp_v3_auth_password ?? "",
          // Gespeichertes v3-Geraet ohne Verfahren = bewusst ohne Verschluesselung
          snmp_v3_priv_protocol: data.snmp_v3_priv_protocol ?? (data.snmp_v3_user ? "" : "aes"),
          snmp_v3_priv_password: data.snmp_v3_priv_password ?? "",
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

  function setVlan(value: string) {
    // Das native VLAN laeuft ungetaggt und kann nicht gleichzeitig getaggt sein
    setForm((prev) => ({
      ...prev,
      vlan_id: value,
      tagged_vlan_ids: prev.tagged_vlan_ids.filter((id) => String(id) !== value),
    }));
  }

  function toggleTagged(vlanId: number, checked: boolean) {
    setForm((prev) => ({
      ...prev,
      tagged_vlan_ids: checked
        ? [...prev.tagged_vlan_ids, vlanId]
        : prev.tagged_vlan_ids.filter((id) => id !== vlanId),
    }));
  }

  function setVlanAddress(vlanId: number, value: string) {
    setForm((prev) => ({ ...prev, vlan_addresses: { ...prev.vlan_addresses, [vlanId]: value } }));
  }

  const isTrunk = form.port_mode === "trunk";
  const isV3 = form.snmp_version === "3";
  const [showSecrets, setShowSecrets] = useState(false);
  const taggedVlans = vlans.filter((vlan) => form.tagged_vlan_ids.includes(vlan.id));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (isTrunk && form.tagged_vlan_ids.length === 0) {
      setError("Wähle mindestens ein getaggtes VLAN - mit nur einem VLAN ist es ein Access-Port.");
      return;
    }
    if (form.snmp_enabled && !isV3 && !form.snmp_community.trim()) {
      setError("Für SNMP v1/v2c wird eine Community benötigt.");
      return;
    }
    if (form.snmp_enabled && isV3) {
      if (!form.snmp_v3_user.trim()) {
        setError("SNMP v3: Benutzername fehlt (genau wie am Gerät, Groß-/Kleinschreibung zählt).");
        return;
      }
      if (form.snmp_v3_auth_password.trim().length < SNMP_V3_MIN_PASSWORD) {
        setError(`SNMP v3: Das Auth-Passwort braucht mindestens ${SNMP_V3_MIN_PASSWORD} Zeichen.`);
        return;
      }
      if (form.snmp_v3_priv_protocol && form.snmp_v3_priv_password.trim().length < SNMP_V3_MIN_PASSWORD) {
        setError(`SNMP v3: Das Privacy-Passwort braucht mindestens ${SNMP_V3_MIN_PASSWORD} Zeichen.`);
        return;
      }
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
      port_mode: form.port_mode,
      vlan_id: form.vlan_id === "" ? null : Number(form.vlan_id),
      tagged_vlan_ids: isTrunk ? form.tagged_vlan_ids : [],
      vlan_addresses: isTrunk
        ? form.tagged_vlan_ids
            .map((id) => ({ vlan_id: id, ip_address: (form.vlan_addresses[id] ?? "").trim() }))
            .filter((entry) => entry.ip_address !== "")
        : [],
      is_active: form.is_active,
      snmp_enabled: form.snmp_enabled,
      // Nicht genutzte Zugangsdaten nicht weiter speichern
      snmp_community: isV3 ? null : form.snmp_community.trim() || null,
      snmp_version: form.snmp_version,
      snmp_port: Number(form.snmp_port) || 161,
      snmp_interfaces: form.snmp_interfaces.trim() || null,
      snmp_v3_user: isV3 ? form.snmp_v3_user.trim() || null : null,
      snmp_v3_auth_protocol: isV3 ? form.snmp_v3_auth_protocol : null,
      snmp_v3_auth_password: isV3 ? form.snmp_v3_auth_password || null : null,
      snmp_v3_priv_protocol: isV3 ? form.snmp_v3_priv_protocol || null : null,
      snmp_v3_priv_password: isV3 && form.snmp_v3_priv_protocol ? form.snmp_v3_priv_password || null : null,
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
              <span>{isTrunk ? "Haupt-IP (Verwaltung) oder Hostname" : "IP-Adresse oder Hostname"}</span>
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
              <span>Anschluss am Switch</span>
              <select
                className="select"
                value={form.port_mode}
                onChange={(e) => set("port_mode", e.target.value as PortMode)}
              >
                <option value="access">Access-Port (ein VLAN)</option>
                <option value="trunk">Trunk-Port (mehrere VLANs)</option>
              </select>
            </label>
            <label className="field span-2">
              <span>{isTrunk ? "Natives VLAN (ungetaggt)" : "VLAN"}</span>
              <select className="select" value={form.vlan_id} onChange={(e) => setVlan(e.target.value)}>
                <option value="">– keins –</option>
                {vlans.map((vlan) => (
                  <option key={vlan.id} value={vlan.id}>
                    {vlan.name} (VLAN {vlan.tag})
                  </option>
                ))}
              </select>
              {isTrunk && <small>Läuft ohne Tag über den Port, oft VLAN 1. Leer lassen, wenn es keins gibt.</small>}
            </label>
            {isTrunk && (
              <div className="field span-2">
                <span>Getaggte VLANs</span>
                {vlans.length === 0 ? (
                  <small>Noch keine VLANs - zuerst unter „VLANs“ anlegen.</small>
                ) : (
                  <div className="check-grid" role="group" aria-label="Getaggte VLANs">
                    {vlans.map((vlan) => {
                      const isNative = String(vlan.id) === form.vlan_id;
                      return (
                        <label key={vlan.id} className="checkbox">
                          <input
                            type="checkbox"
                            disabled={isNative}
                            checked={!isNative && form.tagged_vlan_ids.includes(vlan.id)}
                            onChange={(e) => toggleTagged(vlan.id, e.target.checked)}
                          />
                          {vlan.name} ({vlan.tag})
                          {isNative && <span className="muted">· nativ</span>}
                        </label>
                      );
                    })}
                  </div>
                )}
                <small>Zum Beispiel der Router-Pi am Trunk: nativ VLAN 1, getaggt 20, 30 und 50.</small>
                {taggedVlans.length > 0 && (
                  <div className="vlan-address-list">
                    <span className="vlan-address-title">Adresse des Geräts in den getaggten VLANs (optional)</span>
                    {taggedVlans.map((vlan) => (
                      <label key={vlan.id} className="vlan-address-row">
                        <span>
                          {vlan.name} (VLAN {vlan.tag})
                        </span>
                        <input
                          className="input mono"
                          value={form.vlan_addresses[vlan.id] ?? ""}
                          onChange={(e) => setVlanAddress(vlan.id, e.target.value)}
                          placeholder={vlan.tag <= 255 ? `z. B. 192.168.${vlan.tag}.1` : "IP-Adresse"}
                          aria-label={`Adresse in VLAN ${vlan.tag}`}
                        />
                      </label>
                    ))}
                    <small>
                      Beim Router-Pi seine Gateway-Adresse im jeweiligen VLAN. Angepingt und per SNMP abgefragt wird
                      weiter die Haupt-IP oben.
                    </small>
                  </div>
                )}
              </div>
            )}
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
                  <span>Version</span>
                  <select
                    className="select"
                    value={form.snmp_version}
                    onChange={(e) => set("snmp_version", e.target.value as SnmpVersion)}
                  >
                    <option value="3">v3 (empfohlen)</option>
                    <option value="2c">v2c (Community)</option>
                    <option value="1">v1 (Community)</option>
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
                {!isV3 && (
                  <label className="field span-2">
                    <span>Community</span>
                    <input
                      className="input"
                      type={showSecrets ? "text" : "password"}
                      value={form.snmp_community}
                      onChange={(e) => set("snmp_community", e.target.value)}
                      autoComplete="off"
                    />
                  </label>
                )}
                {isV3 && (
                  <>
                    <label className="field">
                      <span>Benutzer</span>
                      <input
                        className="input"
                        value={form.snmp_v3_user}
                        onChange={(e) => set("snmp_v3_user", e.target.value)}
                        autoComplete="off"
                        maxLength={32}
                      />
                    </label>
                    <label className="field">
                      <span>Anmeldung (Auth)</span>
                      <select
                        className="select"
                        value={form.snmp_v3_auth_protocol}
                        onChange={(e) => set("snmp_v3_auth_protocol", e.target.value)}
                      >
                        {Object.entries(SNMP_AUTH_PROTOCOLS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field span-2">
                      <span>Auth-Passwort</span>
                      <input
                        className="input"
                        type={showSecrets ? "text" : "password"}
                        value={form.snmp_v3_auth_password}
                        onChange={(e) => set("snmp_v3_auth_password", e.target.value)}
                        autoComplete="new-password"
                        maxLength={64}
                      />
                    </label>
                    <label className="field">
                      <span>Verschlüsselung (Privacy)</span>
                      <select
                        className="select"
                        value={form.snmp_v3_priv_protocol}
                        onChange={(e) => set("snmp_v3_priv_protocol", e.target.value)}
                      >
                        {Object.entries(SNMP_PRIV_PROTOCOLS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    {form.snmp_v3_priv_protocol ? (
                      <label className="field">
                        <span>Privacy-Passwort</span>
                        <input
                          className="input"
                          type={showSecrets ? "text" : "password"}
                          value={form.snmp_v3_priv_password}
                          onChange={(e) => set("snmp_v3_priv_password", e.target.value)}
                          autoComplete="new-password"
                          maxLength={64}
                        />
                      </label>
                    ) : (
                      <div className="field" />
                    )}
                    <small className="span-2 field-hint">
                      Genau dieselben Werte wie am Gerät eintragen (TP-Link: SNMP → SNMP v3 → User Config). DES
                      nur, wenn das Gerät kein AES kann - der TL-SG3210 zum Beispiel bietet nur SHA und DES.
                    </small>
                  </>
                )}
                <label className="checkbox span-2">
                  <input type="checkbox" checked={showSecrets} onChange={(e) => setShowSecrets(e.target.checked)} />
                  {isV3 ? "Passwörter anzeigen" : "Community anzeigen"}
                </label>
                <label className="field span-2">
                  <span>Interface-Indizes</span>
                  <input
                    className="input mono"
                    value={form.snmp_interfaces}
                    onChange={(e) => set("snmp_interfaces", e.target.value)}
                    placeholder="1,2,3"
                  />
                  <small>Nummern aus snmpwalk, durch Komma getrennt (siehe Anleitung, Abschnitt 2.3).</small>
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
                <small>
                  Auf dem Gerät einrichten mit <code>sudo ./deploy/agent/install-agent.sh</code> - das Skript fragt
                  nach der Backend-Adresse und diesem Token und schickt dann jede Minute CPU, Arbeitsspeicher,
                  Festplatte und Temperatur.
                </small>
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
                    <td>
                      <div className="cell-stack">
                        <span className="mono">{device.ip_address}</span>
                        {device.vlan_addresses.length > 0 && (
                          <span className="muted mono small-text">
                            {device.vlan_addresses.map((entry) => entry.ip_address).join(", ")}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>{DEVICE_TYPE_LABELS[device.device_type]}</td>
                    <td>
                      {device.port_mode === "trunk" && <span className="badge badge-plain badge-inline">Trunk</span>}
                      {describeDeviceVlans(device, vlans)}
                    </td>
                    <td className="muted">
                      {[
                        "Ping",
                        device.snmp_enabled && (device.snmp_version === "3" ? "SNMP v3" : "SNMP"),
                        device.agent_enabled && "Agent",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
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
