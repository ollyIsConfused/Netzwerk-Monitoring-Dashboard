# Netzwerk-Monitoring-Dashboard

Web-basiertes Monitoring-Dashboard für eine segmentierte VLAN-Infrastruktur
(Switch, Router, DNS-Server, Webserver, NAS). Erfasst Erreichbarkeit,
Bandbreite, Paketverlust und Antwortzeiten je Gerät/VLAN, historisiert die
Werte und löst bei Grenzwertüberschreitung automatisch eine E-Mail-Benachrichtigung
aus. Rollenbasierte Weboberfläche (Admin / Operator / Viewer).

## Architektur

```
[Collector]  --Ping/SNMP-->  Geräte in allen VLANs
     |
     | HTTPS + Bearer-Token (COLLECTOR_API_TOKEN)
     v
[Backend (FastAPI, REST + WebSocket)]  <-- Agenten pushen direkt an /agent/push
     |
     v
[PostgreSQL]
     |
     v
[Frontend (React), rollenbasiert]
```

Der Collector hat **keinen** direkten Datenbankzugriff und keine Abhängigkeit
von `shared/` – er ist ein reiner HTTP-Client und kann dadurch unabhängig vom
Rest deployt werden (z. B. auf einem Router/Gateway, das ohnehin Zugriff auf
alle VLANs hat), während Backend/DB/Frontend woanders laufen. Details und ein
konkretes Beispiel (Collector auf einem Router-Pi am Trunk-Port, Rest auf
einem bestehenden Webserver mit pm2) stehen in
[`docs/deployment.md`](docs/deployment.md).

- **`shared/`** – gemeinsames Datenmodell (SQLAlchemy), Schwellenwert-/Alarmlogik
  und der SMTP-Notifier; wird nur vom Backend genutzt (Single Point of Truth für
  Alarme, keine Duplikation zwischen mehreren Schreibpfaden).
- **`backend/`** – FastAPI-API: Auth (JWT, Rollen), Geräte-/VLAN-Verwaltung,
  Metrik-Abfrage, Alarme (inkl. Quittierung), WebSocket-Status-Push, Endpunkte
  für den Collector (`GET /collector/devices`, `POST /collector/metrics`,
  Token-geschützt) und für eigene Agenten (`POST /agent/push`), sowie eine
  Hintergrundschleife, die fällige Alarm-E-Mails verschickt.
- **`collector/`** – eigenständiger, DB-loser Dienst, pollt zyklisch alle
  aktiven Geräte (ICMP-Ping für Erreichbarkeit/Latenz/Paketverlust, SNMP für
  Switch/Router-Interface-Zähler → daraus abgeleitete Bandbreite) und schickt
  die Rohwerte per HTTPS ans Backend; Schwellenwertauswertung/Alarme passieren
  zentral im Backend.
- **`frontend/`** – React/Vite-Dashboard: VLAN-Übersicht mit Live-Status
  (WebSocket), Geräte-Detailseite mit Zeitreihen-Diagrammen, Alarmliste mit
  Quittierfunktion.

## Setup (lokal mit Docker Compose)

```bash
cp .env.example .env
# .env anpassen: JWT_SECRET + COLLECTOR_API_TOKEN setzen (beliebige lange Zufallsstrings),
# SMTP-Zugangsdaten für Alarm-Mails eintragen

docker compose up --build -d

# Admin-Benutzer + Beispiel-VLANs anlegen
docker compose exec backend python -m app.seed
```

- Frontend: http://localhost:5173 (Login mit `admin` / dem in `.env` gesetzten `SEED_ADMIN_PASSWORD`)
- Backend-API/Docs: http://localhost:8000/docs

### Alternative: Backend und Frontend direkt starten, nur die Datenbank in Docker

Praktisch zum Entwickeln, weil Code-Änderungen sofort neu geladen werden.
Einmalig:

```bash
cp .env.example .env
# zusätzlich in .env: DATABASE_URL=postgresql+psycopg2://monitoring:<POSTGRES_PASSWORD>@localhost:5432/monitoring
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
```

Starten (Datenbank, Admin-Benutzer, Backend und Frontend in einem Terminal,
Strg+C beendet Backend und Frontend):

```bash
./dev.sh
```

Der Seed legt den Admin nur beim ersten Mal an. Ein später in `.env`
geändertes `SEED_ADMIN_PASSWORD` ändert das bestehende Passwort nicht.

Danach im Dashboard (oder direkt über die API) die echten Geräte anlegen:
IP-Adresse, VLAN-Zuordnung, für Switch/Router die SNMP-Community und zu
überwachende Interface-Indizes, für NAS/Webserver optional ein Agent-Token für
eigene Push-Metriken. Anschließend je Gerät Schwellenwerte (`warning_max`,
`critical_max`, …) über `POST /devices/{id}/thresholds` hinterlegen.

## Eigener Agent (Beispiel für NAS/Webserver)

Für Kennzahlen, die SNMP nicht hergibt (z. B. Festplattenbelegung, CPU-Last),
kann ein einfaches Skript auf dem Zielsystem laufen, das regelmäßig postet:

```bash
curl -X POST http://<backend>:8000/agent/push \
  -H "Content-Type: application/json" \
  -d '{"agent_token": "<token aus Geräte-Config>", "metrics": {"cpu_pct": 12.5, "disk_pct": 63.0}}'
```

## Netzwerk-/Sicherheitsvoraussetzungen

Der Collector braucht Zugriff über VLAN-Grenzen hinweg (ICMP + SNMP/UDP 161 +
ggf. Agent-Port). Empfehlung: eigenes Management-VLAN für den Monitoring-Host,
mit expliziten Firewall-/ACL-Freigaben nur für diese Protokolle in jedes
Ziel-VLAN (Least Privilege). SNMPv3 (Auth+Privacy) statt v2c verwenden, wo die
Geräte es unterstützen.

## Bekannte Einschränkungen (MVP)

- `GET /collector/devices` liefert die SNMP-Community im Klartext an den
  Collector aus – unproblematisch, solange die Verbindung per TLS (HTTPS)
  läuft (siehe `docs/deployment.md`), aber **nicht** ohne TLS zwischen
  getrennten Hosts einsetzen.
- Der WebSocket-Status-Kanal (`/ws/status`) ist nicht durch das JWT geschützt
  (liefert nur aggregierte Status-Labels, keine sensiblen Werte) – für den
  Produktivbetrieb sollte er zusätzlich abgesichert werden (z. B. Token-Check
  beim Verbindungsaufbau oder Absicherung auf Netzwerkebene).
- SNMP-Zähler-Overflow (32-Bit-Wraparound) wird erkannt und das betroffene
  Intervall übersprungen statt eine falsche Bandbreitenspitze zu melden;
  64-Bit-Zähler (`ifHCInOctets`/`ifHCOutOctets`) sind für High-Speed-Interfaces
  noch nicht implementiert.
- Keine automatische Downsampling-/Retention-Policy für `metric_samples` –
  für den Dauerbetrieb sollte ein Cron-Job alte Rohdaten aggregieren/löschen.

## Nächste Schritte

1. Reale Geräte-Inventarliste (IP, VLAN, SNMP-Zugang) eintragen und Prototyp
   gegen ein einzelnes Gerät testen.
2. Schwellenwerte pro Gerät/Metrik festlegen und mit simulierten Ausfällen
   (Kabel ziehen, Iperf-Last) verifizieren, dass Alarme korrekt auslösen.
3. TLS/Reverse-Proxy vor Frontend+Backend setzen, bevor das Dashboard aus
   einem produktiven VLAN heraus erreichbar gemacht wird.
4. Retention-/Downsampling-Job für Langzeittrends ergänzen.
