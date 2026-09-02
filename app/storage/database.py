from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.storage.paths import (
    DATABASE_PATH,
    ensure_storage_directories,
)

DATABASE_URL = (
    f"sqlite:///{DATABASE_PATH.resolve().as_posix()}"
)

engine = create_engine(
    DATABASE_URL,
    echo=False,
)

@event.listens_for(engine, "connect")
def enable_foreign_keys(
    dbapi_connection,
    _connection_record,
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()

SessionFactory = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def create_database() -> None:
    ensure_storage_directories()

    from app.storage.models import Base

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "tracks"
            )
        }

        if "detected_genres_json" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN detected_genres_json "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            )

        if "track_embedding_json" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN track_embedding_json "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            )

        columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "tracks"
            )
        }

        if "mood_valence" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN mood_valence REAL"
                )
            )

        if "mood_arousal" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN mood_arousal REAL"
                )
            )

        columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "tracks"
            )
        }

        if "source_id" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN source_id VARCHAR(255)"
                )
            )

        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_tracks_source_source_id "
                "ON tracks (source, source_id)"
            )
        )

        interaction_columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "interactions"
            )
        }

        if "mood_context" not in interaction_columns:
            connection.execute(
                text(
                    "ALTER TABLE interactions "
                    "ADD COLUMN mood_context VARCHAR(50)"
                )
            )

def create_session() -> Session:
    return SessionFactory()


if __name__ == "__main__":
    create_database()
    print("Database initialized")
