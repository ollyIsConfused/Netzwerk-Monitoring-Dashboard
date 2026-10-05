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

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Nur eine abgelaufene/ungueltige Sitzung fuehrt zur Login-Seite - nicht der
    // fehlgeschlagene Login-Versuch selbst (der zeigt seine Meldung im Formular)
    const isLoginRequest = String(error.config?.url ?? "").endsWith("/auth/login");
    if (error.response?.status === 401 && !isLoginRequest) {
      localStorage.removeItem("token");
      localStorage.removeItem("role");
      localStorage.removeItem("username");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
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
  metric_name: "Metrik",
  consecutive_breaches_required: "Messungen bis Alarm",
};

export type UserRole = "admin" | "operator" | "viewer";

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  operator: "Operator",
  viewer: "Betrachter",
};

export type DeviceType = "switch" | "router" | "dns_server" | "webserver" | "nas" | "other";

export const DEVICE_TYPE_LABELS: Record<DeviceType, string> = {
  switch: "Switch",
  router: "Router",
  dns_server: "DNS-Server",
  webserver: "Webserver",
  nas: "NAS",
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
}

export interface Vlan {
  id: number;
  name: string;
  tag: number;
  description: string | null;
}

export interface Device {
  id: number;
  name: string;
  ip_address: string;
  device_type: DeviceType;
  vlan_id: number | null;
  is_active: boolean;
  snmp_enabled: boolean;
  agent_enabled: boolean;
}

export interface DeviceConfig extends Device {
  snmp_community: string | null;
  snmp_version: string;
  snmp_port: number;
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
  reachable: boolean | null;
  overall_status: MetricStatus;
  latest_metrics: Record<string, number>;
  last_seen: string | null;
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
  };
  if (known[metricName]) return known[metricName];
  const iface = /^if(\d+)_(in|out)_bps$/.exec(metricName);
  if (iface) {
    return { label: `Interface ${iface[1]} ${iface[2] === "in" ? "eingehend" : "ausgehend"}`, unit: "bit/s" };
  }
  return { label: metricName, unit: "" };
}

/** Rohzaehler (ifX_in_octets) sind fortlaufende Summen und als Diagramm nicht aussagekraeftig. */
export function isChartableMetric(metricName: string): boolean {
  return !/_octets$/.test(metricName);
}

export function formatMetricValue(metricName: string, value: number): string {
  if (metricName === "reachable") return value >= 1 ? "erreichbar" : "nicht erreichbar";
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
