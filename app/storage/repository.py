import json
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import (
    DetectedGenre,
    Interaction,
    InteractionType,
    Playlist,
    PlaylistEntry,
    RecommendationImpression,
    SpotifyFavorite,
    SpotifyListeningStats,
    SpotifyTrackMetadata,
    Track,
    User,
)
from app.domain.mood import MoodVector
from app.domain.recommendations import RecommendationMode
from app.storage.models import (
    InteractionRecord,
    PlaylistEntryRecord,
    PlaylistRecord,
    RecommendationImpressionRecord,
    SpotifyFavoriteRecord,
    SpotifyListeningStatsRecord,
    SpotifyTrackMetadataRecord,
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

    def list_users(self) -> list[User]:
        statement = select(UserRecord).order_by(UserRecord.created_at)

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [self._to_user(record) for record in records]

    def upsert_spotify_favorite(
        self,
        favorite: SpotifyFavorite,
    ) -> None:
        statement = (
            select(SpotifyFavoriteRecord)
            .where(
                SpotifyFavoriteRecord.user_id == favorite.user_id,
                SpotifyFavoriteRecord.spotify_id == favorite.spotify_id,
            )
            .limit(1)
        )

        with self.session_factory() as session:
            record = session.scalar(statement)
            if record is None:
                session.add(
                    SpotifyFavoriteRecord(
                        user_id=favorite.user_id,
                        track_id=favorite.track_id,
                        spotify_id=favorite.spotify_id,
                        added_at=favorite.added_at,
                        imported_at=favorite.imported_at,
                        album=favorite.album,
                        isrc=favorite.isrc,
                        active=favorite.active,
                    )
                )
            else:
                record.track_id = favorite.track_id
                record.added_at = favorite.added_at
                record.imported_at = favorite.imported_at
                record.album = favorite.album
                record.isrc = favorite.isrc
                record.active = favorite.active
            session.commit()

    def list_spotify_favorites(
        self,
        user_id: str,
        *,
        active_only: bool = False,
    ) -> list[SpotifyFavorite]:
        statement = (
            select(SpotifyFavoriteRecord)
            .where(SpotifyFavoriteRecord.user_id == user_id)
            .order_by(SpotifyFavoriteRecord.added_at, SpotifyFavoriteRecord.id)
        )
        if active_only:
            statement = statement.where(SpotifyFavoriteRecord.active.is_(True))

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [self._to_spotify_favorite(record) for record in records]

    def get_spotify_track_metadata(
        self,
        spotify_id: str,
    ) -> SpotifyTrackMetadata | None:
        with self.session_factory() as session:
            record = session.get(SpotifyTrackMetadataRecord, spotify_id)

        if record is None:
            return None

        return self._to_spotify_track_metadata(record)

    def upsert_spotify_track_metadata(
        self,
        metadata: SpotifyTrackMetadata,
    ) -> None:
        with self.session_factory() as session:
            record = session.get(
                SpotifyTrackMetadataRecord,
                metadata.spotify_id,
            )
            if record is None:
                session.add(
                    SpotifyTrackMetadataRecord(
                        spotify_id=metadata.spotify_id,
                        title=metadata.title,
                        artist=metadata.artist,
                        album=metadata.album,
                        duration_ms=metadata.duration_ms,
                        added_at=metadata.added_at,
                        isrc=metadata.isrc,
                        imported_at=metadata.imported_at,
                    )
                )
            else:
                record.title = metadata.title
                record.artist = metadata.artist
                record.album = metadata.album
                record.duration_ms = metadata.duration_ms
                record.added_at = metadata.added_at
                record.isrc = metadata.isrc
                record.imported_at = metadata.imported_at
            session.commit()

    def list_spotify_track_metadata(self) -> list[SpotifyTrackMetadata]:
        statement = select(SpotifyTrackMetadataRecord).order_by(
            SpotifyTrackMetadataRecord.added_at,
            SpotifyTrackMetadataRecord.spotify_id,
        )

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_spotify_track_metadata(record)
            for record in records
        ]

    def get_spotify_listening_stats(
        self,
        spotify_id: str,
    ) -> SpotifyListeningStats | None:
        with self.session_factory() as session:
            record = session.get(SpotifyListeningStatsRecord, spotify_id)

        if record is None:
            return None

        return self._to_spotify_listening_stats(record)

    def upsert_spotify_listening_stats(
        self,
        stats: SpotifyListeningStats,
    ) -> None:
        with self.session_factory() as session:
            record = session.get(
                SpotifyListeningStatsRecord,
                stats.spotify_id,
            )
            if record is None:
                session.add(
                    SpotifyListeningStatsRecord(
                        spotify_id=stats.spotify_id,
                        play_count=stats.play_count,
                        total_ms_played=stats.total_ms_played,
                        first_played_at=stats.first_played_at,
                        last_played_at=stats.last_played_at,
                        completion_count=stats.completion_count,
                        skip_count=stats.skip_count,
                        imported_at=stats.imported_at,
                    )
                )
            else:
                record.play_count = stats.play_count
                record.total_ms_played = stats.total_ms_played
                record.first_played_at = stats.first_played_at
                record.last_played_at = stats.last_played_at
                record.completion_count = stats.completion_count
                record.skip_count = stats.skip_count
                record.imported_at = stats.imported_at
            session.commit()

    def list_spotify_listening_stats(self) -> list[SpotifyListeningStats]:
        statement = select(SpotifyListeningStatsRecord).order_by(
            SpotifyListeningStatsRecord.last_played_at,
            SpotifyListeningStatsRecord.spotify_id,
        )

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_spotify_listening_stats(record)
            for record in records
        ]

    def add_track(self, track: Track) -> None:
        record = TrackRecord(
            id=track.id,
            title=track.title,
            artist=track.artist,
            created_at=track.created_at,
            genres_json=json.dumps(track.genres),
            detected_genres_json=json.dumps(
                [
                    asdict(genre)
                    for genre in track.detected_genres
                ]
            ),
            track_embedding_json=json.dumps(
                track.track_embedding or []
            ),
            mood_valence=(
                track.mood.valence
                if track.mood is not None
                else None
            ),
            mood_arousal=(
                track.mood.arousal
                if track.mood is not None
                else None
            ),
            mood_tags_json=json.dumps(track.mood_tags),
            mood_profiles_json=json.dumps(track.mood_profiles),
            mood_analysis_version=track.mood_analysis_version,
            duration_ms=track.duration_ms,
            source=track.source,
            source_id=track.source_id,
            source_url=track.source_url,
            local_path=track.local_path,
            cover_path=track.cover_path,
            
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
            record.detected_genres_json = json.dumps(
                [
                    asdict(genre)
                    for genre in track.detected_genres
                ]
            )
            record.track_embedding_json = json.dumps(
                track.track_embedding or []
            )
            record.mood_valence = (
                track.mood.valence
                if track.mood is not None
                else None
            )
            record.mood_arousal = (
                track.mood.arousal
                if track.mood is not None
                else None
            )
            record.mood_tags_json = json.dumps(track.mood_tags)
            record.mood_profiles_json = json.dumps(track.mood_profiles)
            record.mood_analysis_version = track.mood_analysis_version
            record.local_path = track.local_path
            record.source_id = track.source_id
            record.source_url = track.source_url
            record.cover_path = track.cover_path

            session.commit()

    def get_track_by_source(
        self,
        source: str,
        source_id: str,
    ) -> Track | None:
        statement = (
            select(TrackRecord)
            .where(
                TrackRecord.source == source,
                TrackRecord.source_id == source_id,
            )
            .limit(1)
        )

        with self.session_factory() as session:
            record = session.scalar(statement)

        if record is None:
            return None

        return self._to_track(record)

    def delete_track(self, track_id: str) -> None:
        with self.session_factory() as session:
            record = session.get(TrackRecord, track_id)

            if record is None:
                raise ValueError(
                    f"Track does not exist: {track_id}"
                )

            session.execute(
                delete(SpotifyFavoriteRecord).where(
                    SpotifyFavoriteRecord.track_id == track_id
                )
            )
            session.delete(record)
            session.commit()

    def merge_track_references(
        self,
        duplicate_track_id: str,
        survivor_track_id: str,
    ) -> None:
        if duplicate_track_id == survivor_track_id:
            raise ValueError(
                "Duplicate and survivor track IDs must differ"
            )

        with self.session_factory() as session:
            duplicate = session.get(
                TrackRecord,
                duplicate_track_id,
            )
            survivor = session.get(
                TrackRecord,
                survivor_track_id,
            )

            if duplicate is None:
                raise ValueError(
                    f"Track does not exist: {duplicate_track_id}"
                )

            if survivor is None:
                raise ValueError(
                    f"Track does not exist: {survivor_track_id}"
                )

            session.execute(
                update(InteractionRecord)
                .where(
                    InteractionRecord.track_id
                    == duplicate_track_id
                )
                .values(track_id=survivor_track_id)
            )
            session.execute(
                update(PlaylistEntryRecord)
                .where(
                    PlaylistEntryRecord.track_id
                    == duplicate_track_id
                )
                .values(track_id=survivor_track_id)
            )
            session.execute(
                update(RecommendationImpressionRecord)
                .where(
                    RecommendationImpressionRecord.track_id
                    == duplicate_track_id
                )
                .values(track_id=survivor_track_id)
            )
            session.execute(
                update(SpotifyFavoriteRecord)
                .where(
                    SpotifyFavoriteRecord.track_id
                    == duplicate_track_id
                )
                .values(track_id=survivor_track_id)
            )
            session.execute(
                delete(TrackRecord).where(
                    TrackRecord.id == duplicate_track_id
                )
            )
            session.commit()

    def add_playlist(self, playlist: Playlist) -> None:
        record = PlaylistRecord(
            id=playlist.id,
            name=playlist.name,
            cover_path=playlist.cover_path,
            created_at=playlist.created_at,
        )

        with self.session_factory() as session:
            session.add(record)

            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ValueError(
                    f"Playlist already exists: {playlist.id}"
                ) from error

    def get_playlist(self, playlist_id: str) -> Playlist | None:
        with self.session_factory() as session:
            record = session.get(PlaylistRecord, playlist_id)

            if record is None:
                return None

            return self._to_playlist(record)

    def update_playlist(self, playlist: Playlist) -> None:
        with self.session_factory() as session:
            record = session.get(PlaylistRecord, playlist.id)

            if record is None:
                raise ValueError(
                    f"Playlist does not exist: {playlist.id}"
                )

            record.name = playlist.name
            record.cover_path = playlist.cover_path
            session.commit()

    def delete_playlist(self, playlist_id: str) -> None:
        with self.session_factory() as session:
            record = session.get(PlaylistRecord, playlist_id)

            if record is None:
                raise ValueError(
                    f"Playlist does not exist: {playlist_id}"
                )

            session.delete(record)
            session.commit()

    def list_playlists(self) -> list[Playlist]:
        statement = select(PlaylistRecord).order_by(
            PlaylistRecord.created_at.asc()
        )

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_playlist(record)
            for record in records
        ]

    def list_playlist_entries(
        self,
        playlist_id: str,
    ) -> list[PlaylistEntry]:
        statement = (
            select(PlaylistEntryRecord)
            .where(
                PlaylistEntryRecord.playlist_id == playlist_id
            )
            .order_by(PlaylistEntryRecord.position)
        )

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_playlist_entry(record)
            for record in records
        ]

    def replace_playlist_entries(
        self,
        playlist_id: str,
        entries: Iterable[PlaylistEntry],
    ) -> None:
        entries_to_store = tuple(entries)
        expected_positions = tuple(
            range(len(entries_to_store))
        )

        if any(
            entry.playlist_id != playlist_id
            for entry in entries_to_store
        ):
            raise ValueError(
                "Playlist entries must belong to one playlist"
            )

        if tuple(
            entry.position for entry in entries_to_store
        ) != expected_positions:
            raise ValueError(
                "Playlist entry positions must be consecutive"
            )

        with self.session_factory() as session:
            playlist = session.get(PlaylistRecord, playlist_id)

            if playlist is None:
                raise ValueError(
                    f"Playlist does not exist: {playlist_id}"
                )

            session.execute(
                delete(PlaylistEntryRecord).where(
                    PlaylistEntryRecord.playlist_id == playlist_id
                )
            )

            session.add_all(
                [
                    PlaylistEntryRecord(
                        playlist_id=entry.playlist_id,
                        track_id=entry.track_id,
                        position=entry.position,
                    )
                    for entry in entries_to_store
                ]
            )

            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ValueError(
                    "Playlist entries must reference existing tracks"
                ) from error

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
                mood_context=interaction.mood_context,
                recommendation_session_id=(
                    interaction.recommendation_session_id
                ),
                created_at=interaction.created_at,
            )

            session.add(record)
            session.commit()

    def delete_interactions(
        self,
        user_id: str,
        track_id: str,
        interaction_type: str,
    ) -> int:
        statement = delete(InteractionRecord).where(
            InteractionRecord.user_id == user_id,
            InteractionRecord.track_id == track_id,
            InteractionRecord.interaction_type == interaction_type,
        )

        with self.session_factory() as session:
            result = session.execute(statement)
            session.commit()

        return int(result.rowcount or 0)

    def compact_preference_interactions(self) -> int:
        preference_types = {
            InteractionType.LIKE.value,
            InteractionType.DISLIKE.value,
        }
        with self.session_factory() as session:
            records = session.scalars(
                select(InteractionRecord).order_by(InteractionRecord.id)
            ).all()
            latest: dict[tuple[str, str], InteractionRecord] = {}
            for record in records:
                if record.interaction_type not in preference_types:
                    continue
                state_key = (record.user_id, record.track_id)
                previous = latest.get(state_key)
                if (
                    previous is None
                    or record.created_at > previous.created_at
                    or (
                        record.created_at == previous.created_at
                        and record.id > previous.id
                    )
                ):
                    latest[state_key] = record

            removable_ids = [
                record.id
                for record in records
                if (
                    record.interaction_type in preference_types
                    and record.id
                    != latest[(record.user_id, record.track_id)].id
                )
            ]
            if not removable_ids:
                return 0

            result = session.execute(
                delete(InteractionRecord).where(
                    InteractionRecord.id.in_(removable_ids)
                )
            )
            session.commit()
            return int(result.rowcount or 0)

    def list_interactions(
        self,
        user_id: str | None = None,
    ) -> list[Interaction]:
        statement = select(InteractionRecord).order_by(
            InteractionRecord.created_at
        )
        # ``save`` was removed from the interaction model.  Keep old rows in
        # existing databases intact, but do not expose them to the domain.
        statement = statement.where(
            InteractionRecord.interaction_type != "save"
        )
        if user_id is not None:
            statement = statement.where(
                InteractionRecord.user_id == user_id
            )

        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_interaction(record)
            for record in records
        ]

    def add_recommendation_impression(
        self,
        impression: RecommendationImpression,
    ) -> None:
        with self.session_factory() as session:
            user = session.get(UserRecord, impression.user_id)
            track = session.get(TrackRecord, impression.track_id)
            if user is None:
                raise ValueError(
                    f"User does not exist: {impression.user_id}"
                )
            if track is None:
                raise ValueError(
                    f"Track does not exist: {impression.track_id}"
                )

            session.add(
                RecommendationImpressionRecord(
                    user_id=impression.user_id,
                    track_id=impression.track_id,
                    mode=impression.mode.value,
                    position=impression.position,
                    score=impression.score,
                    reason=impression.reason,
                    shown_at=impression.shown_at,
                    session_id=impression.session_id,
                )
            )
            session.commit()

    def list_recommendation_impressions(
        self,
        user_id: str | None = None,
    ) -> list[RecommendationImpression]:
        statement = select(RecommendationImpressionRecord).order_by(
            RecommendationImpressionRecord.shown_at,
            RecommendationImpressionRecord.position,
        )
        if user_id is not None:
            statement = statement.where(
                RecommendationImpressionRecord.user_id == user_id
            )
        with self.session_factory() as session:
            records = session.scalars(statement).all()

        return [
            self._to_recommendation_impression(record)
            for record in records
        ]

    @staticmethod
    def _to_track(record: TrackRecord) -> Track:
        detected_genres = tuple(
            DetectedGenre(**item)
            for item in json.loads(
                record.detected_genres_json or "[]"
            )
        )
        embedding_values = json.loads(
            record.track_embedding_json or "[]"
        )

        track_embedding = (
            tuple(float(value) for value in embedding_values)
            if embedding_values
            else None
        )

        mood = None

        if (
            record.mood_valence is not None
            and record.mood_arousal is not None
        ):
            mood = MoodVector(
                valence=float(record.mood_valence),
                arousal=float(record.mood_arousal),
            )

        mood_tags = tuple(
            (str(item[0]), float(item[1]))
            for item in json.loads(record.mood_tags_json or "[]")
            if isinstance(item, list | tuple) and len(item) >= 2
        )
        mood_profiles = tuple(
            (str(item[0]), float(item[1]))
            for item in json.loads(record.mood_profiles_json or "[]")
            if isinstance(item, list | tuple) and len(item) >= 2
        )

        return Track(
            id=record.id,
            title=record.title,
            artist=record.artist,
            created_at=record.created_at,
            genres=tuple(json.loads(record.genres_json)),
            detected_genres=detected_genres,
            track_embedding=track_embedding,
            mood=mood,
            duration_ms=record.duration_ms,
            source=record.source,
            source_id=record.source_id,
            source_url=record.source_url,
            local_path=record.local_path,
            cover_path=record.cover_path,
            mood_tags=mood_tags,
            mood_profiles=mood_profiles,
            mood_analysis_version=record.mood_analysis_version,
        )

    @staticmethod
    def _to_playlist(record: PlaylistRecord) -> Playlist:
        return Playlist(
            id=record.id,
            name=record.name,
            cover_path=record.cover_path,
            created_at=record.created_at,
        )

    @staticmethod
    def _to_playlist_entry(
        record: PlaylistEntryRecord,
    ) -> PlaylistEntry:
        return PlaylistEntry(
            playlist_id=record.playlist_id,
            track_id=record.track_id,
            position=record.position,
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
            mood_context=record.mood_context,
            recommendation_session_id=record.recommendation_session_id,
        )

    @staticmethod
    def _to_recommendation_impression(
        record: RecommendationImpressionRecord,
    ) -> RecommendationImpression:
        shown_at = record.shown_at
        if shown_at.tzinfo is None:
            shown_at = shown_at.replace(tzinfo=UTC)

        return RecommendationImpression(
            user_id=record.user_id,
            track_id=record.track_id,
            mode=RecommendationMode(record.mode),
            position=record.position,
            score=record.score,
            reason=record.reason,
            shown_at=shown_at,
            session_id=record.session_id,
        )

    @staticmethod
    def _to_spotify_listening_stats(
        record: SpotifyListeningStatsRecord,
    ) -> SpotifyListeningStats:
        first_played_at = record.first_played_at
        if first_played_at is not None and first_played_at.tzinfo is None:
            first_played_at = first_played_at.replace(tzinfo=UTC)

        last_played_at = record.last_played_at
        if last_played_at is not None and last_played_at.tzinfo is None:
            last_played_at = last_played_at.replace(tzinfo=UTC)

        imported_at = record.imported_at
        if imported_at.tzinfo is None:
            imported_at = imported_at.replace(tzinfo=UTC)

        return SpotifyListeningStats(
            spotify_id=record.spotify_id,
            play_count=record.play_count,
            total_ms_played=record.total_ms_played,
            first_played_at=first_played_at,
            last_played_at=last_played_at,
            completion_count=record.completion_count,
            skip_count=record.skip_count,
            imported_at=imported_at,
        )

    @staticmethod
    def _to_spotify_track_metadata(
        record: SpotifyTrackMetadataRecord,
    ) -> SpotifyTrackMetadata:
        added_at = record.added_at
        if added_at is not None and added_at.tzinfo is None:
            added_at = added_at.replace(tzinfo=UTC)

        imported_at = record.imported_at
        if imported_at.tzinfo is None:
            imported_at = imported_at.replace(tzinfo=UTC)

        return SpotifyTrackMetadata(
            spotify_id=record.spotify_id,
            title=record.title,
            artist=record.artist,
            album=record.album,
            duration_ms=record.duration_ms,
            added_at=added_at,
            isrc=record.isrc,
            imported_at=imported_at,
        )

    @staticmethod
    def _to_spotify_favorite(
        record: SpotifyFavoriteRecord,
    ) -> SpotifyFavorite:
        added_at = record.added_at
        if added_at is not None and added_at.tzinfo is None:
            added_at = added_at.replace(tzinfo=UTC)

        imported_at = record.imported_at
        if imported_at.tzinfo is None:
            imported_at = imported_at.replace(tzinfo=UTC)

        return SpotifyFavorite(
            user_id=record.user_id,
            track_id=record.track_id,
            spotify_id=record.spotify_id,
            added_at=added_at,
            imported_at=imported_at,
            album=record.album,
            isrc=record.isrc,
            active=record.active,
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
