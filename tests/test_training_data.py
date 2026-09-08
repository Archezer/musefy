from datetime import UTC, datetime, timedelta

from app.domain.models import (
    Interaction,
    InteractionType,
    Playlist,
    PlaylistEntry,
    Recommendation,
    RecommendationImpression,
    SpotifyListeningStats,
    SpotifyTrackMetadata,
    Track,
    User,
)
from app.domain.mood import MoodVector
from app.domain.recommendations import RecommendationMode
from app.ml.feature_snapshot import (
    RECOMMENDATION_FEATURE_NAMES,
    build_recommendation_feature_snapshot,
)
from app.ml.training_data import (
    build_ranker_dataset,
    make_synthetic_ranker_dataset,
    split_ranker_dataset_by_time,
)
from app.storage.memory import InMemoryMusicStore


def test_dataset_uses_only_explicit_post_impression_reactions() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    for track_id in ("positive", "negative", "unknown"):
        store.add_track(Track(id=track_id, title=track_id, artist="Artist"))

    shown_at = datetime(2026, 1, 1, tzinfo=UTC)
    for position, track_id in enumerate(
        ("positive", "negative", "unknown"),
        start=1,
    ):
        store.add_recommendation_impression(
            RecommendationImpression(
                user_id="user-1",
                track_id=track_id,
                mode=RecommendationMode.POPULARITY,
                position=position,
                score=0.5,
                shown_at=shown_at,
                feature_snapshot=(("candidate_quality", position / 10),),
            )
        )

    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="positive",
            interaction_type=InteractionType.PLAYED_30S,
            created_at=shown_at + timedelta(minutes=1),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="negative",
            interaction_type=InteractionType.DISLIKE,
            created_at=shown_at + timedelta(minutes=2),
        )
    )

    dataset = build_ranker_dataset(store)

    assert len(dataset.examples) == 2
    assert [example.label for example in dataset.examples] == [1, 0]
    assert dataset.examples[0].track_id == "positive"
    assert dataset.examples[1].track_id == "negative"
    assert all(
        example.mode == RecommendationMode.POPULARITY
        for example in dataset.examples
    )
    assert len(dataset.as_matrix()) == 2


def test_dataset_ignores_save_and_future_feature_values() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    track = Track(id="track-1", title="One", artist="Artist")
    store.add_track(track)
    shown_at = datetime(2026, 1, 1, tzinfo=UTC)
    store.add_recommendation_impression(
        RecommendationImpression(
            user_id="user-1",
            track_id=track.id,
            mode=RecommendationMode.POPULARITY,
            position=1,
            score=0.5,
            shown_at=shown_at,
            feature_snapshot=(("plays_before_show", 0.0),),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id=track.id,
            interaction_type="save",  # Legacy value: never a training label.
            created_at=shown_at + timedelta(minutes=1),
        )
    )

    dataset = build_ranker_dataset(store)

    assert dataset.examples == ()


def test_synthetic_dataset_is_reproducible_and_time_split_is_strict() -> None:
    dataset = make_synthetic_ranker_dataset(
        user_count=3,
        examples_per_user=6,
        seed=11,
    )
    same_dataset = make_synthetic_ranker_dataset(
        user_count=3,
        examples_per_user=6,
        seed=11,
    )
    train, validation = split_ranker_dataset_by_time(
        dataset,
        train_fraction=0.5,
    )

    assert dataset == same_dataset
    assert {example.user_id for example in dataset.examples} == {
        "synthetic-user-0",
        "synthetic-user-1",
        "synthetic-user-2",
    }
    assert train.examples[-1].shown_at < validation.examples[0].shown_at


def test_feature_snapshot_contains_only_data_known_at_show_time() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    track = Track(
        id="track-1",
        title="One",
        artist="Artist",
        source_id="spotify-1",
    )
    store.add_track(track)
    shown_at = datetime(2026, 1, 1, tzinfo=UTC)
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id=track.id,
            interaction_type=InteractionType.LIKE,
            created_at=shown_at - timedelta(days=1),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id=track.id,
            interaction_type=InteractionType.LIKE,
            created_at=shown_at + timedelta(days=1),
        )
    )
    store.upsert_spotify_listening_stats(
        SpotifyListeningStats(
            spotify_id="spotify-1",
            play_count=4,
            total_ms_played=120_000,
        )
    )

    snapshot = build_recommendation_feature_snapshot(
        store,
        user_id="user-1",
        recommendation=Recommendation(
            track=track,
            score=0.7,
            reason="baseline",
            mode=RecommendationMode.POPULARITY,
        ),
        position=2,
        shown_at=shown_at,
    )
    values = dict(snapshot)

    assert tuple(name for name, _ in snapshot) == RECOMMENDATION_FEATURE_NAMES
    assert values["user_interaction_count_before_show"] == 1.0
    assert values["user_track_interaction_count_before_show"] == 1.0
    assert values["spotify_play_count"] == 4.0


def test_feature_snapshot_resolves_spotify_history_by_metadata() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    track = Track(
        id="track-1",
        title="Focus Track",
        artist="Artist",
        duration_ms=180_000,
        source="youtube",
        source_id="youtube-video-1",
    )
    store.add_track(track)
    store.upsert_spotify_track_metadata(
        SpotifyTrackMetadata(
            spotify_id="spotify-1",
            title="Focus Track",
            artist="Artist",
            duration_ms=181_000,
        )
    )
    store.upsert_spotify_listening_stats(
        SpotifyListeningStats(
            spotify_id="spotify-1",
            play_count=7,
            completion_count=5,
        )
    )

    snapshot = build_recommendation_feature_snapshot(
        store,
        user_id="user-1",
        recommendation=Recommendation(
            track=track,
            score=0.7,
            reason="metadata match",
        ),
        position=1,
        shown_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    values = dict(snapshot)
    assert values["spotify_has_history"] == 1.0
    assert values["spotify_play_count"] == 7.0
    assert values["spotify_completion_count"] == 5.0


def test_feature_snapshot_contains_playlist_context_features() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_playlist(Playlist(id="playlist-1", name="Ambient set"))
    store.add_track(
        Track(
            id="playlist-track",
            title="Playlist track",
            artist="Artist",
            genres=("ambient",),
            mood=MoodVector(valence=0.2, arousal=0.3),
            track_embedding=(1.0, 0.0),
        )
    )
    candidate = Track(
        id="candidate",
        title="Candidate",
        artist="Artist",
        genres=("ambient",),
        mood=MoodVector(valence=0.2, arousal=0.3),
        track_embedding=(1.0, 0.0),
    )
    store.add_track(candidate)
    store.replace_playlist_entries(
        "playlist-1",
        [PlaylistEntry(playlist_id="playlist-1", track_id="playlist-track", position=0)],
    )

    snapshot = build_recommendation_feature_snapshot(
        store,
        user_id="user-1",
        recommendation=Recommendation(
            track=candidate,
            score=0.7,
            reason="playlist context",
        ),
        position=1,
        shown_at=datetime(2026, 1, 1, tzinfo=UTC),
        playlist_id="playlist-1",
    )
    values = dict(snapshot)

    assert values["playlist_context_available"] == 1.0
    assert values["playlist_track_membership"] == 0.0
    assert values["playlist_mood_similarity"] == 1.0
    assert values["playlist_embedding_similarity"] == 1.0
    assert values["playlist_genre_similarity"] > 0.0
