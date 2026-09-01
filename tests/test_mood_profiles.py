import pytest

from app.domain.mood import MoodVector
from app.ml.mood_profiles import (
    MoodProfilePrediction,
    blend_mood_with_profiles,
    music2emo_to_vector,
    predict_mood_profiles,
)


def test_music2emo_affect_is_normalized_to_domain_vector() -> None:
    assert music2emo_to_vector(1.0, 9.0) == MoodVector(-1.0, 1.0)


def test_dark_tag_can_prioritize_dark_profile() -> None:
    predictions = predict_mood_profiles(
        valence=3.5,
        arousal=6.5,
        tags=(
            ("mood/theme---dark", 0.75),
            ("mood/theme---love", 0.74),
        ),
    )

    assert predictions[0].profile == "dark"


def test_happy_tag_can_prioritize_party_profile() -> None:
    predictions = predict_mood_profiles(
        valence=6.6,
        arousal=6.8,
        tags=(
            ("mood/theme---party", 0.86),
            ("mood/theme---happy", 0.83),
        ),
    )

    assert predictions[0].profile == "party"


def test_top_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="top_k"):
        predict_mood_profiles(
            valence=5.0,
            arousal=5.0,
            top_k=0,
        )


def test_raw_music2emo_tags_can_describe_a_profile() -> None:
    predictions = predict_mood_profiles(
        valence=5.0,
        arousal=7.0,
        tags=(
            ("mood/theme---powerful", 0.9),
            ("mood/theme---sport", 0.8),
            ("mood/theme---fast", 0.75),
        ),
    )

    assert predictions[0].profile == "energetic"


def test_parent_and_subgenre_have_equal_genre_evidence() -> None:
    predictions = predict_mood_profiles(
        valence=5.0,
        arousal=5.0,
        genres=(("R&B---Contemporary R&B", 0.8),),
    )

    romantic = next(
        item
        for item in predictions
        if item.profile == "romantic"
    )

    assert romantic.genre_score == pytest.approx(0.8)


def test_genre_evidence_can_prioritize_a_mood_profile() -> None:
    predictions = predict_mood_profiles(
        valence=5.0,
        arousal=5.0,
        genres=(("Electronic---House", 0.9),),
    )

    assert predictions[0].profile == "party"


def test_profile_evidence_corrects_the_affect_vector() -> None:
    affect_vector = MoodVector(valence=0.8, arousal=-0.2)

    enriched_vector = blend_mood_with_profiles(
        affect_vector,
        (MoodProfilePrediction(profile="dark", score=1.0),),
    )

    assert enriched_vector.valence < affect_vector.valence
    assert enriched_vector.arousal > affect_vector.arousal


def test_profile_blend_uses_only_the_two_strongest_profiles() -> None:
    affect_vector = MoodVector(valence=0.0, arousal=0.0)
    top_profiles = (
        MoodProfilePrediction(profile="dark", score=0.8),
        MoodProfilePrediction(profile="energetic", score=0.7),
    )
    profiles_with_third = (
        *top_profiles,
        MoodProfilePrediction(profile="melancholic", score=0.1),
    )

    assert blend_mood_with_profiles(
        affect_vector,
        top_profiles,
    ) == blend_mood_with_profiles(
        affect_vector,
        profiles_with_third,
    )
