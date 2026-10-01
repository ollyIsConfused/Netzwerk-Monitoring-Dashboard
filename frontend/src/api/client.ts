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
    if (error.response?.status === 401) {
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

export type UserRole = "admin" | "operator" | "viewer";

export type DeviceType = "switch" | "router" | "dns_server" | "webserver" | "nas" | "other";

export type MetricStatus = "ok" | "warning" | "critical" | "unknown";

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
