import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertEvent, api, apiErrorMessage, Device, formatDateTime, metricInfo } from "../api/client";
import { useAuth } from "../api/AuthContext";
import { Icon } from "../components/Icon";
import { Notice } from "../components/Modal";
import { AlertLevelBadge } from "../components/StatusBadge";

export function AlertsPage() {
  const { role } = useAuth();
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [devices, setDevices] = useState<Record<number, Device>>({});
  const [activeOnly, setActiveOnly] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const canAcknowledge = role === "admin" || role === "operator";

  const load = useCallback(async () => {
    try {
      const [alertsRes, devicesRes] = await Promise.all([
        api.get<AlertEvent[]>("/alerts", { params: { active_only: activeOnly } }),
        api.get<Device[]>("/devices"),
      ]);
      setAlerts(alertsRes.data);
      setDevices(Object.fromEntries(devicesRes.data.map((d) => [d.id, d])));
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err, "Alarme konnten nicht geladen werden."));
    } finally {
      setLoading(false);
    }
  }, [activeOnly]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [load]);

  async function acknowledge(id: number) {
    try {
      await api.post(`/alerts/${id}/acknowledge`);
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Alarme</h1>
          <p>Statuswechsel aller Geräte. Quittierte Alarme verschwinden aus der Liste „aktiv“.</p>
        </div>
        <div className="segmented" role="group" aria-label="Filter">
          <button type="button" aria-pressed={activeOnly} onClick={() => setActiveOnly(true)}>
            Aktiv
          </button>
          <button type="button" aria-pressed={!activeOnly} onClick={() => setActiveOnly(false)}>
            Alle
          </button>
        </div>
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      <section className="card">
        {loading ? (
          <div className="empty">Lade Alarme…</div>
        ) : alerts.length === 0 ? (
          <div className="empty">
            <Icon name="checkCircle" size={20} />
            <p style={{ margin: "6px 0 0" }}>{activeOnly ? "Keine aktiven Alarme." : "Noch keine Alarme."}</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Zeitpunkt</th>
                  <th>Stufe</th>
                  <th>Gerät</th>
                  <th>Metrik</th>
                  <th>Meldung</th>
                  <th>Quittiert</th>
                  {canAcknowledge && <th />}
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td className="num muted">{formatDateTime(alert.created_at)}</td>
                    <td>
                      <AlertLevelBadge level={alert.level} />
                    </td>
                    <td>
                      <Link to={`/devices/${alert.device_id}`}>
                        {devices[alert.device_id]?.name ?? `#${alert.device_id}`}
                      </Link>
                    </td>
                    <td>{metricInfo(alert.metric_name).label}</td>
                    <td>{alert.message}</td>
                    <td className="num muted">{formatDateTime(alert.acknowledged_at)}</td>
                    {canAcknowledge && (
                      <td className="actions">
                        {!alert.acknowledged_at && alert.level !== "recovered" && (
                          <button type="button" className="btn btn-sm" onClick={() => acknowledge(alert.id)}>
                            <Icon name="check" size={14} />
                            Quittieren
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
