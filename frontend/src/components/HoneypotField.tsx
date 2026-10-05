import { forwardRef } from "react";

/**
 * Lockfeld (Honeypot) gegen Formular-Bots: fuer Menschen unsichtbar und per Tastatur nicht
 * erreichbar, im HTML aber ein ganz normales Eingabefeld. Einfache Bots fuellen jedes Feld
 * aus - das Backend weist solche Anfragen ab. Der Wert wird beim Absenden ueber die Ref
 * gelesen, damit auch Bots erkannt werden, die nur value setzen ohne Eingabe-Events.
 */
export const HoneypotField = forwardRef<HTMLInputElement, { name: string; label: string }>(
  function HoneypotField({ name, label }, ref) {
    return (
      <div className="hp-field" aria-hidden="true">
        <label>
          {label}
          <input ref={ref} type="text" name={name} tabIndex={-1} autoComplete="off" defaultValue="" />
        </label>
      </div>
    );
  },
);
