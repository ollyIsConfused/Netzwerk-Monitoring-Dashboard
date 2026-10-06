import { FormEvent, useState } from "react";
import { api, apiErrorMessage, metricInfo, ThresholdRule } from "../api/client";
import { Modal, Notice } from "./Modal";

type NumberField = "warning_max" | "critical_max" | "warning_min" | "critical_min";

type Preset = { label: string; metric: string; values: Partial<Record<NumberField, number>> };

const PRESETS: Preset[] = [
  { label: "Offline-Alarm", metric: "reachable", values: { critical_min: 0 } },
  { label: "Antwortzeit", metric: "latency_ms", values: { warning_max: 100, critical_max: 500 } },
  { label: "Paketverlust", metric: "packet_loss_pct", values: { warning_max: 10, critical_max: 50 } },
  // Vom Agenten
  { label: "CPU-Last", metric: "cpu_pct", values: { warning_max: 80, critical_max: 95 } },
  { label: "Arbeitsspeicher", metric: "mem_pct", values: { warning_max: 85, critical_max: 95 } },
  { label: "Festplatte", metric: "disk_pct", values: { warning_max: 80, critical_max: 90 } },
  { label: "Temperatur", metric: "temp_c", values: { warning_max: 70, critical_max: 80 } },
];

/** Vorlagen fuer Metriken mit Nummer bzw. Pfad im Namen (Interfaces, weitere Laufwerke). */
function patternPresets(metricOptions: string[]): Preset[] {
  return metricOptions.flatMap((metric): Preset[] => {
    // ifOperStatus: 1 = up, ab 2 (down, testing, ...) ist die Schnittstelle nicht in Betrieb
    if (/^if\d+_oper_status$/.test(metric)) {
      return [{ label: `${metricInfo(metric).label}: aus`, metric, values: { critical_max: 2 } }];
    }
    if (/^disk_.+_pct$/.test(metric)) {
      return [{ label: metricInfo(metric).label, metric, values: { warning_max: 80, critical_max: 90 } }];
    }
    return [];
  });
}

function toInput(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function toNumber(value: string): number | null {
  const trimmed = value.trim().replace(",", ".");
  return trimmed === "" ? null : Number(trimmed);
}

export function ThresholdDialog({
  deviceId,
  rule,
  metricOptions,
  onClose,
  onSaved,
}: {
  deviceId: number;
  rule: ThresholdRule | null;
  metricOptions: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [metric, setMetric] = useState(rule?.metric_name ?? metricOptions[0] ?? "reachable");
  const [values, setValues] = useState<Record<NumberField, string>>({
    warning_max: toInput(rule?.warning_max),
    critical_max: toInput(rule?.critical_max),
    warning_min: toInput(rule?.warning_min),
    critical_min: toInput(rule?.critical_min),
  });
  const [breaches, setBreaches] = useState(String(rule?.consecutive_breaches_required ?? 2));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function applyPreset(preset: Preset) {
    setMetric(preset.metric);
    setValues({
      warning_max: toInput(preset.values.warning_max),
      critical_max: toInput(preset.values.critical_max),
      warning_min: toInput(preset.values.warning_min),
      critical_min: toInput(preset.values.critical_min),
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const numbers = Object.fromEntries(
      (Object.keys(values) as NumberField[]).map((key) => [key, toNumber(values[key])]),
    ) as Record<NumberField, number | null>;
    if (Object.values(numbers).some((n) => n !== null && Number.isNaN(n))) {
      setError("Bitte nur Zahlen eintragen.");
      return;
    }
    if (Object.values(numbers).every((n) => n === null)) {
      setError("Mindestens ein Grenzwert muss gesetzt sein.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = { ...numbers, consecutive_breaches_required: Number(breaches) || 1 };
      if (rule) {
        await api.patch(`/devices/${deviceId}/thresholds/${rule.id}`, payload);
      } else {
        await api.post(`/devices/${deviceId}/thresholds`, { metric_name: metric, ...payload });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  if (!rule && metricOptions.length === 0) {
    return (
      <Modal title="Schwellenwert anlegen" onClose={onClose} size="sm">
        <div className="form">
          <Notice kind="info">Für alle Metriken dieses Geräts gibt es schon Schwellenwerte - bearbeite die vorhandenen.</Notice>
          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose}>
              Schließen
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  const unit = metricInfo(metric).unit;
  // Nur Vorlagen fuer Metriken anbieten, die noch keinen Schwellenwert haben
  const presets = [
    ...PRESETS.filter((preset) => metricOptions.includes(preset.metric)),
    ...patternPresets(metricOptions),
  ];
  const numberInput = (key: NumberField, label: string) => (
    <label className="field">
      <span>
        {label} {unit && <span className="muted">({unit})</span>}
      </span>
      <input
        className="input"
        inputMode="decimal"
        value={values[key]}
        onChange={(e) => setValues({ ...values, [key]: e.target.value })}
        placeholder="leer = kein Grenzwert"
      />
    </label>
  );

  return (
    <Modal title={rule ? `Schwellenwert: ${metricInfo(rule.metric_name).label}` : "Schwellenwert anlegen"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {!rule && (
          <>
            {presets.length > 0 && (
              <div className="toolbar">
                <span className="muted">Vorlagen:</span>
                {presets.map((preset) => (
                  <button key={preset.label} type="button" className="btn btn-sm" onClick={() => applyPreset(preset)}>
                    {preset.label}
                  </button>
                ))}
              </div>
            )}
            <label className="field">
              <span>Metrik</span>
              <select className="select" value={metric} onChange={(e) => setMetric(e.target.value)}>
                {metricOptions.map((name) => (
                  <option key={name} value={name}>
                    {metricInfo(name).label} ({name})
                  </option>
                ))}
              </select>
            </label>
          </>
        )}

        <div className="form-grid">
          {numberInput("warning_max", "Warnung ab")}
          {numberInput("critical_max", "Kritisch ab")}
          {numberInput("warning_min", "Warnung bei höchstens")}
          {numberInput("critical_min", "Kritisch bei höchstens")}
          <label className="field span-2">
            <span>Messungen in Folge bis zum Alarm</span>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={breaches}
              onChange={(e) => setBreaches(e.target.value)}
            />
            <small>Verhindert Fehlalarme durch einzelne Ausreißer (bei 30 s Intervall: 2 = 1 Minute).</small>
          </label>
        </div>
        <small className="muted">
          „ab“ gilt für zu hohe Werte (z. B. Antwortzeit), „höchstens“ für zu niedrige (z. B. Erreichbarkeit: kritisch
          bei höchstens 0 = offline).
        </small>

        {error && <Notice kind="error">{error}</Notice>}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Abbrechen
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Speichern
          </button>
        </div>
      </form>
    </Modal>
  );
}
