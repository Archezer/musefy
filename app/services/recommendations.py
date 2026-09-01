from app.domain.models import Recommendation
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
            self.track_radio.rebuild()

    def get_recommendations(
        self,
        user_id: str,
        limit: int = 10,
        context: RecommendationContext | None = None,
        target_mood: MoodVector | None = None,
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
            return self.mood_recommender.recommend(
                user_id=normalized_user_id,
                target_mood=context.target_mood,
                limit=limit,
            )

        if context.mode == RecommendationMode.TRACK_RADIO:
            if self.track_radio is None:
                raise RuntimeError("Track radio is not configured.")
            assert context.seed_track_id is not None
            return self.track_radio.recommendations_for(
                context.seed_track_id,
                limit=limit,
            )

        return self.recommender.recommend(
            user_id=normalized_user_id,
            limit=limit,
        )
