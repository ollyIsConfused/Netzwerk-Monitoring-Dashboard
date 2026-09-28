import { MetricStatus } from "../api/client";

const LABELS: Record<MetricStatus, string> = {
  ok: "OK",
  warning: "Warnung",
  critical: "Kritisch",
  unknown: "Unbekannt",
};

const COLORS: Record<MetricStatus, string> = {
  ok: "#1a7f37",
  warning: "#b08800",
  critical: "#cf222e",
  unknown: "#6e7781",
};

export function StatusBadge({ status }: { status: MetricStatus }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        color: "#fff",
        backgroundColor: COLORS[status],
      }}
    >
      {LABELS[status]}
    </span>
  );
}
