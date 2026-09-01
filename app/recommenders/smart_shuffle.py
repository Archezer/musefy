from collections.abc import Sequence

from app.domain.models import Track
from app.recommenders.similarity import (
    TrackSimilarityIndex,
    cosine_similarity,
)


class SmartShuffleBuilder:
    def __init__(
        self,
        tracks: Sequence[Track],
        similarity_index: TrackSimilarityIndex,
    ) -> None:
        self.tracks_by_id = {
            track.id: track
            for track in tracks
            if track.track_embedding is not None
        }
        self.similarity_index = similarity_index

    def build(
        self,
        playlist_track_ids: Sequence[str],
    ) -> tuple[str, ...]:
        base_track_ids = tuple(playlist_track_ids)
        used_track_ids = set(base_track_ids)
        result: list[str] = []

        for start in range(0, len(base_track_ids), 2):
            pair = base_track_ids[start:start + 2]
            result.extend(pair)

            if len(pair) < 2:
                continue

            bridge_track_id = self._find_bridge(
                pair,
                used_track_ids,
            )

            if bridge_track_id is not None:
                result.append(bridge_track_id)
                used_track_ids.add(bridge_track_id)

        return tuple(result)

    def _find_bridge(
        self,
        pair: Sequence[str],
        used_track_ids: set[str],
    ) -> str | None:
        if any(
            track_id not in self.tracks_by_id
            for track_id in pair
        ):
            return None

        candidate_ids: set[str] = set()

        for track_id in pair:
            candidate_ids.update(
                neighbor.track_id
                for neighbor in self.similarity_index.neighbors_for(
                    track_id
                )
            )

        candidates = [
            self.tracks_by_id[track_id]
            for track_id in candidate_ids
            if track_id not in used_track_ids
        ]

        if not candidates:
            return None

        pair_embeddings = [
            self.tracks_by_id[track_id].track_embedding
            for track_id in pair
        ]

        return max(
            candidates,
            key=lambda candidate: sum(
                cosine_similarity(
                    candidate.track_embedding or (),
                    embedding or (),
                )
                for embedding in pair_embeddings
            ) / len(pair_embeddings),
        ).id
