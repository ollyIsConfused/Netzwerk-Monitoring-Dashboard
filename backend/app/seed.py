"""One-off script: creates the initial admin user and, if none exist yet, example VLANs.

Run with:  python -m app.seed
"""
import os

from shared.database import SessionLocal, init_db
from shared.models import User, UserRole, Vlan

from .security import hash_password

DEFAULT_ADMIN_PASSWORD = "admin"


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin").first():
            admin_password = os.environ.get("SEED_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD
            admin_email = os.environ.get("SEED_ADMIN_EMAIL") or "admin@example.com"
            db.add(
                User(
                    username="admin",
                    email=admin_email,
                    hashed_password=hash_password(admin_password),
                    role=UserRole.admin,
                    # Das Startpasswort ist bekannt bzw. steht im Klartext in der .env
                    must_change_password=True,
                )
            )
            # Ein Passwort aus der .env bewusst nicht ausgeben (landet sonst in Terminal-Verlauf und Logs)
            if os.environ.get("SEED_ADMIN_PASSWORD"):
                print("Admin-Benutzer 'admin' angelegt (Startpasswort aus SEED_ADMIN_PASSWORD).")
            else:
                print(f"Admin-Benutzer 'admin' angelegt, Startpasswort '{DEFAULT_ADMIN_PASSWORD}'.")
            print("Beim ersten Anmelden muss ein eigenes Passwort festgelegt werden.")
            if admin_email.endswith("@example.com"):
                print(
                    "Hinweis: SEED_ADMIN_EMAIL ist nicht gesetzt - 'Passwort vergessen'-Anfragen erreichen "
                    "niemanden. Echte Adresse im Dashboard unter Verwaltung > Benutzer eintragen."
                )

        # In einer echten Umgebung stoeren Beispiel-VLANs nur (install.sh setzt SEED_EXAMPLE_VLANS=0)
        if os.environ.get("SEED_EXAMPLE_VLANS", "1") != "0" and db.query(Vlan).count() == 0:
            db.add_all(
                [
                    Vlan(name="Management", tag=10, description="Monitoring-Host, Switch-/Router-Management"),
                    Vlan(name="Server", tag=20, description="DNS, Webserver, NAS"),
                    Vlan(name="Clients", tag=30, description="Arbeitsplätze"),
                ]
            )
            print("Beispiel-VLANs angelegt.")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
