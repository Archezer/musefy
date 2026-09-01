from typing import Protocol

from app.domain.models import Recommendation


class Recommender(Protocol):
    def recommend(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Recommendation]:
        ...
