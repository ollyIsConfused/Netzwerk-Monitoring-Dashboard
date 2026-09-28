import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, DeviceStatus, MetricStatus, Vlan } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";

interface LiveStatus {
  [deviceId: number]: MetricStatus;
}

export function DashboardPage() {
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [statuses, setStatuses] = useState<DeviceStatus[]>([]);
  const [liveStatus, setLiveStatus] = useState<LiveStatus>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const [vlansRes, statusRes] = await Promise.all([
        api.get<Vlan[]>("/vlans"),
        api.get<DeviceStatus[]>("/devices/status"),
      ]);
      setVlans(vlansRes.data);
      setStatuses(statusRes.data);
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 30000); // Fallback-Refresh, falls der WebSocket abbricht
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Hinweis: der WebSocket-Endpunkt liefert nur aggregierte Status-Werte (kein JWT-Schutz in
    // diesem MVP) - siehe README, Abschnitt "Bekannte Einschränkungen" für die Produktivhärtung.
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/status`);

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
      const key = status.device.vlan_id;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(status);
    }
    return map;
  }, [statuses]);

  if (loading) return <p>Lade Gerätestatus…</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
      {vlans.map((vlan) => (
        <section key={vlan.id}>
          <h3>
            {vlan.name} <span style={{ color: "#57606a", fontWeight: 400 }}>(VLAN {vlan.tag})</span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Gerät</th>
                <th>IP-Adresse</th>
                <th>Typ</th>
                <th>Status</th>
                <th>Zuletzt gesehen</th>
              </tr>
            </thead>
            <tbody>
              {(devicesByVlan.get(vlan.id) ?? []).map((status) => (
                <tr key={status.device.id}>
                  <td>
                    <Link to={`/devices/${status.device.id}`}>{status.device.name}</Link>
                  </td>
                  <td>{status.device.ip_address}</td>
                  <td>{status.device.device_type}</td>
                  <td>
                    <StatusBadge status={liveStatus[status.device.id] ?? status.overall_status} />
                  </td>
                  <td>{status.last_seen ? new Date(status.last_seen).toLocaleString("de-DE") : "–"}</td>
                </tr>
              ))}
              {(devicesByVlan.get(vlan.id) ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} style={{ color: "#57606a" }}>
                    Keine Geräte in diesem VLAN konfiguriert.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
