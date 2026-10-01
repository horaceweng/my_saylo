from collections.abc import Iterator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.app_db_url, connect_args={"check_same_thread": False})


# Columns added after their table was first created: (table, column, definition, SQL run once when the column is added)
_LATER_COLUMNS = [
    ("media", "transcribed", "BOOLEAN NOT NULL DEFAULT 0",
     # Videos processed before this column existed were transcribed in one go.
     "UPDATE media SET transcribed = 1 WHERE status IN ('translating', 'ready')"),
    ("media", "level", "VARCHAR NOT NULL DEFAULT ''", None),
    ("media", "score", "FLOAT NOT NULL DEFAULT 0", None),
    ("book", "url", "VARCHAR NOT NULL DEFAULT ''", None),
    ("book", "published", "VARCHAR NOT NULL DEFAULT ''", None),
    ("book", "site", "VARCHAR NOT NULL DEFAULT ''", None),
    # Feeds used to be news only; podcast channels share the table.
    ("feed", "kind", "VARCHAR NOT NULL DEFAULT 'news'", None),
    ("feed", "image", "VARCHAR NOT NULL DEFAULT ''", None),
    # Phrases saved before spaced review existed are due for their first review straight away.
    ("savedphrase", "due_at", "DATETIME", "UPDATE savedphrase SET due_at = created_at"),
    ("savedphrase", "interval_days", "FLOAT NOT NULL DEFAULT 0", None),
    ("savedphrase", "ease", "FLOAT NOT NULL DEFAULT 2.5", None),
    ("savedphrase", "reps", "INTEGER NOT NULL DEFAULT 0", None),
    ("savedphrase", "lapses", "INTEGER NOT NULL DEFAULT 0", None),
]


def _add_missing_columns() -> None:
    """create_all only creates missing tables, not missing columns; add the ones introduced later."""
    with engine.begin() as conn:
        existing: dict[str, set[str]] = {}
        for table, column, definition, after in _LATER_COLUMNS:
            if table not in existing:
                existing[table] = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if existing[table] and column not in existing[table]:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                if after:
                    conn.execute(text(after))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
