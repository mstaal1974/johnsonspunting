import os
import tempfile
import threading
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

ON_VERCEL = bool(os.getenv("VERCEL"))

# Vercel's Postgres/Neon integrations set POSTGRES_URL rather than DATABASE_URL
DB_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
# Hosts hand out postgres:// or postgresql:// URLs; pin the psycopg (v3) driver
for prefix in ("postgres://", "postgresql://"):
    if DB_URL.startswith(prefix):
        DB_URL = "postgresql+psycopg://" + DB_URL[len(prefix):]

# Without a database server the app falls back to a SQLite file. Serverless
# hosts only allow writes under the temp dir, and wipe it whenever the function
# restarts, so data there is not kept - the page shows a warning.
EPHEMERAL = not DB_URL and ON_VERCEL
if not DB_URL:
    default_dir = Path(tempfile.gettempdir()) / "puntclub" if ON_VERCEL else Path("data")
    DATA_DIR = Path(os.getenv("DATA_DIR", default_dir))
    DB_URL = f"sqlite:///{DATA_DIR / 'club.db'}"
else:
    DATA_DIR = None

if DB_URL.startswith("sqlite"):
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:
    # Serverless functions come and go, so don't hold connections open between requests
    engine = create_engine(DB_URL, pool_pre_ping=True, **({"poolclass": NullPool} if ON_VERCEL else {}))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

_ready = False
_ready_lock = threading.Lock()


def init_db():
    """Create tables and seed data. Safe to call repeatedly."""
    global _ready
    if _ready:
        return
    with _ready_lock:
        if _ready:
            return
        from app import models  # noqa: F401
        from app.services.club import ensure_seed

        if DATA_DIR is not None:
            DATA_DIR.mkdir(exist_ok=True, parents=True)
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            ensure_seed(db)
        _ready = True


def get_db():
    # Some hosts (e.g. Vercel) don't run ASGI startup events, so set up on first use
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
