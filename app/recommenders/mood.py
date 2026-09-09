from collections.abc import Callable, Collection
from datetime import UTC, datetime
from math import exp, sqrt
from random import Random

import numpy as np

from app.domain.models import (
    Interaction,
    Recommendation,
    Track,
)
from app.domain.mood import MoodVector
from app.domain.recommendations import RecommendationMode
from app.recommenders.feedback import (
    NEGATIVE_PREFERENCE_TYPES,
    PLAYBACK_SESSION_TYPES,
    POSITIVE_PREFERENCE_TYPES,
    aggregate_playback_weights,
    effective_weight,
    filter_contextual_interactions,
    latest_user_preference_states,
    suppressed_track_ids,
)
from app.recommenders.recency import recency_bonus
from app.storage.protocols import MusicStore

DEFAULT_REPLAY_COOLDOWN = 30
MOOD_DISTANCE_NORMALIZER = 2**0.5
DEFAULT_EXPLORATION_POOL_SIZE = 8
MOOD_EXPLORATION_TEMPERATURE = 0.05
MOOD_RANDOM_SCORE_GAP = 0.12
MOOD_FEEDBACK_FACTOR = 0.05
MY_WAVE_ELITE_RATIO = 0.35
MY_WAVE_MIDDLE_RATIO = 0.4
MY_WAVE_MIDDLE_POOL_MULTIPLIER = 4
MY_WAVE_MIDDLE_TEMPERATURE = 0.06
MY_WAVE_RANDOM_TEMPERATURE = 0.18
# Comparing every candidate with every historical embedding makes My Wave
# quadratic in the size of a user's listening history.  The strongest recent
# signals are enough to represent the profile while keeping the first result
# responsive for larger local libraries.
MAX_PROFILE_EMBEDDINGS = 32
class MoodRecommender:
    def __init__(
        self,
        store: MusicStore,
        replay_cooldown: int = DEFAULT_REPLAY_COOLDOWN,
        exploration_pool_size: int = (
            DEFAULT_EXPLORATION_POOL_SIZE
        ),
        random_generator: Random | None = None,
    ) -> None:
        if replay_cooldown < 0:
            raise ValueError(
                "Replay cooldown must not be negative"
            )

        if exploration_pool_size <= 0:
            raise ValueError(
                "Exploration pool size must be positive"
            )

        self.store = store
        self.replay_cooldown = replay_cooldown
        self.exploration_pool_size = exploration_pool_size
        self.random = random_generator or Random()

    def recommend(
        self,
        user_id: str,
        target_mood: MoodVector,
        limit: int = 10,
        mood_name: str | None = None,
        *,
        now: datetime | None = None,
        should_cancel: Callable[[], bool] | None = None,
        excluded_track_ids: Collection[str] | None = None,
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Recommendation limit must be positive")

        self._check_cancelled(should_cancel)
        current_time = now or datetime.now(UTC)
        interactions = self._get_context_interactions(
            user_id=user_id,
            mood_name=mood_name,
            should_cancel=should_cancel,
        )
        self._check_cancelled(should_cancel)
        all_interactions = list(
            self.store.list_interactions(user_id=user_id)
        )
        tracks = list(self.store.list_tracks())
        self._check_cancelled(should_cancel)
        permanent_track_ids, _ = suppressed_track_ids(
            user_id,
            all_interactions,
            now=current_time,
        )
        _, temporary_track_ids = suppressed_track_ids(
            user_id,
            interactions,
            now=current_time,
            context=mood_name,
        )
        cooldown_track_ids = self._get_cooldown_track_ids(
            user_id,
            interactions,
            should_cancel=should_cancel,
        )
        requested_excluded_track_ids = set(excluded_track_ids or ())
        excluded_ids = (
            permanent_track_ids
            | temporary_track_ids
            | cooldown_track_ids
            | requested_excluded_track_ids
        )

        candidates = []
        for index, track in enumerate(tracks):
            if index % 64 == 0:
                self._check_cancelled(should_cancel)
            if (
                track.mood is not None
                and track.id not in excluded_ids
            ):
                candidates.append(track)

        if not candidates:
            candidates = []
            for index, track in enumerate(tracks):
                if index % 64 == 0:
                    self._check_cancelled(should_cancel)
                if (
                    track.mood is not None
                    and track.id not in permanent_track_ids
                    and track.id not in temporary_track_ids
                    and track.id not in requested_excluded_track_ids
                ):
                    candidates.append(track)

        feedback_scores = self._get_feedback_scores(
            user_id=user_id,
            interactions=interactions,
            should_cancel=should_cancel,
        )

        scored_tracks = []
        for index, track in enumerate(candidates):
            if index % 32 == 0:
                self._check_cancelled(should_cancel)
            scored_tracks.append(
                (
                    track,
                    self._similarity(track.mood, target_mood),
                    feedback_scores.get(track.id, 0.0),
                )
            )
        scored_tracks.sort(
            key=lambda item: (
                -(
                    item[1]
                    + item[2]
                    + recency_bonus(item[0], now=current_time)
                ),
                item[0].artist.casefold(),
                item[0].title.casefold(),
            )
        )

        effective_scores = [
            (
                track,
                min(
                    1.0,
                    similarity
                    + feedback_bonus
                    + recency_bonus(track, now=current_time),
                ),
            )
            for track, similarity, feedback_bonus in scored_tracks
        ]

        selected_tracks = self._select_with_exploration(
            effective_scores,
            limit,
        )

        return [
            Recommendation(
                track=track,
                score=similarity,
                reason="Matches the selected mood",
                mode=RecommendationMode.MOOD,
                mood_similarity=self._similarity(
                    track.mood,
                    target_mood,
                ),
            )
            for track, similarity in selected_tracks
        ]

    def recommend_my_wave(
        self,
        user_id: str,
        limit: int = 10,
        *,
        now: datetime | None = None,
        should_cancel: Callable[[], bool] | None = None,
        excluded_track_ids: Collection[str] | None = None,
    ) -> list[Recommendation]:
        """Return a personalized mood/content wave for one user.

        The profile is intentionally local and explainable: positive listening
        signals form a weighted mood centroid and a small content profile from
        the user's liked/completed tracks.  A user with no history gets
        a neutral cold-start wave and can immediately start teaching it.
        """

        if limit <= 0:
            raise ValueError("Recommendation limit must be positive")

        self._check_cancelled(should_cancel)
        current_time = now or datetime.now(UTC)
        user_interactions = list(
            self.store.list_interactions(user_id=user_id)
        )
        contextual_interactions = filter_contextual_interactions(
            user_id,
            user_interactions,
            context="my_wave",
            include_global=True,
        )
        self._check_cancelled(should_cancel)
        tracks = list(self.store.list_tracks())
        self._check_cancelled(should_cancel)
        permanent_track_ids, temporary_track_ids = suppressed_track_ids(
            user_id,
            user_interactions,
            now=current_time,
            context="my_wave",
        )
        _, global_temporary_track_ids = suppressed_track_ids(
            user_id,
            user_interactions,
            now=current_time,
        )
        temporary_track_ids |= global_temporary_track_ids
        cooldown_track_ids = self._get_cooldown_track_ids(
            user_id,
            contextual_interactions,
            should_cancel=should_cancel,
        )
        requested_excluded_track_ids = set(excluded_track_ids or ())
        excluded_track_ids = (
            permanent_track_ids
            | temporary_track_ids
            | cooldown_track_ids
            | requested_excluded_track_ids
        )
        candidates = []
        for index, track in enumerate(tracks):
            if index % 64 == 0:
                self._check_cancelled(should_cancel)
            if (
                track.id not in excluded_track_ids
            ):
                candidates.append(track)
        if not candidates:
            candidates = []
            for index, track in enumerate(tracks):
                if index % 64 == 0:
                    self._check_cancelled(should_cancel)
                if (
                    track.id not in permanent_track_ids
                    and track.id not in temporary_track_ids
                    and track.id not in requested_excluded_track_ids
                ):
                    candidates.append(track)

        preference_states = latest_user_preference_states(
            user_id,
            user_interactions,
        )
        profile_weights = aggregate_playback_weights(
            user_id,
            contextual_interactions,
            now=current_time,
        )
        for track_id, interaction in preference_states.items():
            if interaction.interaction_type not in POSITIVE_PREFERENCE_TYPES:
                continue
            profile_weights[track_id] = min(
                8.0,
                profile_weights.get(track_id, 0.0)
                + max(
                    0.0,
                    effective_weight(
                        interaction,
                        now=current_time,
                    ),
                ),
            )

        feedback_scores = self._get_feedback_scores(
            user_id=user_id,
            interactions=user_interactions,
            should_cancel=should_cancel,
        )

        tracks_by_id = {track.id: track for track in tracks}
        profile_mood_valence = 0.0
        profile_mood_arousal = 0.0
        profile_weight = 0.0
        profile_embeddings: list[tuple[tuple[float, ...], float]] = []
        artist_weights: dict[str, float] = {}
        genre_weights: dict[str, float] = {}

        for track_id, weight in profile_weights.items():
            if weight <= 0.0:
                continue
            track = tracks_by_id.get(track_id)
            if track is None:
                continue

            if track.mood is not None:
                profile_mood_valence += track.mood.valence * weight
                profile_mood_arousal += track.mood.arousal * weight
                profile_weight += weight
            if track.track_embedding:
                profile_embeddings.append((track.track_embedding, weight))

            artist_key = track.artist.strip().casefold()
            if artist_key:
                artist_weights[artist_key] = (
                    artist_weights.get(artist_key, 0.0) + weight
                )
            for genre in track.genres:
                genre_key = genre.strip().casefold()
                if genre_key:
                    genre_weights[genre_key] = (
                        genre_weights.get(genre_key, 0.0) + weight
                    )

        if len(profile_embeddings) > MAX_PROFILE_EMBEDDINGS:
            profile_embeddings = sorted(
                profile_embeddings,
                key=lambda item: item[1],
                reverse=True,
            )[:MAX_PROFILE_EMBEDDINGS]

        normalized_profile_embeddings: list[
            tuple[tuple[float, ...], float]
        ] = []
        for embedding, weight in profile_embeddings:
            norm = sqrt(sum(value * value for value in embedding))
            if norm > 0.0:
                normalized_profile_embeddings.append(
                    (
                        tuple(value / norm for value in embedding),
                        weight,
                    )
                )
        profile_embeddings = normalized_profile_embeddings
        embedding_similarities = self._build_embedding_similarities(
            candidates,
            profile_embeddings,
            should_cancel=should_cancel,
        )

        profile_mood = (
            MoodVector(
                valence=max(
                    -1.0,
                    min(1.0, profile_mood_valence / profile_weight),
                ),
                arousal=max(
                    -1.0,
                    min(1.0, profile_mood_arousal / profile_weight),
                ),
            )
            if profile_weight > 0.0
            else None
        )
        max_artist_weight = max(artist_weights.values(), default=0.0)
        max_genre_weight = max(genre_weights.values(), default=0.0)

        scored_tracks: list[tuple[Track, float, float, float]] = []
        for index, track in enumerate(candidates):
            if index % 32 == 0:
                self._check_cancelled(should_cancel)
            mood_similarity = (
                self._similarity(track.mood, profile_mood)
                if profile_mood is not None
                else 0.0
            )
            embedding_similarity = embedding_similarities.get(track.id, 0.0)

            artist_affinity = (
                artist_weights.get(track.artist.strip().casefold(), 0.0)
                / max_artist_weight
                if max_artist_weight > 0.0
                else 0.0
            )
            genre_affinity = 0.0
            if max_genre_weight > 0.0:
                genre_affinity = max(
                    (
                        genre_weights.get(genre.strip().casefold(), 0.0)
                        / max_genre_weight
                    )
                    for genre in track.genres
                    if genre.strip()
                ) if any(genre.strip() for genre in track.genres) else 0.0

            affinity = max(artist_affinity, genre_affinity)
            score = (
                0.45 * mood_similarity
                + 0.40 * embedding_similarity
                + 0.15 * affinity
                + feedback_scores.get(track.id, 0.0)
                + recency_bonus(track, now=current_time)
            )
            scored_tracks.append(
                (
                    track,
                    min(1.0, max(0.0, score)),
                    mood_similarity,
                    embedding_similarity,
                )
            )

        scored_tracks.sort(
            key=lambda item: (
                -item[1],
                item[0].artist.casefold(),
                item[0].title.casefold(),
            )
        )
        selected = self._select_my_wave_diversified(
            [(track, score) for track, score, _, _ in scored_tracks],
            limit,
        )
        selected_ids = {track.id for track, _ in selected}
        components = {
            track.id: (mood_similarity, embedding_similarity)
            for track, _, mood_similarity, embedding_similarity
            in scored_tracks
        }

        reason = (
            "Based on your listening history"
            if profile_weight > 0.0 or profile_embeddings
            else "Start listening to personalize your wave"
        )
        return [
            Recommendation(
                track=track,
                score=score,
                reason=reason,
                mode=RecommendationMode.MY_WAVE,
                mood_similarity=components[track.id][0],
                embedding_similarity=components[track.id][1],
            )
            for track, score in selected
            if track.id in selected_ids
        ]

    @staticmethod
    def _build_embedding_similarities(
        candidates: list[Track],
        profile_embeddings: list[tuple[tuple[float, ...], float]],
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, float]:
        """Score candidate embeddings in one vectorized operation."""

        if not candidates or not profile_embeddings:
            return {}

        embedding_candidates = [
            track
            for track in candidates
            if track.track_embedding is not None
        ]
        if not embedding_candidates:
            return {}

        profile_dimension = len(profile_embeddings[0][0])
        if profile_dimension == 0 or any(
            len(embedding) != profile_dimension
            for embedding, _ in profile_embeddings
        ):
            return {}
        if any(
            len(track.track_embedding or ()) != profile_dimension
            for track in embedding_candidates
        ):
            return {}

        MoodRecommender._check_cancelled(should_cancel)
        profile_matrix = np.asarray(
            [embedding for embedding, _ in profile_embeddings],
            dtype=np.float32,
        )
        candidate_matrix = np.asarray(
            [track.track_embedding for track in embedding_candidates],
            dtype=np.float32,
        )
        candidate_norms = np.linalg.norm(candidate_matrix, axis=1)
        valid_candidates = candidate_norms > 0.0
        normalized_candidates = np.zeros_like(candidate_matrix)
        normalized_candidates[valid_candidates] = (
            candidate_matrix[valid_candidates]
            / candidate_norms[valid_candidates, np.newaxis]
        )
        similarity_matrix = normalized_candidates @ profile_matrix.T
        profile_weights = np.asarray(
            [weight for _, weight in profile_embeddings],
            dtype=np.float32,
        )
        MoodRecommender._check_cancelled(should_cancel)

        similarities: dict[str, float] = {}
        for index, track in enumerate(embedding_candidates):
            if index % 64 == 0:
                MoodRecommender._check_cancelled(should_cancel)
            if not valid_candidates[index]:
                continue

            closest_indices = np.argsort(
                similarity_matrix[index],
            )[::-1][:5]
            closest_similarities = (
                similarity_matrix[index, closest_indices] + 1.0
            ) / 2.0
            closest_weights = profile_weights[closest_indices]
            total_weight = float(closest_weights.sum())
            if total_weight > 0.0:
                similarities[track.id] = float(
                    np.dot(
                        closest_similarities,
                        closest_weights,
                    )
                    / total_weight
                )

        return similarities

    def _select_my_wave_diversified(
        self,
        scored_tracks: list[tuple[Track, float]],
        limit: int,
    ) -> list[tuple[Track, float]]:
        """Mix the strongest tracks with lower-ranked and fresh choices."""

        if len(scored_tracks) <= limit or limit <= 2:
            return self._select_with_exploration(scored_tracks, limit)

        elite_count = max(1, int(limit * MY_WAVE_ELITE_RATIO))
        middle_count = max(1, int(limit * MY_WAVE_MIDDLE_RATIO))
        selected = list(scored_tracks[:elite_count])
        selected_ids = {track.id for track, _ in selected}

        middle_start = elite_count
        middle_end = min(
            len(scored_tracks),
            max(
                middle_start + middle_count,
                limit * MY_WAVE_MIDDLE_POOL_MULTIPLIER,
            ),
        )
        middle_pool = [
            item
            for item in scored_tracks[middle_start:middle_end]
            if item[0].id not in selected_ids
        ]
        middle_selection = self._sample_scored_tracks(
            middle_pool,
            min(middle_count, limit - len(selected)),
            temperature=MY_WAVE_MIDDLE_TEMPERATURE,
        )
        selected.extend(middle_selection)
        selected_ids.update(track.id for track, _ in middle_selection)

        random_count = limit - len(selected)
        random_pool = [
            item
            for item in scored_tracks[middle_end:]
            if item[0].id not in selected_ids
        ]
        random_selection = self._sample_scored_tracks(
            random_pool,
            random_count,
            temperature=MY_WAVE_RANDOM_TEMPERATURE,
        )
        selected.extend(random_selection)
        selected_ids.update(track.id for track, _ in random_selection)

        if len(selected) < limit:
            selected.extend(
                item
                for item in scored_tracks
                if item[0].id not in selected_ids
            )

        return selected[:limit]

    def _sample_scored_tracks(
        self,
        candidates: list[tuple[Track, float]],
        limit: int,
        *,
        temperature: float,
    ) -> list[tuple[Track, float]]:
        """Sample without replacement while keeping higher scores favored."""

        if limit <= 0 or not candidates:
            return []

        remaining = list(candidates)
        selected: list[tuple[Track, float]] = []
        while remaining and len(selected) < limit:
            minimum_score = min(score for _, score in remaining)
            weights = [
                exp((score - minimum_score) / temperature)
                for _, score in remaining
            ]
            selected_item = self.random.choices(
                population=remaining,
                weights=weights,
                k=1,
            )[0]
            selected.append(selected_item)
            remaining.remove(selected_item)

        return selected

    @staticmethod
    def _check_cancelled(
        should_cancel: Callable[[], bool] | None,
    ) -> None:
        if should_cancel is not None and should_cancel():
            raise RuntimeError("Recommendation calculation cancelled")

    def _get_context_interactions(
        self,
        user_id: str,
        mood_name: str | None,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[Interaction]:
        normalized_mood_name = (
            mood_name.strip().casefold()
            if mood_name and mood_name.strip()
            else None
        )

        interactions: list[Interaction] = []
        for index, interaction in enumerate(
            self.store.list_interactions(user_id=user_id)
        ):
            if index % 64 == 0:
                self._check_cancelled(should_cancel)
            if (
                interaction.user_id == user_id
                and interaction.mood_context == normalized_mood_name
            ):
                interactions.append(interaction)
        return interactions

    @staticmethod
    def _get_feedback_scores(
        user_id: str,
        interactions: list[Interaction],
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, float]:
        MoodRecommender._check_cancelled(should_cancel)
        return {
            track_id: (
                -MOOD_FEEDBACK_FACTOR
                if interaction.interaction_type in NEGATIVE_PREFERENCE_TYPES
                else MOOD_FEEDBACK_FACTOR
            )
            for track_id, interaction in latest_user_preference_states(
                user_id,
                interactions,
            ).items()
            if interaction.interaction_type
            in POSITIVE_PREFERENCE_TYPES | NEGATIVE_PREFERENCE_TYPES
        }

    def _select_with_exploration(
        self,
        scored_tracks: list[tuple[Track, float]],
        limit: int,
    ) -> list[tuple[Track, float]]:
        if len(scored_tracks) <= limit:
            return scored_tracks[:limit]

        pool_size = min(
            len(scored_tracks),
            max(limit * 2, self.exploration_pool_size),
        )
        pool = scored_tracks[:pool_size]
        top_score = pool[0][1]
        eligible = [
            item
            for item in pool
            if top_score - item[1] <= MOOD_RANDOM_SCORE_GAP
        ]

        if len(eligible) <= limit:
            return scored_tracks[:limit]

        selected: list[tuple[Track, float]] = []
        remaining = list(eligible)

        while remaining and len(selected) < limit:
            minimum_score = min(
                item[1]
                for item in remaining
            )
            weights = [
                exp(
                    (item[1] - minimum_score)
                    / MOOD_EXPLORATION_TEMPERATURE
                )
                for item in remaining
            ]
            selected_item = self.random.choices(
                population=remaining,
                weights=weights,
                k=1,
            )[0]
            selected.append(selected_item)
            remaining.remove(selected_item)

        selected_ids = {
            item[0].id
            for item in selected
        }
        for item in scored_tracks:
            if len(selected) >= limit:
                break
            if item[0].id not in selected_ids:
                selected.append(item)
                selected_ids.add(item[0].id)

        return selected

    def _get_skipped_track_ids(
        self,
        user_id: str,
        interactions: list[Interaction],
        now: datetime | None = None,
    ) -> set[str]:
        _, temporary = suppressed_track_ids(
            user_id,
            interactions,
            now=now or datetime.now(UTC),
        )
        return temporary

    def _get_cooldown_track_ids(
        self,
        user_id: str,
        interactions: list[Interaction],
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> set[str]:
        if self.replay_cooldown == 0:
            return set()

        playback_history: list[Interaction] = []
        for index, interaction in enumerate(interactions):
            if index % 64 == 0:
                self._check_cancelled(should_cancel)
            if (
                interaction.user_id == user_id
                and interaction.interaction_type in PLAYBACK_SESSION_TYPES
            ):
                playback_history.append(interaction)
        playback_history.sort(
            key=lambda interaction: interaction.created_at
        )
        return {
            interaction.track_id
            for interaction in playback_history[-self.replay_cooldown :]
        }

    @staticmethod
    def _get_latest_user_interactions(
        user_id: str,
        interactions: list[Interaction],
    ) -> dict[str, Interaction]:
        latest: dict[str, Interaction] = {}
        for interaction in interactions:
            if interaction.user_id != user_id:
                continue

            previous = latest.get(interaction.track_id)
            if previous is None or interaction.created_at > previous.created_at:
                latest[interaction.track_id] = interaction

        return latest

    @staticmethod
    def _similarity(
        track_mood: MoodVector | None,
        target_mood: MoodVector,
    ) -> float:
        if track_mood is None:
            return 0.0

        return max(
            0.0,
            1.0 - track_mood.distance_to(target_mood)
            / MOOD_DISTANCE_NORMALIZER,
        )
