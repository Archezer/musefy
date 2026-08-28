from app.domain.models import Recommendation
from app.recommenders.protocols import Recommender


class RecommendationService:
    def __init__(self, recommender: Recommender) -> None:
        self.recommender = recommender

    def get_recommendations(
            self,
            user_id: str,
            limit: int = 10
    ) -> list[Recommendation]:
        normalized_user_id = user_id.strip()

        if not normalized_user_id:
            raise ValueError("User ID must not be empty")

        return self.recommender.recommend(
            user_id=normalized_user_id,
            limit=limit,
        )