"""One-off script: creates the initial admin user and, if none exist yet, example VLANs.

Run with:  python -m app.seed
"""
import os

from shared.database import SessionLocal, init_db
from shared.models import User, UserRole, Vlan

from .security import hash_password


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin").first():
            admin_password = os.environ.get("SEED_ADMIN_PASSWORD", "changeme123")
            db.add(
                User(
                    username="admin",
                    email=os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com"),
                    hashed_password=hash_password(admin_password),
                    role=UserRole.admin,
                )
            )
            print(f"Admin-Benutzer 'admin' angelegt (Passwort: {admin_password}) - bitte nach dem ersten Login ändern.")

        if db.query(Vlan).count() == 0:
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
