# Deployment: Collector auf dem Router-Pi, Datenbank auf der NAS, Dashboard auf dem Webserver

Diese Anleitung geht von genau dem Setup aus, das im Projekt vorliegt: das
VLAN-Netzwerk (Switch + mehrere VLANs) ist bereits fertig eingerichtet, ein
Raspberry Pi hängt am Trunk-Port, routet zwischen den VLANs, macht die
Firewall zwischen den VLANs und betreibt bereits einen Reverse-Proxy für
andere interne Dienste. Eine zweite, NAS-artige Maschine (Raspberry Pi mit
4× 500 GB Festplatten, normales Linux) übernimmt die Datenbank. Der
Webserver läuft mit **pm2** (kein Docker). Am Netzwerk/an den VLANs muss
dafür **nichts** verändert werden.

```
Browser ──HTTPS──▶ Pi (bestehender Reverse-Proxy, TLS)
                       │
                       ├──▶ Webserver:5173  (Frontend, statischer Build)
                       └──▶ Webserver:8000  (Backend-API + WebSocket)

Router-Pi (Collector, systemd) ──HTTP/HTTPS + Bearer-Token──▶ Webserver:8000
Collector ──ICMP/SNMP──▶ Geräte in allen VLANs (lokal vom Router aus, da
                          der Collector auf dem Router selbst läuft)

Webserver (Backend) ──postgresql://<nas-ip>:5432──▶ NAS-Pi (Postgres,
                          Datenverzeichnis auf dem Festplatten-Array)
```

## 0. NAS-Pi: Postgres

Läuft auf einer eigenen Maschine, damit die Datenbank auf dedizierter,
redundanter Storage liegt statt auf der Systemplatte des Webservers.

### 0.1 PostgreSQL nativ installieren

TimescaleDB-spezifische Features werden im aktuellen Schema nicht genutzt –
ein normales PostgreSQL reicht:

```bash
sudo apt install postgresql
```

### 0.2 Datenverzeichnis auf das Festplatten-Array legen

**Wichtig bei einem Pi als NAS:** Standardmäßig legt Postgres sein
Datenverzeichnis auf der SD-Karte an. Der Collector schreibt alle ~30s pro
Gerät mehrere Messwerte – auf Dauer sorgt das für spürbaren Verschleiß und
schlechte Performance auf einer SD-Karte. Stattdessen auf das
Festplatten-Array verschieben (Beispiel, Array unter `/mnt/storage`
gemountet):

```bash
sudo systemctl stop postgresql
sudo pg_dropcluster --stop <version> main   # z.B. 15 main
sudo mkdir -p /mnt/storage/postgresql
sudo chown postgres:postgres /mnt/storage/postgresql
sudo pg_createcluster <version> main -d /mnt/storage/postgresql/<version>/main
sudo systemctl start postgresql
```

(Versionsnummer mit `pg_lsclusters` prüfen.)

### 0.3 Datenbank + Nutzer anlegen

```bash
sudo -u postgres psql -c "CREATE USER monitoring WITH PASSWORD '<passwort>';"
sudo -u postgres psql -c "CREATE DATABASE monitoring OWNER monitoring;"
```

### 0.4 Erreichbarkeit nur für den Webserver freigeben

`postgresql.conf` (z. B. `/etc/postgresql/<version>/main/postgresql.conf`):

```
listen_addresses = '<nas-ip>'
```

`pg_hba.conf`: eine einzige Zeile, die exakt die Webserver-IP erlaubt –
sonst nichts (kein `0.0.0.0/0`, kein `trust`):

```
host    monitoring    monitoring    <webserver-ip>/32    scram-sha-256
```

Firewall auf der NAS (Beispiel mit `ufw`):

```bash
sudo ufw allow from <webserver-ip> to any port 5432 proto tcp
```

Danach Postgres neu starten: `sudo systemctl restart postgresql`.

### 0.5 Backups

RAID schützt vor Plattenausfall, nicht vor einem versehentlichen
`DROP TABLE` oder Datenkorruption. Regelmäßiges `pg_dump` einrichten
(Cron, z. B. täglich, Ablage auf einem anderen Teil des Arrays oder extern):

```bash
sudo -u postgres pg_dump monitoring | gzip > /mnt/storage/backups/monitoring-$(date +%F).sql.gz
```

## 1. Webserver: Backend + Frontend

### 1.1 Repo holen

```bash
git clone <repo-url> /opt/monitoring
cd /opt/monitoring
cp .env.example .env
```

`.env` ausfüllen:
- `JWT_SECRET` und `COLLECTOR_API_TOKEN`: je ein langer Zufallsstring, z. B. `openssl rand -hex 32`
- `DATABASE_URL=postgresql+psycopg2://monitoring:<passwort>@<nas-ip>:5432/monitoring` (Postgres läuft auf der NAS, siehe Abschnitt 0 – nicht `localhost`)
- `BACKEND_URL` wird hier nicht gebraucht (nur relevant auf dem Pi)
- SMTP-Zugangsdaten für Alarm-Mails

### 1.2 Backend

```bash
cd /opt/monitoring/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Admin-Benutzer + Beispiel-VLANs anlegen
# (aus backend/ heraus, damit "app" gefunden wird; .env laden, damit DATABASE_URL
# auf die NAS zeigt; PYTHONPATH=.. damit "shared/" gefunden wird)
cd /opt/monitoring/backend
set -a; source ../.env; set +a
PYTHONPATH=.. .venv/bin/python -m app.seed
```

### 1.3 Frontend bauen

Voraussetzung: Node.js 20.19+ oder 22.12+ (Mindestversion von Vite 8).

Falls Frontend und Backend über den bestehenden Reverse-Proxy auf dem Pi unter
demselben Pfad erreichbar gemacht werden (empfohlen, siehe Abschnitt 3),
reicht ein normaler Build ohne weitere Konfiguration:

```bash
cd /opt/monitoring/frontend
npm install
npm run build
```

Falls stattdessen Frontend und Backend auf getrennten Ports ohne
Pfad-Rewrite laufen sollen, vorher `cp .env.production.example .env.production`
und `VITE_API_BASE_URL`/`VITE_WS_BASE_URL` auf die öffentliche Backend-Adresse setzen.

### 1.4 Mit pm2 starten

```bash
cd /opt/monitoring
pm2 start deploy/webserver/ecosystem.config.js
pm2 save   # damit die Prozesse einen Reboot überleben
```

`deploy/webserver/ecosystem.config.js` startet Backend (Uvicorn, Port 8000,
nur auf `127.0.0.1` gebunden) und Frontend (`serve -s dist`, Port 5173). Die
`run-backend.sh` lädt dabei die Werte aus der Repo-Root-`.env` in echte
Umgebungsvariablen (pm2-Ecosystem-Dateien kennen kein `env_file` wie
docker-compose). Falls das Skript nicht ausführbar ist: `chmod +x
deploy/webserver/run-backend.sh`.

Logs/Status: `pm2 logs monitoring-backend`, `pm2 status`.

## 2. Router-Pi: nur der Collector

Netzwerk-Setup ist bereits vorhanden – hier geht es nur um den Collector-Prozess selbst.

### 2.1 Collector-Ordner kopieren

Nur `collector/` wird gebraucht (kein `shared/`, keine DB-Treiber mehr):

```bash
sudo mkdir -p /opt/monitoring-collector
sudo cp -r collector /opt/monitoring-collector/
sudo useradd --system --home /opt/monitoring-collector monitoring || true
cd /opt/monitoring-collector
python3 -m venv venv
venv/bin/pip install -r collector/requirements.txt
sudo chown -R monitoring:monitoring /opt/monitoring-collector
```

### 2.2 Konfiguration

```bash
sudo cp deploy/pi/monitoring-collector.env.example /etc/monitoring-collector.env
sudo chmod 600 /etc/monitoring-collector.env
sudo $EDITOR /etc/monitoring-collector.env
```

Eintragen:
- `BACKEND_URL` – die Adresse, unter der der Webserver-Backend über den
  Reverse-Proxy erreichbar ist (z. B. `https://dashboard.example.com`), **oder**
  direkt die interne Adresse (z. B. `http://<webserver-ip>:8000`), wenn der
  Traffic nicht extra über den Reverse-Proxy laufen soll (spart TLS-Aufwand,
  ist aber nur vertretbar, weil dieser Traffic ohnehin nur innerhalb des
  selbst kontrollierten Netzes bleibt – siehe Sicherheits-Hinweis unten).
- `COLLECTOR_API_TOKEN` – exakt derselbe Wert wie in der `.env` auf dem Webserver.

### 2.3 systemd-Service

```bash
sudo cp deploy/pi/monitoring-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now monitoring-collector
sudo systemctl status monitoring-collector
journalctl -u monitoring-collector -f
```

### 2.4 Firewall

Der Collector läuft lokal auf dem Router-Pi selbst – ICMP/SNMP in die VLANs
sind also implizit erlaubt (der Traffic kommt vom Router, nicht von einem
dritten Host, die bestehenden Inter-VLAN-Regeln greifen hier nicht). Es wird
nur eine **ausgehende** Freigabe vom Pi zum Backend-Port auf dem Webserver
gebraucht (z. B. Port 8000 oder 443, je nachdem ob direkt oder über den
Reverse-Proxy) – das ist auf einem Router i. d. R. ohnehin erlaubt, wenn keine
restriktive OUTPUT-Policy für den Router-Prozess selbst existiert.

## 3. Dashboard von außen erreichbar machen

Da der Pi bereits einen Reverse-Proxy für andere Dienste betreibt, am
einfachsten dort einen weiteren Server-Block/Vhost für das Dashboard
ergänzen (Beispiel nginx-Syntax, sinngemäß für Caddy/Traefik/etc. übertragbar):

```nginx
server {
    listen 443 ssl;
    server_name dashboard.example.com;

    # bestehendes Zertifikat des Pi-Reverse-Proxys verwenden

    location / {
        proxy_pass http://<webserver-ip>:5173;
        proxy_set_header Host $host;
    }

    location /api/ {
        proxy_pass http://<webserver-ip>:8000/;
        proxy_set_header Host $host;
    }

    location /ws/ {
        proxy_pass http://<webserver-ip>:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Wenn dieser Pfad-Rewrite (`/api/` → Backend-Root) verwendet wird, braucht das
Frontend **keine** `VITE_API_BASE_URL`/`VITE_WS_BASE_URL` – die Defaults
(`/api`, `/ws`) passen dann automatisch.

## 4. Testen

1. Vom Webserver aus die DB-Verbindung prüfen: `psql -h <nas-ip> -U monitoring -d monitoring`
   sollte klappen; derselbe Befehl von einem dritten Host aus sollte an der
   Firewall der NAS abgewiesen werden.
2. `curl https://dashboard.example.com/api/health` → `{"status":"ok"}`
3. Im Dashboard einloggen (`admin` + `SEED_ADMIN_PASSWORD` aus der `.env`)
4. Ein echtes Gerät anlegen (IP, VLAN, ggf. SNMP-Community) und ein paar
   Minuten warten – `journalctl -u monitoring-collector -f` sollte
   Poll-Zyklen zeigen, im Dashboard sollte der Status auf „OK“ springen.
5. Testweise ein Gerät vom Netz nehmen → nach der konfigurierten Anzahl
   aufeinanderfolgender Fehlschläge sollte ein Alarm samt E-Mail kommen.

## 5. Sicherheits-Checkliste

- `JWT_SECRET` und `COLLECTOR_API_TOKEN` sind echte Zufallsstrings, nicht die
  Beispielwerte aus `.env.example`.
- Postgres auf der NAS ist per `listen_addresses` + `pg_hba.conf` + Firewall
  ausschließlich für die Webserver-IP erreichbar (siehe Abschnitt 0.4) – nicht
  fürs restliche Netz offen.
- Das Postgres-Datenverzeichnis liegt auf dem Festplatten-Array der NAS, nicht
  auf der SD-Karte (Abschnitt 0.2), und wird regelmäßig per `pg_dump` gesichert
  (Abschnitt 0.5).
- Browser-Zugriff läuft über HTTPS (TLS-Terminierung am bestehenden
  Reverse-Proxy auf dem Pi).
- SNMP nach Möglichkeit auf v3 (Auth+Privacy) umstellen, sobald die Geräte es
  unterstützen – v2c überträgt die Community im Klartext.
