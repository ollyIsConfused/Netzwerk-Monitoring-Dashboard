import axios from "axios";

export const api = axios.create({ baseURL: "/api" });

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
