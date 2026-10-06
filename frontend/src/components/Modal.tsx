import { ReactNode, useEffect, useRef, useState } from "react";
import { apiErrorMessage } from "../api/client";
import { Icon } from "./Icon";

export function Modal({
  title,
  onClose,
  children,
  size = "md",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  size?: "sm" | "md";
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  // onClose kommt oft als Inline-Funktion; ueber die Ref laeuft der Effekt nur einmal,
  // sonst wuerde der Fokus bei jedem Tastendruck zurueck aufs erste Feld springen
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }
    document.addEventListener("keydown", onKey);
    // Fokus in den Dialog setzen (erstes Eingabefeld, sonst den Dialog selbst)
    const first = dialogRef.current?.querySelector<HTMLElement>("input, select, textarea, button.btn-primary");
    (first ?? dialogRef.current)?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        className={`modal${size === "sm" ? " modal-sm" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <div className="modal-header">
          <h2>{title}</h2>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Schließen">
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function Notice({
  kind,
  children,
}: {
  kind: "error" | "warning" | "success" | "info";
  children: ReactNode;
}) {
  const icon = kind === "error" || kind === "warning" ? "alert" : kind === "success" ? "check" : "help";
  return (
    <div className={`notice notice-${kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon name={icon} size={16} />
      <div>{children}</div>
    </div>
  );
}

/** Bestaetigungsdialog (standardmaessig fuer Loeschaktionen); zeigt Fehler aus onConfirm im Dialog an. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Löschen",
  danger = true,
  onConfirm,
  onClose,
}: {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose} size="sm">
      <div className="form">
        <div>{message}</div>
        {error && <Notice kind="error">{error}</Notice>}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Abbrechen
          </button>
          <button
            type="button"
            className={`btn ${danger ? "btn-danger-solid" : "btn-primary"}`}
            onClick={confirm}
            disabled={busy}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
