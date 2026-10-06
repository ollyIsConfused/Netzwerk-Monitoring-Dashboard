import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import {
  AlertEvent,
  api,
  apiErrorMessage,
  DEVICE_TYPE_LABELS,
  deviceVlanIds,
  DeviceStatus,
  formatDateTime,
  formatMetricValue,
  MetricStatus,
  Vlan,
} from "../api/client";
import { useAuth } from "../api/AuthContext";
import { Icon } from "../components/Icon";
import { Notice } from "../components/Modal";
import { ReachableBadge, StatusBadge } from "../components/StatusBadge";

interface LiveStatus {
  [deviceId: number]: MetricStatus;
}

function StatTile({ label, value, color, hint }: { label: string; value: number; color?: string; hint?: string }) {
  return (
    <div className="card stat-tile">
      <div className="stat-label">
        {color && <span className="dot" style={{ background: color }} />}
        {label}
      </div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

function DeviceTable({ rows, liveStatus }: { rows: DeviceStatus[]; liveStatus: LiveStatus }) {
  if (rows.length === 0) return <div className="empty">Keine Geräte in diesem VLAN.</div>;
  return (
    <div className="table-wrap">
      <table className="device-table">
        <colgroup>
          <col style={{ width: "18%" }} />
          <col style={{ width: "15%" }} />
          <col style={{ width: "12%" }} />
          <col style={{ width: "13%" }} />
          <col style={{ width: "13%" }} />
          <col style={{ width: "12%" }} />
          <col style={{ width: "17%" }} />
        </colgroup>
        <thead>
          <tr>
            <th>Gerät</th>
            <th>IP-Adresse</th>
            <th>Typ</th>
            <th>Erreichbar</th>
            <th>Status</th>
            <th>Antwortzeit</th>
            <th>Zuletzt gesehen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.device.id}>
              <td>
                <Link to={`/devices/${row.device.id}`}>{row.device.name}</Link>
                {row.device.port_mode === "trunk" && (
                  <span className="badge badge-plain badge-inline-after" title="Trunk-Port: in mehreren VLANs">
                    Trunk
                  </span>
                )}
              </td>
              <td className="mono">{row.device.ip_address}</td>
              <td>{DEVICE_TYPE_LABELS[row.device.device_type]}</td>
              <td>
                <ReachableBadge reachable={row.reachable} />
              </td>
              <td>
                <StatusBadge status={liveStatus[row.device.id] ?? row.overall_status} />
              </td>
              <td className="num">
                {/* Bei offline Geraeten ist die letzte Antwortzeit veraltet */}
                {row.reachable !== false && row.latest_metrics.latency_ms !== undefined
                  ? formatMetricValue("latency_ms", row.latest_metrics.latency_ms)
                  : "–"}
              </td>
              <td className="num muted">{formatDateTime(row.last_seen)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DashboardPage() {
  const { role } = useAuth();
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [statuses, setStatuses] = useState<DeviceStatus[]>([]);
  const [activeAlerts, setActiveAlerts] = useState(0);
  const [liveStatus, setLiveStatus] = useState<LiveStatus>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [vlansRes, statusRes, alertsRes] = await Promise.all([
          api.get<Vlan[]>("/vlans"),
          api.get<DeviceStatus[]>("/devices/status"),
          api.get<AlertEvent[]>("/alerts", { params: { active_only: true } }),
        ]);
        setVlans(vlansRes.data);
        setStatuses(statusRes.data);
        setActiveAlerts(alertsRes.data.filter((a) => a.level !== "recovered").length);
        setError(null);
      } catch (err) {
        setError(apiErrorMessage(err, "Status konnte nicht geladen werden."));
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 30000); // Fallback-Refresh, falls der WebSocket abbricht
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Hinweis: der WebSocket-Endpunkt liefert nur aggregierte Status-Werte (kein JWT-Schutz in
    // diesem MVP) - siehe README, Abschnitt "Bekannte Einschränkungen" für die Produktivhärtung.
    // VITE_WS_BASE_URL analog zu VITE_API_BASE_URL für Deployments ohne gemeinsamen Reverse-Proxy.
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsBase = import.meta.env.VITE_WS_BASE_URL || `${protocol}//${window.location.host}/ws`;
    const socket = new WebSocket(`${wsBase}/status`);

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "status") {
          const next: LiveStatus = {};
          for (const entry of payload.devices) {
            next[entry.device_id] = entry.status;
          }
          setLiveStatus(next);
        }
      } catch {
        // ignore malformed messages
      }
    };

    return () => socket.close();
  }, []);

  const devicesByVlan = useMemo(() => {
    const map = new Map<number | null, DeviceStatus[]>();
    for (const status of statuses) {
      // Trunk-Geraete (z. B. der Router) erscheinen in jedem VLAN, das sie fuehren
      const vlanIds = deviceVlanIds(status.device);
      for (const key of vlanIds.length ? vlanIds : [null]) {
        if (!map.has(key)) map.set(key, []);
        map.get(key)!.push(status);
      }
    }
    return map;
  }, [statuses]);

  const counts = useMemo(() => {
    const effective = statuses.map((s) => liveStatus[s.device.id] ?? s.overall_status);
    return {
      total: statuses.length,
      online: statuses.filter((s) => s.reachable === true).length,
      offline: statuses.filter((s) => s.reachable === false).length,
      warning: effective.filter((s) => s === "warning").length,
      critical: effective.filter((s) => s === "critical").length,
    };
  }, [statuses, liveStatus]);

  const unassigned = devicesByVlan.get(null) ?? [];

  if (loading) return <p className="muted">Lade Gerätestatus…</p>;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Übersicht</h1>
          <p>Live-Status aller überwachten Geräte, gruppiert nach VLAN.</p>
        </div>
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      <div className="stat-grid">
        <StatTile label="Geräte" value={counts.total} hint="aktiv überwacht" />
        <StatTile label="Online" value={counts.online} color="var(--status-good)" />
        <StatTile label="Offline" value={counts.offline} color="var(--status-critical)" />
        <StatTile label="Mit Warnung" value={counts.warning} color="var(--status-warning)" />
        <StatTile label="Aktive Alarme" value={activeAlerts} color="var(--status-critical)" hint="nicht quittiert" />
      </div>

      {statuses.length === 0 && (
        <div className="card empty">
          <p style={{ marginTop: 0 }}>Noch keine Geräte angelegt.</p>
          {role === "admin" && (
            <Link className="btn btn-primary" to="/admin/devices" style={{ textDecoration: "none" }}>
              <Icon name="plus" />
              Erstes Gerät anlegen
            </Link>
          )}
        </div>
      )}

      {statuses.length > 0 &&
        vlans.map((vlan) => (
          <section key={vlan.id} className="card">
            <div className="card-header">
              <h2>
                {vlan.name} <span className="muted">· VLAN {vlan.tag}</span>
              </h2>
              {vlan.description && <span className="muted">{vlan.description}</span>}
            </div>
            <DeviceTable rows={devicesByVlan.get(vlan.id) ?? []} liveStatus={liveStatus} />
          </section>
        ))}

      {unassigned.length > 0 && (
        <section className="card">
          <div className="card-header">
            <h2>Ohne VLAN</h2>
          </div>
          <DeviceTable rows={unassigned} liveStatus={liveStatus} />
        </section>
      )}
    </div>
  );
}
