from collections.abc import Callable, Collection

from app.domain.models import Recommendation, Track
from app.domain.mood import MoodVector
from app.domain.recommendations import (
    RecommendationContext,
    RecommendationMode,
)
from app.recommenders.mood import MoodRecommender
from app.recommenders.protocols import Recommender
from app.services.track_similarity import TrackSimilarityService


class RecommendationService:
    def __init__(
        self,
        recommender: Recommender,
        mood_recommender: MoodRecommender | None = None,
        track_radio: TrackSimilarityService | None = None,
    ) -> None:
        self.recommender = recommender
        self.mood_recommender = mood_recommender
        self.track_radio = track_radio

    def refresh(self) -> None:
        if self.track_radio is not None:
            # Track radio performs a cheap seed-to-library search on demand.
            # Rebuilding the complete all-pairs index here made refreshes
            # block the UI even though radio does not need that index.
            self.track_radio.invalidate()

    def update_track(self, track: Track) -> None:
        if self.track_radio is not None:
            self.track_radio.update_track(track)

    def remove_track(self, track_id: str) -> None:
        if self.track_radio is not None:
            self.track_radio.remove_track(track_id)

    def get_recommendations(
        self,
        user_id: str,
        limit: int = 10,
        context: RecommendationContext | None = None,
        target_mood: MoodVector | None = None,
        should_cancel: Callable[[], bool] | None = None,
        excluded_track_ids: Collection[str] | None = None,
    ) -> list[Recommendation]:
        normalized_user_id = user_id.strip()

        if not normalized_user_id:
            raise ValueError("User ID must not be empty")

        if context is not None and target_mood is not None:
            raise ValueError(
                "Pass either context or target_mood, not both."
            )

        if context is None:
            context = (
                RecommendationContext.mood(target_mood)
                if target_mood is not None
                else RecommendationContext()
            )

        if context.mode == RecommendationMode.MOOD:
            if self.mood_recommender is None:
                raise RuntimeError("Mood recommender is not configured.")
            assert context.target_mood is not None
            if should_cancel is None:
                return self.mood_recommender.recommend(
                    user_id=normalized_user_id,
                    target_mood=context.target_mood,
                    limit=limit,
                    mood_name=context.mood_name,
                )
            return self.mood_recommender.recommend(
                user_id=normalized_user_id,
                target_mood=context.target_mood,
                limit=limit,
                mood_name=context.mood_name,
                should_cancel=should_cancel,
            )

        if context.mode == RecommendationMode.MY_WAVE:
            if self.mood_recommender is None:
                raise RuntimeError("Mood recommender is not configured.")
            if should_cancel is None:
                return self.mood_recommender.recommend_my_wave(
                    user_id=normalized_user_id,
                    limit=limit,
                )
            return self.mood_recommender.recommend_my_wave(
                user_id=normalized_user_id,
                limit=limit,
                should_cancel=should_cancel,
            )

        if context.mode == RecommendationMode.GENRE:
            genre_recommender = getattr(
                self.recommender,
                "recommend_genre",
                None,
            )
            if genre_recommender is None:
                raise RuntimeError("Genre recommender is not configured.")
            assert context.genre_name is not None
            return genre_recommender(
                user_id=normalized_user_id,
                genre_name=context.genre_name,
                limit=limit,
                should_cancel=should_cancel,
            )

        if context.mode == RecommendationMode.TRACK_RADIO:
            if self.track_radio is None:
                raise RuntimeError("Track radio is not configured.")
            assert context.seed_track_id is not None
            return self.track_radio.recommendations_for(
                context.seed_track_id,
                limit=limit,
                user_id=normalized_user_id,
                excluded_track_ids=excluded_track_ids,
                should_cancel=should_cancel,
            )

        return self.recommender.recommend(
            user_id=normalized_user_id,
            limit=limit,
        )
