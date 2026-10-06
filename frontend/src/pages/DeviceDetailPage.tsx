import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import {
  AlertEvent,
  api,
  apiErrorMessage,
  describeDeviceVlans,
  Device,
  DEVICE_TYPE_LABELS,
  formatDateTime,
  formatMetricValue,
  isChartableMetric,
  metricInfo,
  MetricSamplePoint,
  ThresholdRule,
  Vlan,
} from "../api/client";
import { useAuth } from "../api/AuthContext";
import { Icon } from "../components/Icon";
import { MetricChart } from "../components/MetricChart";
import { ConfirmDialog, Notice } from "../components/Modal";
import { AlertLevelBadge } from "../components/StatusBadge";
import { ThresholdDialog } from "../components/ThresholdDialog";

const RANGES = [
  { minutes: 30, label: "30 Min" },
  { minutes: 60, label: "1 Std" },
  { minutes: 360, label: "6 Std" },
  { minutes: 1440, label: "24 Std" },
];

const DEFAULT_METRICS = ["reachable", "latency_ms", "packet_loss_pct"];

function metricOrder(name: string): number {
  const index = DEFAULT_METRICS.indexOf(name);
  return index === -1 ? DEFAULT_METRICS.length : index;
}

export function DeviceDetailPage() {
  const { deviceId } = useParams<{ deviceId: string }>();
  const { role } = useAuth();
  const isAdmin = role === "admin";

  const [device, setDevice] = useState<Device | null>(null);
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [samplesByMetric, setSamplesByMetric] = useState<Record<string, MetricSamplePoint[]>>({});
  const [rules, setRules] = useState<ThresholdRule[]>([]);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [rangeMinutes, setRangeMinutes] = useState(60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ThresholdRule | "new" | null>(null);
  const [deleting, setDeleting] = useState<ThresholdRule | null>(null);

  const loadMeta = useCallback(async () => {
    try {
      const [deviceRes, vlansRes, rulesRes, alertsRes] = await Promise.all([
        api.get<Device>(`/devices/${deviceId}`),
        api.get<Vlan[]>("/vlans"),
        api.get<ThresholdRule[]>(`/devices/${deviceId}/thresholds`),
        api.get<AlertEvent[]>("/alerts", { params: { device_id: deviceId, limit: 10 } }),
      ]);
      setDevice(deviceRes.data);
      setVlans(vlansRes.data);
      setRules(rulesRes.data);
      setAlerts(alertsRes.data);
    } catch (err) {
      setError(apiErrorMessage(err, "Gerät konnte nicht geladen werden."));
    }
  }, [deviceId]);

  useEffect(() => {
    loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const response = await api.get<MetricSamplePoint[]>(`/devices/${deviceId}/metrics`, {
          params: { since_minutes: rangeMinutes },
        });
        const grouped: Record<string, MetricSamplePoint[]> = {};
        for (const sample of response.data) {
          if (!grouped[sample.metric_name]) grouped[sample.metric_name] = [];
          grouped[sample.metric_name].push(sample);
        }
        if (!cancelled) setSamplesByMetric(grouped);
      } catch (err) {
        if (!cancelled) setError(apiErrorMessage(err, "Messwerte konnten nicht geladen werden."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [deviceId, rangeMinutes]);

  const chartMetrics = useMemo(() => {
    const names = new Set([...DEFAULT_METRICS, ...Object.keys(samplesByMetric)]);
    return [...names].filter(isChartableMetric).sort((a, b) => metricOrder(a) - metricOrder(b) || a.localeCompare(b));
  }, [samplesByMetric]);


  if (error && !device) {
    return (
      <div className="page">
        <Notice kind="error">{error}</Notice>
        <Link to="/">Zur Übersicht</Link>
      </div>
    );
  }

  return (
    <div className="page">
      <div>
        <Link to="/" className="muted" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Icon name="arrowLeft" size={14} />
          Übersicht
        </Link>
      </div>
      <div className="page-header">
        <div>
          <h1>{device?.name ?? `Gerät #${deviceId}`}</h1>
          {device && (
            <div className="detail-meta" style={{ marginTop: 6 }}>
              <span>
                IP <b className="mono">{device.ip_address}</b>
              </span>
              <span>
                Typ <b>{DEVICE_TYPE_LABELS[device.device_type]}</b>
              </span>
              <span>
                {device.port_mode === "trunk" ? "Trunk" : "VLAN"}{" "}
                <b>{describeDeviceVlans(device, vlans).replace(/^–$/, "keins")}</b>
              </span>
              {!device.is_active && <span className="badge badge-plain">pausiert</span>}
            </div>
          )}
        </div>
        {/* Zeitraum-Filter: eine Zeile oberhalb aller Diagramme, gilt fuer alle */}
        <div className="segmented" role="group" aria-label="Zeitraum">
          {RANGES.map((range) => (
            <button
              key={range.minutes}
              type="button"
              aria-pressed={rangeMinutes === range.minutes}
              onClick={() => setRangeMinutes(range.minutes)}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>

      {error && device && <Notice kind="error">{error}</Notice>}

      <div className="grid-2">
        {chartMetrics.map((metricName) => (
          <MetricChart
            key={metricName}
            metricName={metricName}
            samples={samplesByMetric[metricName] ?? []}
            rule={rules.find((r) => r.metric_name === metricName)}
            loading={loading}
          />
        ))}
      </div>

      <section className="card">
        <div className="card-header">
          <h2>Schwellenwerte</h2>
          {isAdmin && (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setEditing("new")}>
              <Icon name="plus" size={14} />
              Schwellenwert
            </button>
          )}
        </div>
        {rules.length === 0 ? (
          <div className="empty">
            Keine Schwellenwerte - für dieses Gerät werden keine Alarme ausgelöst.
            {isAdmin && " Tipp: Vorlage „Offline-Alarm“ verwenden."}
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Metrik</th>
                  <th>Warnung</th>
                  <th>Kritisch</th>
                  <th>Messungen bis Alarm</th>
                  {isAdmin && <th />}
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id}>
                    <td>{metricInfo(rule.metric_name).label}</td>
                    <td className="num">
                      {[
                        rule.warning_max !== null && `≥ ${formatMetricValue(rule.metric_name, rule.warning_max)}`,
                        rule.warning_min !== null && `≤ ${formatMetricValue(rule.metric_name, rule.warning_min)}`,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "–"}
                    </td>
                    <td className="num">
                      {[
                        rule.critical_max !== null && `≥ ${formatMetricValue(rule.metric_name, rule.critical_max)}`,
                        rule.critical_min !== null && `≤ ${formatMetricValue(rule.metric_name, rule.critical_min)}`,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "–"}
                    </td>
                    <td className="num">{rule.consecutive_breaches_required}</td>
                    {isAdmin && (
                      <td className="actions">
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm btn-icon"
                          onClick={() => setEditing(rule)}
                          aria-label="Bearbeiten"
                        >
                          <Icon name="edit" size={14} />
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm btn-icon btn-danger"
                          onClick={() => setDeleting(rule)}
                          aria-label="Löschen"
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Letzte Alarme</h2>
          <Link to="/alerts">Alle Alarme</Link>
        </div>
        {alerts.length === 0 ? (
          <div className="empty">Keine Alarme für dieses Gerät.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td className="num muted">{formatDateTime(alert.created_at)}</td>
                    <td>
                      <AlertLevelBadge level={alert.level} />
                    </td>
                    <td>{alert.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {editing && device && (
        <ThresholdDialog
          deviceId={device.id}
          rule={editing === "new" ? null : editing}
          metricOptions={chartMetrics.filter((m) => !rules.some((r) => r.metric_name === m))}
          onClose={() => setEditing(null)}
          onSaved={loadMeta}
        />
      )}
      {deleting && device && (
        <ConfirmDialog
          title="Schwellenwert löschen"
          message={`Schwellenwert für „${metricInfo(deleting.metric_name).label}“ löschen? Danach gibt es für diese Metrik keine Alarme mehr.`}
          onConfirm={async () => {
            await api.delete(`/devices/${device.id}/thresholds/${deleting.id}`);
            await loadMeta();
          }}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
