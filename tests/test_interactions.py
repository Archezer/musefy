from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import (
    Interaction,
    InteractionType,
    Track,
    User,
)
from app.services.interactions import InteractionService
from app.storage.memory import InMemoryMusicStore


def test_record_like_creates_interaction():
    store = InMemoryMusicStore()

    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )

    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )

    service = InteractionService(store)

    result = service.record(
        user_id="user-1",
        track_id="track-1",
        interaction_type=InteractionType.LIKE,
    )

    assert result.created is True
    assert (
        result.interaction.interaction_type
        == InteractionType.LIKE
    )
    assert len(store.list_interactions()) == 1


def test_record_like_is_idempotent():
    store = InMemoryMusicStore()

    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )

    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )

    service = InteractionService(store)

    first_result = service.record(
        "user-1",
        "track-1",
        InteractionType.LIKE,
    )

    second_result = service.record(
        "user-1",
        "track-1",
        InteractionType.LIKE,
    )

    assert first_result.created is True
    assert second_result.created is False
    assert len(store.list_interactions()) == 1


def test_record_rejects_unknown_user():
    store = InMemoryMusicStore()

    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )

    service = InteractionService(store)

    with pytest.raises(
        ValueError,
        match="User does not exist: user-404",
    ):
        service.record(
            user_id="user-404",
            track_id="track-1",
            interaction_type=InteractionType.LIKE,
        )


def test_record_rejects_unknown_track():
    store = InMemoryMusicStore()

    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )

    service = InteractionService(store)

    with pytest.raises(
        ValueError,
        match="Track does not exist: track-404",
    ):
        service.record(
            user_id="user-1",
            track_id="track-404",
            interaction_type=InteractionType.LIKE,
        )


def test_record_skip_creates_interaction():
    store = InMemoryMusicStore()

    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )

    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )

    result = InteractionService(store).record(
        user_id="user-1",
        track_id="track-1",
        interaction_type=InteractionType.SKIP,
    )

    assert result.created is True
    assert (
        result.interaction.interaction_type
        == InteractionType.SKIP
    )


def test_record_save_is_idempotent():
    store = InMemoryMusicStore()

    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )

    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )

    service = InteractionService(store)

    first_result = service.record(
        "user-1",
        "track-1",
        InteractionType.SAVE,
    )

    second_result = service.record(
        "user-1",
        "track-1",
        InteractionType.SAVE,
    )

    assert first_result.created is True
    assert second_result.created is False
    assert len(store.list_interactions()) == 1


def test_stateful_interactions_are_idempotent_per_mood_context():
    store = InMemoryMusicStore()
    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )
    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )

    service = InteractionService(store)

    sad_result = service.record(
        "user-1",
        "track-1",
        InteractionType.LIKE,
        mood_context=" Sad ",
    )
    repeated_sad_result = service.record(
        "user-1",
        "track-1",
        InteractionType.LIKE,
        mood_context="sad",
    )
    happy_result = service.record(
        "user-1",
        "track-1",
        InteractionType.LIKE,
        mood_context="happy",
    )

    assert sad_result.created is True
    assert repeated_sad_result.created is False
    assert happy_result.created is True
    assert len(store.list_interactions()) == 2


def test_like_state_can_be_read_and_removed_across_mood_contexts():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )
    service = InteractionService(store)

    service.record(
        "user-1",
        "track-1",
        InteractionType.LIKE,
        mood_context="calm",
    )
    service.record(
        "user-1",
        "track-1",
        InteractionType.LIKE,
        mood_context="energy",
    )

    assert service.is_liked("user-1", "track-1") is True
    assert service.remove_like("user-1", "track-1") is True
    assert service.is_liked("user-1", "track-1") is False
    assert store.list_interactions() == []


def test_latest_dislike_clears_like_button_state():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )
    service = InteractionService(store)

    service.record("user-1", "track-1", InteractionType.LIKE)
    service.record("user-1", "track-1", InteractionType.DISLIKE)

    assert service.is_liked("user-1", "track-1") is False


def test_preference_compaction_keeps_latest_state_and_playback_history():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="track-1",
            title="Test Track",
            artist="Test Artist",
        )
    )
    timestamp = datetime(2026, 9, 5, tzinfo=UTC)
    store.add_interaction(
        Interaction(
            "user-1",
            "track-1",
            InteractionType.LIKE,
            timestamp,
        )
    )
    store.add_interaction(
        Interaction(
            "user-1",
            "track-1",
            InteractionType.LIKE,
            timestamp + timedelta(seconds=1),
        )
    )
    store.add_interaction(
        Interaction(
            "user-1",
            "track-1",
            InteractionType.DISLIKE,
            timestamp + timedelta(seconds=2),
        )
    )
    store.add_interaction(
        Interaction(
            "user-1",
            "track-1",
            InteractionType.PLAY_START,
            timestamp + timedelta(seconds=3),
        )
    )
    service = InteractionService(store)

    plan = service.preference_compaction_plan()

    assert plan.redundant_records == 2
    assert plan.affected_tracks == 1
    assert service.compact_preference_history() == 2
    assert [
        interaction.interaction_type
        for interaction in store.list_interactions()
    ] == [InteractionType.DISLIKE, InteractionType.PLAY_START]
