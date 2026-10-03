import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, MetricSamplePoint } from "../api/client";

const CHART_METRICS = ["latency_ms", "packet_loss_pct"] as const;

export function DeviceDetailPage() {
  const { deviceId } = useParams<{ deviceId: string }>();
  const [samplesByMetric, setSamplesByMetric] = useState<Record<string, MetricSamplePoint[]>>({});
  const [rangeMinutes, setRangeMinutes] = useState(60);

  useEffect(() => {
    if (!deviceId) return;
    async function load() {
      const response = await api.get<MetricSamplePoint[]>(`/devices/${deviceId}/metrics`, {
        params: { since_minutes: rangeMinutes },
      });
      const grouped: Record<string, MetricSamplePoint[]> = {};
      for (const sample of response.data) {
        if (!grouped[sample.metric_name]) grouped[sample.metric_name] = [];
        grouped[sample.metric_name].push(sample);
      }
      setSamplesByMetric(grouped);
    }
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [deviceId, rangeMinutes]);

  const availableMetrics = Object.keys(samplesByMetric).length > 0 ? Object.keys(samplesByMetric) : CHART_METRICS;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Gerät #{deviceId}</h2>
        <select value={rangeMinutes} onChange={(e) => setRangeMinutes(Number(e.target.value))}>
          <option value={30}>Letzte 30 Minuten</option>
          <option value={60}>Letzte Stunde</option>
          <option value={360}>Letzte 6 Stunden</option>
          <option value={1440}>Letzte 24 Stunden</option>
        </select>
      </div>

      {availableMetrics.map((metricName) => {
        const points = (samplesByMetric[metricName] ?? []).map((s) => ({
          time: new Date(s.timestamp).toLocaleTimeString("de-DE"),
          value: s.value,
        }));
        return (
          <div key={metricName} style={{ marginTop: 24, background: "#fff", padding: 16, borderRadius: 8 }}>
            <h4 style={{ marginTop: 0 }}>{metricName}</h4>
            {points.length === 0 ? (
              <p style={{ color: "#57606a" }}>Noch keine Daten für diesen Zeitraum.</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={points}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" minTickGap={40} />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="value" stroke="#0969da" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        );
      })}
    </div>
  );
}
