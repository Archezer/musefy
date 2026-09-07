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
def configure_sqlite_connection(
    dbapi_connection,
    _connection_record,
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA busy_timeout = 5000")
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

        if "mood_tags_json" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN mood_tags_json TEXT NOT NULL DEFAULT '[]'"
                )
            )

        if "mood_profiles_json" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN mood_profiles_json TEXT NOT NULL DEFAULT '[]'"
                )
            )

        if "mood_analysis_version" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN mood_analysis_version VARCHAR(50)"
                )
            )

        impression_columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "recommendation_impressions"
            )
        }

        if "feature_snapshot_json" not in impression_columns:
            connection.execute(
                text(
                    "ALTER TABLE recommendation_impressions "
                    "ADD COLUMN feature_snapshot_json "
                    "TEXT NOT NULL DEFAULT '{}'"
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

        if "cover_path" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN cover_path VARCHAR(500)"
                )
            )

        spotify_metadata_columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "spotify_track_metadata"
            )
        }

        if "cover_url" not in spotify_metadata_columns:
            connection.execute(
                text(
                    "ALTER TABLE spotify_track_metadata "
                    "ADD COLUMN cover_url TEXT"
                )
            )

        if "created_at" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE tracks "
                    "ADD COLUMN created_at DATETIME"
                )
            )
            connection.execute(
                text(
                    "UPDATE tracks SET created_at = CURRENT_TIMESTAMP "
                    "WHERE created_at IS NULL"
                )
            )

        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_tracks_source_source_id "
                "ON tracks (source, source_id)"
            )
        )

        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_interactions_user_created_at "
                "ON interactions (user_id, created_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_interactions_user_track_created_at "
                "ON interactions (user_id, track_id, created_at)"
            )
        )

        playlist_columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "playlists"
            )
        }

        if "cover_path" not in playlist_columns:
            connection.execute(
                text(
                    "ALTER TABLE playlists "
                    "ADD COLUMN cover_path VARCHAR(500)"
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

        if "recommendation_session_id" not in interaction_columns:
            connection.execute(
                text(
                    "ALTER TABLE interactions "
                    "ADD COLUMN recommendation_session_id VARCHAR(100)"
                )
            )

def create_session() -> Session:
    return SessionFactory()


if __name__ == "__main__":
    create_database()
    print("Database initialized")
