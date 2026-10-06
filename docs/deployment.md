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
Browser (per VPN) ──HTTP──▶ Webserver:8080  nginx
                                ├── /       → Frontend (statischer Build)
                                ├── /api/   → Backend 127.0.0.1:8000 (pm2)
                                └── /ws/    → Backend-WebSocket

Router-Pi (Collector, systemd) ──HTTP + Bearer-Token──▶ Webserver:8080/api
Collector ──ICMP/SNMP──▶ Geräte in allen VLANs (lokal vom Router aus, da
                          der Collector auf dem Router selbst läuft)

Webserver (Backend) ──postgresql://<nas-ip>:5432──▶ NAS-Pi (Postgres,
                          Datenverzeichnis auf dem Festplatten-Array)
```

Das Backend lauscht nur lokal auf dem Webserver; nach außen ist nur der eine
nginx-Port sichtbar. Für Webserver und Router-Pi gibt es Installationsskripte,
die beim ersten Mal einrichten und danach als Update dienen (Abschnitte 1 und 2).

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

Voraussetzungen (einmalig): `git`, Python 3.10–3.12 mit `venv`, Node.js 20.19+ oder 22.12+,
`pm2` (`sudo npm install -g pm2`) und nginx.

### 1.1 Repo holen und installieren

```bash
sudo git clone https://github.com/ollyIsConfused/Netzwerk-Monitoring-Dashboard.git /opt/monitoring
sudo chown -R "$USER" /opt/monitoring
cd /opt/monitoring
./deploy/webserver/install.sh
```

Beim ersten Aufruf legt das Skript die `.env` an (Rechte `600`, `JWT_SECRET` und
`COLLECTOR_API_TOKEN` zufällig) und fragt im Terminal nach:

- **Datenbank:** Server, Port, Name, Benutzer und Passwort (Postgres auf der NAS,
  siehe Abschnitt 0). Daraus baut es die `DATABASE_URL`, Sonderzeichen im Passwort
  werden automatisch kodiert.
- **E-Mail-Adresse des Admins:** bekommt die „Passwort vergessen“-Anfragen.
- **SMTP (optional):** Server, Port, Benutzer, Passwort für Alarm- und Passwort-Mails.
  Leer lassen, um das später in der `.env` nachzutragen.

Passwörter werden bei der Eingabe nicht angezeigt und landen nur in der `.env`.
Ohne Terminal (z. B. per Skript) bricht es stattdessen ab und nennt die Werte, die
von Hand mit `nano .env` einzutragen sind.

### 1.2 Was das Skript macht

1. Python-Umgebung `backend/.venv` und Pakete
2. Verbindungstest zur Datenbank – mit Hinweisen, falls Firewall, `pg_hba.conf`
   oder Passwort nicht passen
3. Tabellen und Admin-Benutzer (nur wenn noch nicht vorhanden). Neue Spalten aus
   späteren Versionen ergänzt es in einer bestehenden Datenbank automatisch.
4. Frontend-Build (`frontend/dist`)
5. Backend per pm2 starten bzw. neu starten (`monitoring-backend`, nur `127.0.0.1:8000`)
6. nginx-Site `monitoring-dashboard` auf Port 8080 (fragt vorher; `--nginx` ohne
   Rückfrage, `--port N` für einen anderen Port). Ist die Konfiguration
   fehlerhaft, wird die Site wieder deaktiviert – das bestehende nginx bleibt unverändert.

Am Ende zeigt es die Werte für den Collector an. Firewall-Regeln ändert es
**nicht**, es nennt nur die nötigen Freigaben.

Einmalig, damit pm2 nach einem Neustart automatisch startet: `pm2 startup`
(den angezeigten `sudo`-Befehl ausführen), danach `pm2 save`.

### 1.3 Update

```bash
cd /opt/monitoring
git pull
./deploy/webserver/install.sh
```

### 1.4 Erste Anmeldung und Passwörter

Erste Anmeldung im Dashboard: Benutzer `admin`, Passwort `admin`. Das Dashboard
verlangt sofort ein eigenes Passwort, vorher ist nichts anderes erreichbar. Bis
dahin kann sich jeder im Netz mit `admin`/`admin` anmelden, deshalb direkt nach
der Installation anmelden.

Hat jemand sein Passwort vergessen, nutzt er auf der Anmeldeseite „Passwort
vergessen?“ (Benutzername + E-Mail). Der Admin bekommt eine Mail und schickt unter
*Verwaltung > Benutzer* mit dem Schlüssel-Symbol ein Einmal-Passwort an die beim
Konto hinterlegte Adresse. Ablauf und Schutzmaßnahmen: siehe README, Abschnitt
„Konten und Passwörter“.

Admin selbst ausgesperrt:

```bash
cd /opt/monitoring/backend
set -a; source ../.env; set +a
PYTHONPATH=.. .venv/bin/python -m app.set_password admin
```

### 1.5 E-Mail (SMTP)

Steht in der `.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`). Bei
Gmail: `smtp.gmail.com`, Port `587`, als Passwort ein App-Passwort (Google-Konto >
Sicherheit > 2-Faktor-Bestätigung > App-Passwörter), nicht das normale
Konto-Passwort. Werte mit Leerzeichen in einfache Anführungszeichen setzen.

Testen:

```bash
./deploy/webserver/install.sh --mailtest
```

Das schickt eine Test-Mail an die Admin-Adresse. Die Firewall muss vom Webserver
ausgehend Port 587 (bzw. 465) erlauben. Links in den Mails zeigen auf
`DASHBOARD_URL`. Das Skript setzt dafür `http://<webserver-ip>:8080`. Wer das
Dashboard über eine andere Adresse aufruft, ändert den Wert in der `.env` und
startet das Skript erneut.

## 2. Router-Pi: nur der Collector

Netzwerk-Setup ist bereits vorhanden – hier geht es nur um den Collector-Prozess selbst.

```bash
git clone https://github.com/ollyIsConfused/Netzwerk-Monitoring-Dashboard.git ~/Netzwerk-Monitoring-Dashboard
cd ~/Netzwerk-Monitoring-Dashboard
sudo ./deploy/pi/install-collector.sh
```

Beim ersten Aufruf legt das Skript `/etc/monitoring-collector.env` an (nur für
root lesbar) und bricht ab. Dann `sudo nano /etc/monitoring-collector.env`:

- `BACKEND_URL=http://<webserver-ip>:8080/api` (zeigt `install.sh` auf dem Webserver an)
- `COLLECTOR_API_TOKEN` – exakt derselbe Wert wie in der `.env` auf dem Webserver
  (dort anzeigen mit `grep ^COLLECTOR_API_TOKEN .env`)

Danach das Skript erneut starten. Es kopiert den Collector nach
`/opt/monitoring-collector`, richtet die Python-Umgebung ein, **testet die
Verbindung zum Backend samt Token** (mit klarer Meldung bei falscher URL,
falschem Token oder blockiertem Port) und startet den systemd-Dienst
`monitoring-collector`.

Update: `git pull && sudo ./deploy/pi/install-collector.sh`
Logs: `journalctl -u monitoring-collector -f`

**Firewall:** Der Collector läuft auf dem Router-Pi selbst. ICMP/SNMP in die VLANs
und die Verbindung zum Webserver sind ausgehender Verkehr des Routers und von
den Weiterleitungsregeln (`ufw route`) nicht betroffen.

## 3. Dashboard erreichbar machen

Das Dashboard soll nicht öffentlich sein, sondern nur per VPN (bzw. aus dem
Heimnetz) erreichbar. Dafür braucht es auf dem Router-Pi eine Weiterleitungsregel
vom VPN zum Webserver-Port, z. B.:

```bash
sudo ufw route allow in on wg0 out on eth0.30 proto tcp from 10.10.10.2 to 192.168.30.15 port 8080
```

Läuft auf dem Webserver selbst eine Firewall, dort Port 8080 für den Router und
das VPN freigeben. Danach im Browser: `http://192.168.30.15:8080`.

Soll das Dashboard trotzdem über den Reverse-Proxy auf dem Pi laufen, reicht dort
ein einziges `reverse_proxy <webserver-ip>:8080` – nginx auf dem Webserver
verteilt `/api` und `/ws` bereits selbst. Dann den Zugriff unbedingt auf VPN und
Heimnetz beschränken.

## 4. Testen

1. Vom Webserver aus die DB-Verbindung prüfen: `psql -h <nas-ip> -U monitoring -d monitoring`
   sollte klappen; derselbe Befehl von einem dritten Host aus sollte an der
   Firewall der NAS abgewiesen werden.
2. `curl http://<webserver-ip>:8080/api/health` → `{"status":"ok"}`
3. Im Dashboard einloggen (`admin` / `admin`) und ein eigenes Passwort festlegen
4. Ein echtes Gerät anlegen (IP, VLAN, ggf. SNMP-Community) und ein paar
   Minuten warten – `journalctl -u monitoring-collector -f` sollte
   Poll-Zyklen zeigen, im Dashboard sollte der Status auf „OK“ springen.
5. Testweise ein Gerät vom Netz nehmen → nach der konfigurierten Anzahl
   aufeinanderfolgender Fehlschläge sollte ein Alarm samt E-Mail kommen.

## 5. Sicherheits-Checkliste

- `JWT_SECRET` und `COLLECTOR_API_TOKEN` sind echte Zufallsstrings, nicht die
  Beispielwerte aus `.env.example`.
- Das Startpasswort `admin` ist direkt nach der Installation durch ein eigenes
  ersetzt (Abschnitt 1.4), und beim Admin ist eine echte E-Mail-Adresse hinterlegt.
- Postgres auf der NAS ist per `listen_addresses` + `pg_hba.conf` + Firewall
  ausschließlich für die Webserver-IP erreichbar (siehe Abschnitt 0.4) – nicht
  fürs restliche Netz offen.
- Das Postgres-Datenverzeichnis liegt auf dem Festplatten-Array der NAS, nicht
  auf der SD-Karte (Abschnitt 0.2), und wird regelmäßig per `pg_dump` gesichert
  (Abschnitt 0.5).
- Das Dashboard ist nur per VPN bzw. aus dem Heimnetz erreichbar (Abschnitt 3),
  das Backend lauscht nur auf `127.0.0.1`.
- SNMP nach Möglichkeit auf v3 (Auth+Privacy) umstellen, sobald die Geräte es
  unterstützen – v2c überträgt die Community im Klartext.
