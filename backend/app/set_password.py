"""Setzt das Passwort eines Benutzers direkt in der Datenbank, z. B. wenn man sich
ausgesperrt hat. Das Passwort wird verdeckt abgefragt und nie angezeigt.

Aufruf (aus backend/, mit geladener .env):
    python -m app.set_password            # Benutzer "admin"
    python -m app.set_password <benutzer>
"""
import getpass
import sys

from shared.database import SessionLocal, init_db
from shared.models import User

from .schemas import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from .security import hash_password


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            print(f"Benutzer '{username}' gibt es nicht. Zuerst 'python -m app.seed' ausführen.")
            return 1

        password = getpass.getpass(f"Neues Passwort für '{username}': ")
        if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
            print(f"Das Passwort muss {PASSWORD_MIN_LENGTH} bis {PASSWORD_MAX_LENGTH} Zeichen lang sein.")
            return 1
        if getpass.getpass("Passwort wiederholen: ") != password:
            print("Die Passwörter stimmen nicht überein.")
            return 1

        user.hashed_password = hash_password(password)
        user.is_active = True
        db.commit()
        print(f"Passwort für '{username}' gesetzt (Konto ist aktiv).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
