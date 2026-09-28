import { useEffect, useState } from "react";
import { api, AlertEvent } from "../api/client";
import { useAuth } from "../api/AuthContext";

export function AlertsPage() {
  const { role } = useAuth();
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [activeOnly, setActiveOnly] = useState(true);
  const canAcknowledge = role === "admin" || role === "operator";

  async function load() {
    const response = await api.get<AlertEvent[]>("/alerts", { params: { active_only: activeOnly } });
    setAlerts(response.data);
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOnly]);

  async function acknowledge(id: number) {
    await api.post(`/alerts/${id}/acknowledge`);
    load();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Alarme</h2>
        <label style={{ fontSize: 14 }}>
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} /> nur aktive
          Alarme
        </label>
      </div>
      <table>
        <thead>
          <tr>
            <th>Zeitpunkt</th>
            <th>Gerät</th>
            <th>Metrik</th>
            <th>Stufe</th>
            <th>Nachricht</th>
            <th>Quittiert</th>
            {canAcknowledge && <th></th>}
          </tr>
        </thead>
        <tbody>
          {alerts.map((alert) => (
            <tr key={alert.id}>
              <td>{new Date(alert.created_at).toLocaleString("de-DE")}</td>
              <td>{alert.device_id}</td>
              <td>{alert.metric_name}</td>
              <td>{alert.level}</td>
              <td>{alert.message}</td>
              <td>{alert.acknowledged_at ? new Date(alert.acknowledged_at).toLocaleString("de-DE") : "–"}</td>
              {canAcknowledge && (
                <td>
                  {!alert.acknowledged_at && <button onClick={() => acknowledge(alert.id)}>Quittieren</button>}
                </td>
              )}
            </tr>
          ))}
          {alerts.length === 0 && (
            <tr>
              <td colSpan={canAcknowledge ? 7 : 6} style={{ color: "#57606a" }}>
                Keine Alarme.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
