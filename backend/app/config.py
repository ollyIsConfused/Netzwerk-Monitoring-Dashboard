import os

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-.env")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

STATUS_BROADCAST_INTERVAL_SECONDS = int(os.environ.get("STATUS_BROADCAST_INTERVAL_SECONDS", "5"))
