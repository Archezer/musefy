import json
from collections.abc import Callable
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import (
    Interaction,
    InteractionType,
    Track,
    User,
)
from app.storage.models import (
    InteractionRecord,
    TrackRecord,
    UserRecord,
)


class SQLAlchemyMusicStore:
    def __init__(
        self,
        session_factory: Callable[[], Session]
    ) -> None:
        self.session_factory = session_factory

    def add_user(self, user: User) -> None:
        record = UserRecord(
            id=user.id,
            display_name=user.display_name,
            created_at=user.created_at,
        )

        with self.session_factory() as session:
            session.add(record)

            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()

                raise ValueError(
                    f"User already exists: {user.id}"
                ) from error


    def get_user(self, user_id: str) -> User | None:
        with self.session_factory() as session:
            record = session.get(UserRecord, user_id)

            if record is None:
                return None

            return self._to_user(record)

    def add_track(self, track: Track) -> None:
        record = TrackRecord(
            id=track.id,
            title=track.title,
            artist=track.artist,
            genres_json=json.dumps(track.genres),
            duration_ms=track.duration_ms,
            source=track.source,
            source_url=track.source_url,
            local_path=track.local_path,
        )

        with self.session_factory() as session:
            session.add(record)

            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()

                raise ValueError(
                    f"Track already exists: {track.id}"
                ) from error

    def get_track(self, track_id: str) -> Track | None:
        with self.session_factory() as session:
            record = session.get(TrackRecord, track_id)

            if record is None:
                return None

            return self._to_track(record)

    def update_track(self, track: Track) -> None:
        with self.session_factory() as session:
            record = session.get(TrackRecord, track.id)

            if record is None:
                raise ValueError(
                    f"Track does not exist: {track.id}"
                )

            record.title = track.title
            record.artist = track.artist
            record.genres_json = json.dumps(track.genres)
            record.local_path = track.local_path

            session.commit()

    def delete_track(self, track_id: str) -> None:
        with self.session_factory() as session:
            record = session.get(TrackRecord, track_id)

            if record is None:
                raise ValueError(
                    f"Track does not exist: {track_id}"
                )

            session.delete(record)
            session.commit()

    def list_tracks(self) -> list[Track]:
        statement = select(TrackRecord).order_by(
            TrackRecord.artist,
            TrackRecord.title,
        )

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_track(record)
            for record in records
        ]

    def add_interaction(self, interaction: Interaction) -> None:

        with self.session_factory() as session:
            user = session.get(UserRecord, interaction.user_id)
            track = session.get(TrackRecord, interaction.track_id)

            if user is None:
                raise ValueError(
                    f"User does not exist: {interaction.user_id}"
                )

            if track is None:
                raise ValueError(
                    f"Track does not exist: {interaction.track_id}"
                )

            record = InteractionRecord(
                user_id=interaction.user_id,
                track_id=interaction.track_id,
                interaction_type=interaction.interaction_type.value,
                created_at=interaction.created_at,
            )

            session.add(record)
            session.commit()

    def list_interactions(self) -> list[Interaction]:
        statement = select(InteractionRecord).order_by(
            InteractionRecord.created_at
        )

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_interaction(record)
            for record in records
        ]

    @staticmethod
    def _to_track(record: TrackRecord) -> Track:
        return Track(
            id=record.id,
            title=record.title,
            artist=record.artist,
            genres=tuple(json.loads(record.genres_json)),
            duration_ms=record.duration_ms,
            source=record.source,
            source_url=record.source_url,
            local_path=record.local_path,
        )

    @staticmethod
    def _to_interaction(
        record: InteractionRecord,
    ) -> Interaction:
        created_at = record.created_at

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        return Interaction(
            user_id=record.user_id,
            track_id=record.track_id,
            interaction_type=InteractionType(
                record.interaction_type
            ),
            created_at=created_at,
        )

    @staticmethod
    def _to_user(record: UserRecord) -> User:
        created_at = record.created_at

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        return User(
            id=record.id,
            display_name=record.display_name,
            created_at=created_at,
        )
