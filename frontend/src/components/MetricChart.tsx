import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMetricValue, metricInfo, MetricSamplePoint, parseTimestamp, ThresholdRule } from "../api/client";

interface Point {
  t: number;
  value: number;
}

const AXIS_TICK = { fill: "var(--text-muted)", fontSize: 12 };

function formatTime(t: number, spanMs: number): string {
  const date = new Date(t);
  return spanMs > 20 * 3600 * 1000
    ? date.toLocaleString("de-DE", { weekday: "short", hour: "2-digit", minute: "2-digit" })
    : date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function ChartTooltip({
  active,
  payload,
  metricName,
}: {
  active?: boolean;
  payload?: { payload: Point }[];
  metricName: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="chart-tooltip">
      {/* Wert zuerst und kraeftig, Zeitpunkt als Nebeninformation */}
      <strong>{formatMetricValue(metricName, point.value)}</strong>
      <span>{new Date(point.t).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" })}</span>
    </div>
  );
}

function thresholdLines(rule: ThresholdRule | undefined) {
  if (!rule) return [];
  const lines: { y: number; label: string; color: string }[] = [];
  if (rule.warning_max !== null) lines.push({ y: rule.warning_max, label: "Warnung", color: "var(--status-warning)" });
  if (rule.critical_max !== null) lines.push({ y: rule.critical_max, label: "Kritisch", color: "var(--status-critical)" });
  if (rule.warning_min !== null) lines.push({ y: rule.warning_min, label: "Warnung", color: "var(--status-warning)" });
  if (rule.critical_min !== null) lines.push({ y: rule.critical_min, label: "Kritisch", color: "var(--status-critical)" });
  return lines;
}

/** Eine Messgroesse pro Diagramm (eine Achse), Flaeche als dezente Toenung, Fadenkreuz + Tooltip. */
export function MetricChart({
  metricName,
  samples,
  rule,
  loading,
}: {
  metricName: string;
  samples: MetricSamplePoint[];
  rule?: ThresholdRule;
  loading: boolean;
}) {
  const { label, unit } = metricInfo(metricName);
  const points: Point[] = samples.map((s) => ({ t: parseTimestamp(s.timestamp), value: s.value }));
  const spanMs = points.length > 1 ? points[points.length - 1].t - points[0].t : 0;
  const isReachable = metricName === "reachable";
  const latest = points.length ? points[points.length - 1].value : null;

  return (
    <section className="card chart-card" style={{ opacity: loading ? 0.6 : 1 }}>
      <div className="card-header">
        <h3>
          {label} {unit && <span className="muted">({unit})</span>}
        </h3>
        {latest !== null && <span className="mono">{formatMetricValue(metricName, latest)}</span>}
      </div>
      <div className="card-body">
        {points.length === 0 ? (
          <div className="empty">Keine Messwerte in diesem Zeitraum.</div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={points} margin={{ top: 10, right: rule ? 64 : 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => formatTime(t, spanMs)}
                tick={AXIS_TICK}
                stroke="var(--axis)"
                tickLine={false}
                minTickGap={48}
              />
              <YAxis
                width={64}
                tick={AXIS_TICK}
                axisLine={false}
                tickLine={false}
                domain={isReachable ? [0, 1] : [0, "auto"]}
                ticks={isReachable ? [0, 1] : undefined}
                tickFormatter={(v: number) =>
                  isReachable ? (v >= 1 ? "online" : "offline") : unit === "bit/s" ? formatMetricValue(metricName, v) : String(v)
                }
              />
              <Tooltip
                content={<ChartTooltip metricName={metricName} />}
                cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
                isAnimationActive={false}
              />
              {thresholdLines(rule).map((line) => (
                <ReferenceLine
                  key={`${line.label}-${line.y}`}
                  y={line.y}
                  stroke={line.color}
                  strokeWidth={1}
                  ifOverflow="extendDomain"
                  // Beschriftung rechts neben dem Plot, damit sie nie die Messkurve verdeckt
                  label={{ value: line.label, position: "right", fill: "var(--text-secondary)", fontSize: 11 }}
                />
              ))}
              <Area
                type={isReachable ? "stepAfter" : "monotone"}
                dataKey="value"
                stroke="var(--series-1)"
                strokeWidth={2}
                fill="var(--series-1)"
                fillOpacity={0.1}
                dot={false}
                activeDot={{ r: 4, fill: "var(--series-1)", stroke: "var(--surface)", strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
