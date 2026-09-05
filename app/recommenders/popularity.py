from collections import defaultdict
from datetime import UTC, datetime
from math import exp
from random import Random

from app.domain.models import (
    Interaction,
    InteractionType,
    Recommendation,
    Track,
)
from app.domain.recommendations import RecommendationMode
from app.recommenders.feedback import (
    DEFAULT_INTEREST_HALF_LIFE_DAYS,
    PLAYBACK_INTERACTION_TYPES,
    PLAYBACK_SESSION_TYPES,
    aggregate_user_track_weights,
    effective_weight,
    latest_preference_state_indices,
    suppressed_track_ids,
)
from app.recommenders.protocols import Recommender
from app.storage.protocols import MusicStore

DEFAULT_REPLAY_COOLDOWN = 30
DEFAULT_EXPLORATION_POOL_SIZE = 30
EXPLORATION_TEMPERATURE = 2.0
ARTIST_PREFERENCE_FACTOR = 0.5
GENRE_PREFERENCE_FACTOR = 0.5
PARENT_GENRE_RELEVANCE = 0.5
SUBGENRE_RECOMMENDATION_MIN_SCORE = 0.25

class MostPopularRecommender(Recommender):
    def __init__(
        self,
        store: MusicStore,
        replay_cooldown: int = DEFAULT_REPLAY_COOLDOWN,
        exploration_pool_size: int = (
            DEFAULT_EXPLORATION_POOL_SIZE
        ),
        random_generator: Random | None = None,
        interest_half_life_days: float = DEFAULT_INTEREST_HALF_LIFE_DAYS,
    ) -> None:
        if replay_cooldown < 0:
            raise ValueError(
                "Replay cooldown must not be negative"
            )

        if exploration_pool_size <= 0:
            raise ValueError(
                "Exploration pool size must be positive"
            )

        if interest_half_life_days <= 0:
            raise ValueError(
                "Interest half-life must be positive"
            )

        self.store = store
        self.replay_cooldown = replay_cooldown
        self.exploration_pool_size = (
            exploration_pool_size
        )
        self.random = random_generator or Random()
        self.interest_half_life_days = interest_half_life_days

    def _get_cooldown_track_ids(
        self,
        user_id: str,
        interactions: list[Interaction],
    ) -> set[str]:
        if self.replay_cooldown == 0:
            return set()

        playback_history = [
            interaction
            for interaction in interactions
            if (
                interaction.user_id == user_id
                and interaction.interaction_type
                in PLAYBACK_SESSION_TYPES
            )
        ]

        playback_history.sort(key=lambda interaction: interaction.created_at)

        recent_playback = playback_history[
            -self.replay_cooldown:
        ]

        return {
            interaction.track_id
            for interaction in recent_playback
        }


    def _select_with_exploration(
        self,
        candidates: list[Track],
        track_scores: dict[str, float],
        limit: int,
    ) -> list[Track]:
        pool_size = max(
            limit,
            self.exploration_pool_size,
        )

        pool = candidates[:pool_size]
        selected_tracks: list[Track] = []

        while pool and len(selected_tracks) < limit:
            minimum_score = min(
                track_scores[track.id]
                for track in pool
            )

            weights = [
                exp(
                    (
                        track_scores[track.id]
                        - minimum_score
                    )
                    / EXPLORATION_TEMPERATURE
                )
                for track in pool
            ]

            selected_track = self.random.choices(
                population=pool,
                weights=weights,
                k=1,
            )[0]

            selected_tracks.append(selected_track)
            pool.remove(selected_track)

        return selected_tracks


    def _get_user_genre_scores(
        self,
        user_id: str,
        interactions: list[Interaction],
        now: datetime,
    ) -> dict[str, float]:
        genre_scores: dict[str, float] = defaultdict(float)
        track_weights = aggregate_user_track_weights(
            user_id,
            interactions,
            now=now,
            half_life_days=self.interest_half_life_days,
        )

        for track_id, weight in track_weights.items():
            track = self.store.get_track(track_id)

            if track is None:
                continue

            for genre, relevance in (
                self._get_track_genre_features(track).items()
            ):
                genre_scores[genre] += (
                    weight
                    * GENRE_PREFERENCE_FACTOR
                    * relevance
                )

        return genre_scores

    @staticmethod
    def _get_track_genre_features(
        track: Track,
    ) -> dict[str, float]:
        features: dict[str, float] = {}

        if track.detected_genres:
            for prediction in track.detected_genres:
                full_genre = prediction.genre.strip().casefold()
                parent_genre = (
                    prediction.parent_genre.strip().casefold()
                )

                relevance = max(
                    prediction.weighted_score,
                    0.0,
                )

                if (
                    full_genre
                    and (
                        not prediction.subgenre
                        or prediction.score
                        >= SUBGENRE_RECOMMENDATION_MIN_SCORE
                    )
                ):
                    features[full_genre] = max(
                        features.get(full_genre, 0.0),
                        relevance,
                    )

                if parent_genre:
                    features[parent_genre] = max(
                        features.get(parent_genre, 0.0),
                        relevance * PARENT_GENRE_RELEVANCE,
                    )

            return features

        for genre in track.genres:
            normalized_genre = genre.strip().casefold()

            if not normalized_genre:
                continue

            features[normalized_genre] = max(
                features.get(normalized_genre, 0.0),
                1.0,
            )

            parent_genre, separator, _ = (
                normalized_genre.partition("---")
            )

            if separator and parent_genre:
                features[parent_genre] = max(
                    features.get(parent_genre, 0.0),
                    PARENT_GENRE_RELEVANCE,
                )

        return features


    def _get_user_artist_scores(
        self,
        user_id: str,
        interactions: list[Interaction],
        now: datetime,
    ) -> dict[str, float]:
        artist_scores: dict[str, float] = defaultdict(float)
        track_weights = aggregate_user_track_weights(
            user_id,
            interactions,
            now=now,
            half_life_days=self.interest_half_life_days,
        )

        for track_id, weight in track_weights.items():
            track = self.store.get_track(track_id)

            if track is None:
                continue

            artist_scores[track.artist] += weight * ARTIST_PREFERENCE_FACTOR

        return artist_scores

    def _get_last_played_at(
        self,
        user_id: str,
        interactions: list[Interaction]
    ) -> dict[str, float]:
        last_played_at: dict[str, float] = {}

        for interaction in interactions:
            if (
                interaction.user_id == user_id
                and interaction.interaction_type
                in PLAYBACK_INTERACTION_TYPES
            ):
                played_at = (
                    interaction.created_at.timestamp()
                )

                last_played_at[interaction.track_id] = max(
                    last_played_at.get(
                        interaction.track_id,
                        float("-inf"),
                    ),
                    played_at,
                )

        return last_played_at


    def recommend(
        self,
        user_id: str,
        limit: int = 10,
        *,
        now: datetime | None = None,
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Recommendation limit must be positive")

        current_time = now or datetime.now(UTC)
        all_interactions = list(self.store.list_interactions())
        interactions = [
            interaction
            for interaction in all_interactions
            if interaction.mood_context is None
        ]
        suppression_interactions = [
            interaction
            for interaction in all_interactions
            if interaction.mood_context is None
            or interaction.interaction_type
            in {
                InteractionType.DO_NOT_RECOMMEND,
                InteractionType.ALLOW_RECOMMEND,
            }
        ]
        tracks = list(self.store.list_tracks())

        track_scores: dict[str, float] = defaultdict(float)
        latest_state_indices = latest_preference_state_indices(interactions)

        for index, interaction in enumerate(interactions):
            if interaction.interaction_type in {
                InteractionType.LIKE,
                InteractionType.SAVE,
                InteractionType.DISLIKE,
            }:
                state_key = (interaction.user_id, interaction.track_id)
                if latest_state_indices.get(state_key) != index:
                    continue

            # Permanent hide/restore decisions belong to one user and must
            # never change global popularity for everyone else.
            if interaction.interaction_type in {
                InteractionType.DO_NOT_RECOMMEND,
                InteractionType.ALLOW_RECOMMEND,
            }:
                continue
            if (
                interaction.interaction_type == InteractionType.DISLIKE
                and interaction.user_id != user_id
            ):
                continue

            track_scores[interaction.track_id] += (
                effective_weight(
                    interaction,
                    now=current_time,
                    half_life_days=self.interest_half_life_days,
                )
            )

        user_artist_scores = (
            self._get_user_artist_scores(
                user_id=user_id,
                interactions=interactions,
                now=current_time,
            )
        )

        for track in tracks:
            track_scores[track.id] += (
                user_artist_scores.get(
                    track.artist,
                    0.0,
                )
            )

        user_genre_scores = (
            self._get_user_genre_scores(
                user_id=user_id,
                interactions=interactions,
                now=current_time,
            )
        )

        for track in tracks:
            genres = self._get_track_genre_features(track)
            genre_weight = sum(genres.values())

            if not genres or genre_weight <= 0:
                continue

            genre_bonus = sum(
                user_genre_scores.get(genre, 0.0)
                * relevance
                for genre, relevance in genres.items()
            ) / genre_weight

            track_scores[track.id] += genre_bonus

        cooldown_track_ids = (
            self._get_cooldown_track_ids(
                user_id=user_id,
                interactions=interactions,
            )
        )

        permanent_track_ids, temporary_track_ids = suppressed_track_ids(
            user_id,
            suppression_interactions,
            now=current_time,
        )

        excluded_track_ids = (
            permanent_track_ids | temporary_track_ids | cooldown_track_ids
        )

        candidate_tracks = [
            track for track in tracks
            if track.id not in excluded_track_ids
        ]

        fallback_used = not candidate_tracks

        if fallback_used:
            candidate_tracks = [
                track for track in tracks
                if (
                    track.id not in permanent_track_ids
                    and track.id not in temporary_track_ids
                )
            ]

        last_played_at = self._get_last_played_at(
            user_id=user_id,
            interactions=interactions,
        )

        if fallback_used:
            candidate_tracks.sort(
                key=lambda track: (
                    last_played_at.get(
                        track.id,
                        float("-inf"),
                    ),
                    -track_scores[track.id],
                    track.artist,
                    track.title,
                )
            )
        else:
            candidate_tracks.sort(
                key=lambda track: (
                    -track_scores[track.id],
                    track.artist,
                    track.title,
                )
            )

        selected_tracks = (
            self._select_with_exploration(
                candidates=candidate_tracks,
                track_scores=track_scores,
                limit=limit,
            )
        )

        recommendations = []

        for track in selected_tracks:
            score = track_scores[track.id]

            artist_bonus = user_artist_scores.get(
                track.artist,
                0.0
            )
            
            genres = self._get_track_genre_features(track)

            genre_bonus = sum(
                user_genre_scores.get(genre, 0.0)
                * relevance
                for genre, relevance in genres.items()
            )

            if artist_bonus > 0:
                reason = (
                    f"Matches your favorite artist: "
                    f"{track.artist}"
                )
            elif genre_bonus > 0:
                reason = "Matches your preferred genres"
            elif score > 0:
                reason = "Popular among users"
            else:
                reason = "Not enough interaction data"

            recommendations.append(
                Recommendation(
                    track=track,
                    score=score,
                    reason=reason,
                    mode=RecommendationMode.POPULARITY,
                    popularity_score=score,
                )
            )

        return recommendations
