import axios from "axios";

// Default "/api" relies on a reverse proxy in front of frontend+backend rewriting
// that prefix (see docker-compose/nginx.conf). Set VITE_API_BASE_URL at build time
// when frontend and backend are deployed on different hosts/ports without a
// shared proxy path (e.g. frontend served via pm2, backend on its own port).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

export const api = axios.create({ baseURL: API_BASE_URL });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Muss exakt dem Text im Backend entsprechen (backend/app/security.py)
export const PASSWORD_CHANGE_REQUIRED = "Bitte zuerst ein eigenes Passwort festlegen";

export const SESSION_KEYS = ["token", "role", "username", "mustChangePassword"] as const;

// Seitenleisten-Zaehler (Alarme, Passwort-Anfragen) sofort statt erst beim naechsten Abruf aktualisieren
const COUNTS_CHANGED_EVENT = "monitoring:counts-changed";

export function notifyCountsChanged() {
  window.dispatchEvent(new Event(COUNTS_CHANGED_EVENT));
}

export function onCountsChanged(handler: () => void): () => void {
  window.addEventListener(COUNTS_CHANGED_EVENT, handler);
  return () => window.removeEventListener(COUNTS_CHANGED_EVENT, handler);
}

export function clearSession() {
  SESSION_KEYS.forEach((key) => localStorage.removeItem(key));
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Nur eine abgelaufene/ungueltige Sitzung fuehrt zur Login-Seite - nicht der
    // fehlgeschlagene Login-Versuch selbst (der zeigt seine Meldung im Formular)
    const isLoginRequest = String(error.config?.url ?? "").endsWith("/auth/login");
    if (error.response?.status === 401 && !isLoginRequest) {
      clearSession();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    // Admin hat in der Zwischenzeit ein neues Passwort gesetzt: erst eigenes Passwort festlegen
    if (error.response?.status === 403 && error.response.data?.detail === PASSWORD_CHANGE_REQUIRED) {
      if (localStorage.getItem("mustChangePassword") !== "1") {
        localStorage.setItem("mustChangePassword", "1");
        window.location.href = "/";
      }
    }
    return Promise.reject(error);
  },
);

/** Macht aus einer Axios-/FastAPI-Fehlerantwort eine lesbare deutsche Meldung. */
export function apiErrorMessage(error: unknown, fallback = "Aktion fehlgeschlagen."): string {
  if (!axios.isAxiosError(error)) return fallback;
  if (!error.response) return "Server nicht erreichbar - läuft das Backend?";
  const detail = error.response.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    // Pydantic-Validierungsfehler: [{loc: [..., "feld"], msg: "..."}]
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : undefined;
        const message = (item.msg ?? "ungültig").replace(/^Value error, /, "");
        return field ? `${FIELD_LABELS[String(field)] ?? field}: ${message}` : message;
      })
      .join(" · ");
  }
  return fallback;
}

const FIELD_LABELS: Record<string, string> = {
  username: "Benutzername",
  email: "E-Mail",
  password: "Passwort",
  new_password: "Neues Passwort",
  current_password: "Aktuelles Passwort",
  name: "Name",
  tag: "VLAN-Tag",
  ip_address: "IP-Adresse",
  snmp_port: "SNMP-Port",
  snmp_v3_user: "SNMP-Benutzer",
  snmp_v3_auth_password: "Auth-Passwort",
  snmp_v3_priv_password: "Privacy-Passwort",
  metric_name: "Metrik",
  consecutive_breaches_required: "Messungen bis Alarm",
};

export type UserRole = "admin" | "operator" | "viewer";

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  operator: "Operator",
  viewer: "Betrachter",
};

export type DeviceType =
  | "switch"
  | "router"
  | "gateway"
  | "dns_server"
  | "dhcp_server"
  | "webserver"
  | "nas"
  | "workstation"
  | "other";

// Reihenfolge = Reihenfolge in der Auswahl beim Anlegen
export const DEVICE_TYPE_LABELS: Record<DeviceType, string> = {
  switch: "Switch",
  router: "Router",
  gateway: "Gateway",
  dns_server: "DNS-Server",
  dhcp_server: "DHCP-Server",
  webserver: "Webserver",
  nas: "NAS",
  workstation: "Workstation",
  other: "Sonstiges",
};

export type MetricStatus = "ok" | "warning" | "critical" | "unknown";

export interface User {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  must_change_password: boolean;
  password_reset_requested_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  role: UserRole;
  username: string;
  must_change_password: boolean;
}

export interface TemporaryPasswordResult {
  email: string;
  email_sent: boolean;
  temporary_password: string | null;
}

export interface Vlan {
  id: number;
  name: string;
  tag: number;
  description: string | null;
}

/** access = Geraet haengt in genau einem VLAN; trunk = Port fuehrt mehrere VLANs getaggt */
export type PortMode = "access" | "trunk";

/** Adresse eines Trunk-Geraets in einem getaggten VLAN, beim Router z. B. das Gateway */
export interface VlanAddress {
  vlan_id: number;
  ip_address: string;
}

export interface Device {
  id: number;
  name: string;
  /** Haupt-/Verwaltungsadresse - die wird angepingt und per SNMP abgefragt */
  ip_address: string;
  device_type: DeviceType;
  port_mode: PortMode;
  /** Access: das VLAN des Geraets. Trunk: das native (ungetaggte) VLAN */
  vlan_id: number | null;
  tagged_vlan_ids: number[];
  vlan_addresses: VlanAddress[];
  is_active: boolean;
  snmp_enabled: boolean;
  snmp_version: SnmpVersion;
  agent_enabled: boolean;
}

/** Alle VLANs, in denen ein Geraet vorkommt: das (native) VLAN und bei Trunks die getaggten. */
export function deviceVlanIds(device: Device): number[] {
  const ids = device.vlan_id === null ? [] : [device.vlan_id];
  return device.port_mode === "trunk" ? [...ids, ...device.tagged_vlan_ids] : ids;
}

/** Adresse des Geraets in einem VLAN; ohne eigene Adresse dort die Haupt-IP. */
export function deviceAddressInVlan(device: Device, vlanId: number | null): string {
  return device.vlan_addresses.find((entry) => entry.vlan_id === vlanId)?.ip_address ?? device.ip_address;
}

/** Kurzbeschreibung fuer Tabellen, z. B. "Webserver (30)" oder "nativ 1 · getaggt 20, 30, 50". */
export function describeDeviceVlans(device: Device, vlans: Vlan[]): string {
  const byId = new Map(vlans.map((vlan) => [vlan.id, vlan]));
  if (device.port_mode !== "trunk") {
    const vlan = device.vlan_id === null ? undefined : byId.get(device.vlan_id);
    return vlan ? `${vlan.name} (${vlan.tag})` : "–";
  }
  const native = device.vlan_id === null ? undefined : byId.get(device.vlan_id);
  const tagged = device.tagged_vlan_ids
    .map((id) => byId.get(id)?.tag)
    .filter((tag): tag is number => tag !== undefined);
  return [native ? `nativ ${native.tag}` : null, tagged.length ? `getaggt ${tagged.join(", ")}` : null]
    .filter(Boolean)
    .join(" · ");
}

export type SnmpVersion = "1" | "2c" | "3";

export const SNMP_AUTH_PROTOCOLS: Record<string, string> = {
  sha: "SHA",
  sha256: "SHA-256",
  sha512: "SHA-512",
  sha224: "SHA-224",
  sha384: "SHA-384",
  md5: "MD5 (veraltet)",
};

/** Leerer Schluessel = keine Verschluesselung, nur Anmeldung */
export const SNMP_PRIV_PROTOCOLS: Record<string, string> = {
  aes: "AES-128",
  des: "DES (schwach)",
  "": "keine - nur Anmeldung",
};

export interface DeviceConfig extends Device {
  snmp_community: string | null;
  snmp_port: number;
  snmp_v3_user: string | null;
  snmp_v3_auth_protocol: string | null;
  snmp_v3_auth_password: string | null;
  snmp_v3_priv_protocol: string | null;
  snmp_v3_priv_password: string | null;
  snmp_interfaces: string | null;
  agent_token: string | null;
}

export interface ThresholdRule {
  id: number;
  metric_name: string;
  warning_max: number | null;
  critical_max: number | null;
  warning_min: number | null;
  critical_min: number | null;
  consecutive_breaches_required: number;
}

export interface DeviceStatus {
  device: Device;
  /** Letzter bekannter Wert - bei stale nicht mehr aktuell */
  reachable: boolean | null;
  overall_status: MetricStatus;
  latest_metrics: Record<string, number>;
  last_seen: string | null;
  /** Vom Collector kommen seit einiger Zeit keine neuen Messwerte */
  stale: boolean;
  agent_last_seen: string | null;
  agent_stale: boolean;
}

export interface MetricSamplePoint {
  metric_name: string;
  value: number;
  status: MetricStatus;
  timestamp: string;
}

export type AlertLevel = "warning" | "critical" | "recovered";

export interface AlertEvent {
  id: number;
  device_id: number;
  metric_name: string;
  level: AlertLevel;
  message: string;
  value: number | null;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

/** Anzeigename und Einheit je Metrik; Interface-Metriken (if3_in_bps) werden erkannt. */
export function metricInfo(metricName: string): { label: string; unit: string } {
  const known: Record<string, { label: string; unit: string }> = {
    reachable: { label: "Erreichbarkeit", unit: "" },
    latency_ms: { label: "Antwortzeit", unit: "ms" },
    packet_loss_pct: { label: "Paketverlust", unit: "%" },
    cpu_pct: { label: "CPU-Last", unit: "%" },
    disk_pct: { label: "Festplattenbelegung", unit: "%" },
    mem_pct: { label: "Arbeitsspeicher", unit: "%" },
    temp_c: { label: "Temperatur", unit: "°C" },
  };
  if (known[metricName]) return known[metricName];
  const iface = /^if(\d+)_(in|out)_bps$/.exec(metricName);
  if (iface) {
    return { label: `Interface ${iface[1]} ${iface[2] === "in" ? "eingehend" : "ausgehend"}`, unit: "bit/s" };
  }
  const operStatus = /^if(\d+)_oper_status$/.exec(metricName);
  if (operStatus) return { label: `Interface ${operStatus[1]} Status`, unit: "" };
  // Weitere Laufwerke vom Agenten, z. B. disk_mnt_storage_pct fuer /mnt/storage
  const disk = /^disk_(.+)_pct$/.exec(metricName);
  if (disk) return { label: `Festplatte /${disk[1].replace(/_/g, "/")}`, unit: "%" };
  return { label: metricName, unit: "" };
}

/** Rohzaehler (ifX_in_octets) sind fortlaufende Summen und als Diagramm nicht aussagekraeftig. */
export function isChartableMetric(metricName: string): boolean {
  return !/_octets$/.test(metricName);
}

export function formatMetricValue(metricName: string, value: number): string {
  if (metricName === "reachable") return value >= 1 ? "erreichbar" : "nicht erreichbar";
  // SNMP ifOperStatus: 1 = up, 2 = down, alles andere (testing, dormant ...) als Zahl
  if (/_oper_status$/.test(metricName) && (value === 1 || value === 2)) return value === 1 ? "an (up)" : "aus (down)";
  const { unit } = metricInfo(metricName);
  if (unit === "bit/s") return formatBitrate(value);
  const rounded = Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(1);
  return `${rounded.replace(".", ",")}${unit ? ` ${unit}` : ""}`;
}

export function formatBitrate(bps: number): string {
  const units = ["bit/s", "kbit/s", "Mbit/s", "Gbit/s"];
  let value = bps;
  let index = 0;
  while (value >= 1000 && index < units.length - 1) {
    value /= 1000;
    index += 1;
  }
  return `${value.toFixed(value >= 100 || index === 0 ? 0 : 1).replace(".", ",")} ${units[index]}`;
}

export function formatDateTime(value: string | null): string {
  if (!value) return "–";
  // Das Backend liefert UTC ohne Zeitzonen-Suffix
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  return new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" });
}

export function parseTimestamp(value: string): number {
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  return new Date(iso).getTime();
}
