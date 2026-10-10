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

Agent auf NAS/Webserver/Router-Pi/Pi-hole ──HTTP + Agent-Token──▶ Webserver:8080/api
                          (CPU, Arbeitsspeicher, Festplatte, Temperatur; optional)
```

Das Backend lauscht nur lokal auf dem Webserver; nach außen ist nur der eine
nginx-Port sichtbar. Für Webserver, Router-Pi und die Agenten gibt es
Installationsskripte, die beim ersten Mal einrichten und danach als Update dienen
(Abschnitte 1 bis 3).

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
./deploy/webserver/install.sh --nginx
```

`--nginx` übernimmt auch Änderungen an der nginx-Site, z. B. neue Sicherheits-Header
(Abschnitt 4.1). Ohne den Schalter fragt das Skript nach.

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

## 2. Router-Pi: Collector

Netzwerk-Setup ist bereits vorhanden – hier geht es nur um den Collector-Prozess selbst.

### 2.1 Installieren

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

**Webserver und Collector immer zusammen aktualisieren.** Kommen neue Felder in der
Geräte-Konfiguration hinzu (wie bei SNMP v3), stürzt ein älterer Collector daran ab. Die
Übersicht zeigt dann „Veraltet“, bis auch der Collector aktualisiert ist. Collectors ab
der Version mit SNMP v3 ignorieren unbekannte Felder.

**Firewall:** Der Collector läuft auf dem Router-Pi selbst. ICMP/SNMP in die VLANs
und die Verbindung zum Webserver sind ausgehender Verkehr des Routers und von
den Weiterleitungsregeln (`ufw route`) nicht betroffen.

### 2.2 So arbeitet der Collector

Alle 30 Sekunden (`POLL_INTERVAL_SECONDS`):

1. Er holt mit seinem Token die Liste der aktiven Geräte vom Backend
   (`GET /api/collector/devices`).
2. Er pingt jedes Gerät 5-mal an. Daraus werden Erreichbarkeit, Paketverlust und
   Antwortzeit.
3. Bei den Typen Switch, Router und Gateway fragt er per SNMP (v1, v2c oder v3, je nach
   Gerät) je eingetragenem Interface-Index den Status (`ifOperStatus`) und die
   Byte-Zähler ab und berechnet daraus die Bandbreite. Die drei Werte einer
   Schnittstelle holt er mit einer Anfrage.
4. Er schickt alle Werte an das Backend (`POST /api/collector/metrics`). Speichern,
   Schwellenwerte prüfen, Alarme und Mails übernimmt das Backend. Der Collector selbst
   hat keinen Zugriff auf die Datenbank.

**Absenderadresse:** Der Router-Pi hat in jedem VLAN eine eigene Adresse (das
Gateway). Linux nimmt als Absender immer die Adresse der Schnittstelle, über die das
Ziel erreicht wird:

| Ziel                         | Absender des Collectors        |
|------------------------------|--------------------------------|
| Pi-hole `192.168.20.10`      | `192.168.20.1` (`eth0.20`)     |
| Webserver `192.168.30.15`    | `192.168.30.1` (`eth0.30`)     |
| NAS `192.168.50.25`          | `192.168.50.1` (`eth0.50`)     |
| Router-Pi `192.168.178.66`   | `192.168.178.66` (lokal)       |

Nachprüfen auf dem Router-Pi mit `ip route get 192.168.20.10` (Feld `src`). Wichtig
ist das für SNMP-Freigaben auf den Geräten (Abschnitt 2.4).

Die Zeitstempel der Messwerte kommen von der Uhr des Router-Pi. Geht sie falsch,
meldet das Dashboard die Werte als veraltet. `timedatectl` muss
`System clock synchronized: yes` zeigen.

### 2.3 Den Router-Pi im Dashboard eintragen

Vorher unter *Verwaltung > VLANs* die VLANs anlegen, z. B. Heimnetz (Tag 1, das
ungetaggte FritzBox-Netz), DNS (20), Server (30) und NAS (50). Dann unter
*Verwaltung > Geräte*:

| Feld                          | Wert                                              |
|-------------------------------|---------------------------------------------------|
| Name / Typ                    | Router-Pi / Router                                |
| Haupt-IP (Verwaltung)         | `192.168.178.66`                                  |
| Anschluss am Switch           | Trunk-Port                                        |
| Natives VLAN                  | Heimnetz (VLAN 1)                                 |
| Getaggte VLANs                | DNS (20), Server (30), NAS (50)                   |
| Adresse in VLAN 20 / 30 / 50  | `192.168.20.1` / `192.168.30.1` / `192.168.50.1`  |

Die Übersicht zeigt den Router-Pi dann in jeder VLAN-Karte mit seiner Adresse dort.
Angepingt und per SNMP abgefragt wird die Haupt-IP.

Weil der Collector auf dem Router-Pi läuft, pingt er sich selbst an – der Router-Pi
ist damit immer „online“. Aussagekräftig ist bei ihm der Zustand seiner
Schnittstellen über SNMP. Dafür auf dem Router-Pi snmpd einrichten:

```bash
sudo apt install snmpd snmp
sudo cp /etc/snmp/snmpd.conf /etc/snmp/snmpd.conf.bak-$(date +%F)
sudo nano /etc/snmp/snmpd.conf
```

Die vorhandene `agentaddress`-Zeile und die `rocommunity public …`-Zeilen
auskommentieren (`#` davor) und stattdessen eintragen (`<community>` ist ein
selbst gewähltes, nicht erratbares Wort):

```
agentaddress udp:127.0.0.1:161,udp:192.168.178.66:161
rocommunity <community> 127.0.0.1
rocommunity <community> 192.168.178.66
```

- `agentaddress`: auf welchen Adressen snmpd lauscht. Standard ist nur
  `127.0.0.1`; der Collector fragt aber die Haupt-IP `192.168.178.66` ab.
- `rocommunity`: nur lesen, und nur für Anfragen von diesen Absendern. Fragt der
  Router-Pi sich selbst über `192.168.178.66` ab, ist das auch der Absender.
  `127.0.0.1` ist für Tests von Hand.
- Port 161 von außen bleibt durch ufw gesperrt (eingehend standardmäßig `deny`) –
  dafür keine Regel anlegen.

```bash
sudo systemctl restart snmpd
snmpwalk -v2c -c <community> 192.168.178.66 1.3.6.1.2.1.2.2.1.2
```

`1.3.6.1.2.1.2.2.1.2` ist die Adresse der Liste aller Schnittstellennamen (`ifDescr`).
Den Namen `IF-MIB::ifDescr` versteht `snmpwalk` unter Debian/Raspberry Pi OS nur mit
dem Zusatzpaket `snmp-mibs-downloader`, sonst kommt „Unknown Object Identifier“ – die
Zahlenadresse funktioniert immer. Die Ausgabe sieht etwa so aus (die Nummern
unterscheiden sich je System):

```
iso.3.6.1.2.1.2.2.1.2.1 = STRING: "lo"
iso.3.6.1.2.1.2.2.1.2.2 = STRING: "eth0"
iso.3.6.1.2.1.2.2.1.2.5 = STRING: "eth0.20"
iso.3.6.1.2.1.2.2.1.2.6 = STRING: "eth0.30"
iso.3.6.1.2.1.2.2.1.2.7 = STRING: "eth0.50"
iso.3.6.1.2.1.2.2.1.2.8 = STRING: "wg0"
```

Die letzte Zahl der Adresse ist der Interface-Index. Im Gerät unter SNMP eintragen:
Community, Version v2c, Port 161 und als Interface-Indizes z. B. `2,5,6,7,8`
(`eth0`, die drei VLAN-Schnittstellen und das VPN). Danach zeigt die Detailseite
pro Schnittstelle Status und Bandbreite – also auch pro VLAN-Gateway. Mit der
Schwellenwert-Vorlage „Interface N Status: aus“ (kritisch ab 2) gibt es einen Alarm,
sobald eine Schnittstelle ausfällt; die `eth0.X`-Schnittstellen fallen mit, wenn das
Trunk-Kabel gezogen wird.

### 2.4 SNMP auf anderen Geräten (z. B. Switch)

Die SNMP-Freigabe eines Geräts muss die Gateway-Adresse des Router-Pi in dem VLAN
erlauben, in dem die Verwaltungsadresse des Geräts liegt (Tabelle in Abschnitt 2.2).
Hat der Switch z. B. die Adresse `192.168.20.2`, kommt die Anfrage von
`192.168.20.1`. Die Adresse des Webservers (`192.168.30.15`) ist dafür falsch – der
Webserver fragt keine Geräte ab.

### 2.5 SNMP v3 (z. B. TP-Link TL-SG3210)

Bei v1/v2c steht die Community im Klartext in jedem Paket. SNMP v3 meldet sich
stattdessen mit Benutzer und Passwort an, ohne das Passwort zu übertragen (Prüfsumme
per SHA), schützt vor gefälschten und wiederholten Paketen und verschlüsselt die
Werte (AES oder DES). Für Geräte, deren SNMP-Verkehr über das Netz läuft (Switch),
ist das die richtige Wahl. Für den Router-Pi selbst reicht v2c, weil er sich lokal
abfragt (Abschnitt 2.3).

**Views verstehen:** Jeder SNMP-Wert hat eine Adresse im Baum, z. B.
`1.3.6.1.2.1.2.2.1.10.<port>` = empfangene Bytes eines Ports. Eine *View* gibt Teile
dieses Baums frei (*Include*) oder sperrt sie (*Exclude*, der genauere Eintrag gewinnt).
Eine *Gruppe* nutzt Views zum Lesen (*Read View*), Ändern (*Write View*) und für
Meldungen (*Notify View*); ein *Benutzer* gehört zu einer Gruppe.

Am TL-SG3210 (Weboberfläche, Menü *SNMP*):

1. **Global Config:** SNMP auf *Enable*, *Apply*. Die *Local Engine ID* nicht ändern –
   aus ihr und den Passwörtern berechnet der Switch die Schlüssel der v3-Benutzer.
2. **SNMP View:** `viewDefault` so lassen (Include `1`, Exclude `1.3.6.1.6.3.15`,
   `.16`, `.18` – die Excludes verbergen Benutzer, Gruppen und Communities; nicht
   löschen). Am saubersten zusätzlich eine View nur für das Monitoring, drei Zeilen
   mit demselben Namen:

   | View Name        | View Type | MIB Object ID     | Inhalt                          |
   |------------------|-----------|-------------------|---------------------------------|
   | `viewMonitoring` | Include   | `1.3.6.1.2.1.1`   | system (Name, Laufzeit)         |
   | `viewMonitoring` | Include   | `1.3.6.1.2.1.2`   | interfaces (Status, Zähler)     |
   | `viewMonitoring` | Include   | `1.3.6.1.2.1.31`  | ifMIB (Portnamen, 64-Bit-Zähler) |

3. **SNMP Group:** Name `Monitoring`, Security Level **AuthPriv**, Read View
   `viewMonitoring` (oder `viewDefault`), Write View und Notify View **leer** – keine
   Schreibrechte.
4. **SNMP User:** Name z. B. `Monitoring` (Groß-/Kleinschreibung zählt), *Local User*,
   Gruppe `Monitoring`, **AuthPriv**, Authentication Mode **SHA**, Privacy Mode **DES**
   (der TL-SG3210 bietet nur DES; wo AES angeboten wird, AES nehmen). Zwei verschiedene
   Passwörter, z. B. `openssl rand -hex 16` (32 Zeichen, Auth) und `openssl rand -hex 8`
   (16 Zeichen, Privacy – mehr erlaubt der Switch dort nicht).
5. **v1/v2c-Communities** `public`/`private` löschen, falls vorhanden.
6. Oben auf **Save**, sonst ist alles nach einem Neustart weg.

Test vom Router-Pi aus (Werte einsetzen):

```bash
snmpwalk -v3 -l authPriv -u Monitoring -a SHA -A 'AUTH-PASSWORT' -x DES -X 'PRIV-PASSWORT' <switch-ip> 1.3.6.1.2.1.31.1.1.1.1
```

`1.3.6.1.2.1.31.1.1.1.1` ist die Liste der Portnamen (`ifName`). Die letzte Zahl jeder
Zeile ist der Interface-Index (bei TP-Link oft große Zahlen wie `49153` für `1/0/1`).

| Ausgabe | Bedeutung |
|---|---|
| `… = STRING: "1/0/1"` | passt |
| `Authentication failure (incorrect password, community or key)` | Auth-Passwort oder SHA/MD5 passt nicht |
| `Unknown user name` | Benutzername falsch (Groß-/Kleinschreibung) |
| `Timeout: No Response` | SNMP aus, falsche IP, Zugriffsbeschränkung am Switch – oder Privacy-Passwort/Verfahren falsch (der Switch kann dann nicht entschlüsseln und antwortet gar nicht) |

Im Dashboard beim Switch: *SNMP-Abfrage aktivieren*, Version **v3**, Benutzer,
Anmeldung **SHA**, Auth-Passwort, Verschlüsselung **DES**, Privacy-Passwort, Port 161,
Interface-Indizes aus dem Test. Dieselben Fehler wie in der Tabelle stehen bei
Problemen auch im Collector-Log (`journalctl -u monitoring-collector -n 50`).

Die Zugangsdaten liegen wie die Community im Klartext in der Datenbank (der Collector
braucht sie im Klartext). Sichtbar sind sie nur für Admins im Bearbeiten-Dialog und für
den Collector über dessen Token, nicht in den normalen Ansichten.

Optional auch für den Router-Pi selbst: `sudo systemctl stop snmpd`, dann
`sudo net-snmp-create-v3-user -ro -a SHA -A 'AUTH-PASSWORT' -x AES -X 'PRIV-PASSWORT' monitoring`
(das Werkzeug gehört zum Paket `snmpd`), `sudo systemctl start snmpd` und im Dashboard
v3 mit SHA/AES eintragen. Kommentierst du danach die `rocommunity`-Zeilen aus, ist v2c
ganz abgeschaltet.

## 3. Agent auf den Servern (CPU, Arbeitsspeicher, Festplatte)

Was Ping und SNMP nicht liefern, schickt ein kleiner Agent vom Gerät selbst an das
Backend: CPU-Last (`cpu_pct`), Arbeitsspeicher (`mem_pct`), Belegung von `/`
(`disk_pct`) und weiterer Laufwerke (z. B. `disk_mnt_storage_pct` für
`/mnt/storage`) und, wo vorhanden, die Temperatur (`temp_c`, z. B. beim Raspberry Pi).
Er braucht nur bash, awk, df und curl und läuft auf NAS, Webserver, Router-Pi und
Pi-hole.

### 3.1 Im Dashboard vorbereiten

*Verwaltung > Geräte >* Gerät bearbeiten > „Agent darf Messwerte an /agent/push
senden“ anhaken > „Generieren“ > Speichern. Jedes Gerät bekommt ein eigenes Token.

### 3.2 Auf dem Gerät installieren

```bash
git clone https://github.com/ollyIsConfused/Netzwerk-Monitoring-Dashboard.git ~/Netzwerk-Monitoring-Dashboard
cd ~/Netzwerk-Monitoring-Dashboard
sudo ./deploy/agent/install-agent.sh
```

(Ist das Repo schon da, statt `git clone` nur `git pull`.) Das Skript fragt:

- **Backend-Adresse:** `http://192.168.30.15:8080/api` (auf dem Webserver selbst
  geht auch `http://127.0.0.1:8080/api`)
- **Agent-Token** aus dem Dashboard (Eingabe wird nicht angezeigt)
- **Laufwerke:** Vorschlag aus `df`, auf der NAS z. B. `/ /mnt/storage`. Ist ein
  Laufwerk nicht eingehängt, lässt der Agent es weg, statt die Systemplatte zu melden.
- **Intervall:** 60 Sekunden (15 bis 120)

Dann speichert es die Werte in `/etc/monitoring-agent.env` (nur für root lesbar),
kopiert den Agenten nach `/opt/monitoring-agent`, **sendet einmal zur Probe** (mit
klarer Meldung bei falschem Token, falscher Adresse oder blockierter Verbindung) und
richtet den systemd-Timer `monitoring-agent.timer` ein. Der Agent läuft dabei als
eigener Benutzer ohne Rechte und kann das Dateisystem nur lesen.

- Werte ansehen, ohne zu senden: `/opt/monitoring-agent/monitoring-agent.sh --print`
- Log: `journalctl -u monitoring-agent -n 20`
- Update: `git pull && sudo ./deploy/agent/install-agent.sh` (Enter übernimmt die bisherigen Werte)
- Abschalten: `sudo systemctl disable --now monitoring-agent.timer`

Im Dashboard gibt es danach beim Gerät unter „Schwellenwerte“ Vorlagen für CPU-Last,
Arbeitsspeicher, Festplatte und Temperatur.

### 3.3 Firewall

Der Agent verbindet sich vom Gerät zum Webserver, Port 8080. Webserver (lokal) und
Router-Pi (eigener ausgehender Verkehr) brauchen keine Regel. NAS und Pi-hole liegen
in anderen VLANs, dort muss der Router-Pi die Verbindung weiterleiten. Zuerst den
IST-Zustand ansehen:

```bash
sudo ufw status numbered
```

Dann die beiden Regeln **ergänzen** (es wird nichts gelöscht oder ersetzt):

```bash
sudo ufw route allow in on eth0.50 out on eth0.30 proto tcp from 192.168.50.25 to 192.168.30.15 port 8080
sudo ufw route allow in on eth0.20 out on eth0.30 proto tcp from 192.168.20.10 to 192.168.30.15 port 8080
```

- `route allow`: erlaubt Weiterleitung durch den Router (nicht Verbindungen zum
  Router selbst – SSH auf den Router-Pi bleibt davon unberührt).
- `in on eth0.50 out on eth0.30`: von VLAN 50 (NAS) nach VLAN 30 (Webserver).
- `from … to … port 8080 proto tcp`: genau ein Absender, ein Ziel, ein Port.

Die Antworten des Webservers lässt ufw automatisch zurück (bestehende Verbindung).
ufw speichert die Regeln dauerhaft (`/etc/ufw/user.rules`). Steht in
`ufw status numbered` oberhalb schon eine `DENY`-Regel für denselben Weg, greift die
neue Regel nicht – dann mit `sudo ufw insert <nummer> route allow …` davor einfügen.

### 3.4 Veraltete Daten

Kommen vom Collector oder von einem Agenten länger als `STALE_AFTER_SECONDS`
(Standard 180, in der `.env` auf dem Webserver) keine neuen Werte, zeigt die Übersicht
„Veraltet“ statt online/offline und oben einen Hinweis, was zu prüfen ist. Das
Agent-Intervall muss deshalb deutlich kleiner sein (das Skript erlaubt höchstens 120 s).
Fragt der Collector sehr viele Geräte ab (er arbeitet sie nacheinander ab, ca. 4–6 s
pro Gerät), den Wert erhöhen.

## 4. Dashboard erreichbar machen

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

### 4.1 Schutz, wenn das Dashboard öffentlich erreichbar ist

Läuft das Dashboard über Cloudflare und Caddy im Internet, greifen diese Schutzmaßnahmen
ohne weitere Einstellung:

- **Sicherheits-Header** von nginx: Content-Security-Policy (Skripte und Verbindungen
  nur von der eigenen Adresse), HSTS, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, Referrer-Policy. Prüfen:
  `curl -sI https://<deine-domain>/ | grep -iE 'content-security|strict-transport|x-frame'`
- **Login-Bremse:** Nach 5 Fehlversuchen von einer Adresse ist die Anmeldung dort für
  5 Minuten gesperrt, nach 10 Fehlversuchen für einen Benutzernamen ebenso (von jeder
  Adresse aus). Die Besucher-Adresse kommt aus dem Header `CF-Connecting-IP`, den
  Cloudflare setzt und Caddy weiterreicht. Einstellbar in `.env` mit
  `LOGIN_MAX_FAILURES` und `LOGIN_BLOCK_SECONDS`.
- **Live-Status (`/ws/status`) nur nach Anmeldung:** Das Frontend schickt das Token als
  erste Nachricht. Ohne gültiges Token beendet der Server die Verbindung, ebenso wenn
  die Anmeldung abläuft oder das Passwort geändert wird.
- **Keine API-Beschreibung:** `/api/docs` und `/api/openapi.json` sind abgeschaltet
  (`ENABLE_API_DOCS=1` in `.env` schaltet sie wieder ein, z. B. zum Entwickeln).
- **Kein CORS:** Andere Webseiten dürfen die API nicht aus dem Browser heraus
  aufrufen. Nur wenn das Frontend unter einer anderen Adresse läuft als die API,
  diese in `CORS_ORIGINS` eintragen.

Den stärksten Schutz bietet zusätzlich **Cloudflare Access** (kostenlos bis 50
Benutzer, *Zero Trust > Access > Applications*): Dann sieht nur, wer sich vorher bei
Cloudflare ausgewiesen hat (z. B. per Code an die eigene E-Mail-Adresse), überhaupt
die Anmeldeseite. Der Collector und die Agenten sind davon nicht betroffen, sie
sprechen den Webserver im Heimnetz direkt an.

## 5. Testen

1. Vom Webserver aus die DB-Verbindung prüfen: `psql -h <nas-ip> -U monitoring -d monitoring`
   sollte klappen; derselbe Befehl von einem dritten Host aus sollte an der
   Firewall der NAS abgewiesen werden.
2. `curl http://<webserver-ip>:8080/api/health` → `{"status":"ok"}`
3. Im Dashboard einloggen (`admin` / `admin`) und ein eigenes Passwort festlegen
4. Ein echtes Gerät anlegen (IP, VLAN, ggf. SNMP-Community) und ein paar
   Minuten warten – `journalctl -u monitoring-collector -f` sollte
   Poll-Zyklen zeigen, im Dashboard sollte der Status auf „OK“ springen.
5. Beim Gerät einen Schwellenwert anlegen (Vorlage „Offline-Alarm“) und es
   testweise vom Netz nehmen → nach der konfigurierten Anzahl aufeinanderfolgender
   Fehlschläge sollte ein Alarm samt E-Mail kommen. Ohne Schwellenwert zeigt die
   Übersicht nur „Offline“, löst aber keinen Alarm aus.
6. Collector anhalten (`sudo systemctl stop monitoring-collector` auf dem Router-Pi)
   → nach etwa 3 Minuten zeigt die Übersicht „Veraltet“ und einen Hinweis. Danach
   `sudo systemctl start monitoring-collector`.

## 6. Sicherheits-Checkliste

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
- Das Dashboard ist nur per VPN bzw. aus dem Heimnetz erreichbar (Abschnitt 4),
  das Backend lauscht nur auf `127.0.0.1`. Ist es doch öffentlich: nginx-Site mit
  `install.sh --nginx` aktuell (Sicherheits-Header), `ENABLE_API_DOCS` nicht gesetzt,
  am besten Cloudflare Access davor (Abschnitt 4.1).
- snmpd auf dem Router-Pi nutzt eine eigene Community, nicht `public`, und erlaubt
  nur die eigenen Adressen (Abschnitt 2.3); Port 161 ist von außen nicht freigegeben.
- Jeder Agent hat ein eigenes Token; `/etc/monitoring-agent.env` ist nur für root
  lesbar. Für die Agenten von NAS und Pi-hole sind nur die beiden Regeln zum
  Webserver-Port freigegeben (Abschnitt 3.3).
- SNMP auf Geräten, deren Verkehr über das Netz läuft (Switch), mit v3 und AuthPriv
  (Abschnitt 2.5): Gruppe ohne Write View, eigene Read View nur für System und
  Schnittstellen. v2c überträgt die Community im Klartext.
