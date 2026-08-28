from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DATABASE_PATH = Path("data/music.db")
DATABASE_PATH.parent.mkdir(
    parents=True,
    exist_ok=True,
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
    from app.storage.models import Base

    Base.metadata.create_all(engine)

def create_session() -> Session:
    return SessionFactory()


if __name__ == "__main__":
    create_database()
    print("Database initialized")