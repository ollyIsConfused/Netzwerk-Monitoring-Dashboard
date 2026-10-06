import { AlertLevel, MetricStatus } from "../api/client";
import { Icon, IconName } from "./Icon";

// Statusfarben sind reserviert und stehen nie allein: immer Symbol + Text dazu
const STATUS: Record<MetricStatus, { label: string; color: string; icon: IconName }> = {
  ok: { label: "OK", color: "var(--status-good)", icon: "checkCircle" },
  warning: { label: "Warnung", color: "var(--status-warning)", icon: "alert" },
  critical: { label: "Kritisch", color: "var(--status-critical)", icon: "xCircle" },
  unknown: { label: "Unbekannt", color: "var(--status-unknown)", icon: "help" },
};

const LEVEL: Record<AlertLevel, { label: string; color: string; icon: IconName }> = {
  warning: STATUS.warning,
  critical: STATUS.critical,
  recovered: { label: "Behoben", color: "var(--status-good)", icon: "checkCircle" },
};

function Badge({ label, color, icon, title }: { label: string; color: string; icon: IconName; title?: string }) {
  return (
    <span className="badge" title={title}>
      <span style={{ color, display: "inline-flex" }}>
        <Icon name={icon} size={14} />
      </span>
      {label}
    </span>
  );
}

export function StatusBadge({ status }: { status: MetricStatus }) {
  return <Badge {...STATUS[status]} />;
}

export function AlertLevelBadge({ level }: { level: AlertLevel }) {
  return <Badge {...LEVEL[level]} />;
}

export function ReachableBadge({ reachable, stale = false }: { reachable: boolean | null; stale?: boolean }) {
  // Letzter Stand zu alt (Collector meldet sich nicht): kein online/offline vortaeuschen
  if (stale) {
    return (
      <Badge
        {...STATUS.unknown}
        label="Veraltet"
        title="Keine aktuellen Daten - angezeigt wird der letzte bekannte Stand"
      />
    );
  };
  if (reachable === null) return <Badge {...STATUS.unknown} label="Keine Daten" />;
  return reachable ? (
    <Badge label="Online" color="var(--status-good)" icon="checkCircle" />
  ) : (
    <Badge label="Offline" color="var(--status-critical)" icon="xCircle" />
  );
}
