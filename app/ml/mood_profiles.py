from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import sqrt

from app.domain.mood import MOOD_PRESETS, MoodVector

MOOD_AFFECT_WEIGHT = 0.70
MOOD_TAG_WEIGHT = 0.05
MOOD_GENRE_WEIGHT = 0.25
MOOD_BLEND_PROFILE_LIMIT = 2

GENRE_GROUPS = {
    "melancholic": {
        "alternative": 0.7,
        "blues": 0.7,
        "emo": 1.0,
        "folk": 0.55,
        "grunge": 0.8,
        "indie": 0.75,
        "sadcore": 1.0,
        "shoegaze": 0.85,
        "singer-songwriter": 0.7,
        "slowcore": 1.0,
    },
    "calm": {
        "acoustic": 0.7,
        "ambient": 1.0,
        "classical": 0.85,
        "chillout": 1.0,
        "downtempo": 0.9,
        "easy listening": 0.9,
        "folk": 0.5,
        "jazz": 0.55,
        "lounge": 0.85,
        "new age": 1.0,
        "piano": 0.75,
        "soundtrack": 0.5,
    },
    "happy": {
        "dance": 0.8,
        "disco": 0.9,
        "funk": 0.75,
        "latin": 0.7,
        "pop": 0.75,
        "reggae": 0.65,
        "ska": 0.75,
        "soul": 0.65,
    },
    "energetic": {
        "drum & bass": 1.0,
        "electronic": 0.7,
        "hardcore": 1.0,
        "hardstyle": 1.0,
        "hip hop": 0.55,
        "metal": 0.9,
        "punk": 0.85,
        "rock": 0.75,
        "techno": 0.9,
        "trance": 0.75,
        "trap": 0.7,
    },
    "dark": {
        "alternative": 0.35,
        "black metal": 1.0,
        "darkwave": 1.0,
        "death metal": 0.9,
        "doom metal": 1.0,
        "emo": 0.65,
        "gothic": 0.95,
        "grunge": 0.65,
        "hip hop": 0.4,
        "industrial": 1.0,
        "metal": 0.7,
        "trap": 0.55,
    },
    "romantic": {
        "ballad": 0.8,
        "blues": 0.65,
        "bossa nova": 0.9,
        "contemporary r&b": 1.0,
        "flamenco": 0.8,
        "jazz": 0.55,
        "latin": 0.8,
        "pop": 0.55,
        "r&b": 1.0,
        "singer-songwriter": 0.7,
        "soul": 0.85,
    },
    "focus": {
        "ambient": 1.0,
        "classical": 0.9,
        "chillout": 0.9,
        "downtempo": 0.85,
        "electronic": 0.35,
        "jazz": 0.45,
        "new age": 0.9,
        "soundtrack": 0.65,
    },
    "party": {
        "dance": 1.0,
        "disco": 0.95,
        "edm": 0.95,
        "electronic": 0.7,
        "funk": 0.8,
        "house": 1.0,
        "hip hop": 0.5,
        "latin": 0.75,
        "pop": 0.65,
        "reggae": 0.65,
        "trap": 0.55,
    },
}

TAG_GROUPS = {
    "melancholic": {
        "sad": 1.0,
        "melancholic": 1.0,
        "ballad": 0.75,
        "slow": 0.7,
        "emotional": 0.65,
        "dramatic": 0.3,
        "soft": 0.25,
    },
    "calm": {
        "calm": 1.0,
        "relaxing": 1.0,
        "meditative": 0.9,
        "soft": 0.8,
        "ambient": 0.8,
        "peaceful": 0.8,
        "soundscape": 0.65,
        "background": 0.5,
    },
    "happy": {
        "happy": 1.0,
        "positive": 0.9,
        "upbeat": 0.85,
        "uplifting": 0.85,
        "hopeful": 0.75,
        "summer": 0.7,
        "fun": 0.5,
        "funny": 0.35,
    },
    "energetic": {
        "energetic": 1.0,
        "fast": 0.9,
        "powerful": 0.85,
        "sport": 0.8,
        "heavy": 0.75,
        "action": 0.7,
        "motivational": 0.65,
        "trailer": 0.65,
        "epic": 0.55,
    },
    "dark": {
        "dark": 1.0,
        "deep": 0.8,
        "dramatic": 0.65,
        "drama": 0.5,
        "heavy": 0.5,
        "cool": 0.25,
    },
    "romantic": {
        "love": 1.0,
        "romantic": 1.0,
        "sexy": 0.75,
        "emotional": 0.65,
        "soft": 0.35,
        "melodic": 0.3,
    },
    "focus": {
        "soundscape": 1.0,
        "background": 0.9,
        "meditative": 0.8,
        "ambient": 0.8,
        "calm": 0.6,
        "documentary": 0.35,
        "nature": 0.3,
        "space": 0.3,
    },
    "party": {
        "party": 1.0,
        "fun": 0.85,
        "groovy": 0.75,
        "upbeat": 0.65,
        "summer": 0.65,
        "happy": 0.55,
        "sport": 0.25,
    },
}


@dataclass(frozen=True)
class MoodProfilePrediction:
    profile: str
    score: float
    affect_score: float = 0.0
    tag_score: float = 0.0
    genre_score: float = 0.0


def music2emo_to_vector(
    valence: float,
    arousal: float,
) -> MoodVector:
    """Convert Music2Emo's 1..9 affect values to our -1..1 space."""
    if not 1.0 <= valence <= 9.0:
        raise ValueError("Music2Emo valence must be between 1 and 9.")

    if not 1.0 <= arousal <= 9.0:
        raise ValueError("Music2Emo arousal must be between 1 and 9.")

    return MoodVector(
        valence=(valence - 5.0) / 4.0,
        arousal=(arousal - 5.0) / 4.0,
    )


def predict_mood_profiles(
    *,
    valence: float,
    arousal: float,
    tags: Iterable[tuple[str, float]] = (),
    genres: Iterable[tuple[str, float]] = (),
    top_k: int = 3,
) -> tuple[MoodProfilePrediction, ...]:
    """Rank curated profiles using affect, tag, and genre evidence."""
    if top_k < 1:
        raise ValueError("top_k must be positive.")

    vector = music2emo_to_vector(valence, arousal)
    max_distance = sqrt(8.0)
    tag_scores = _collect_tag_scores(tags)
    genre_scores = _collect_genre_scores(genres)
    predictions = []

    for profile, target in MOOD_PRESETS.items():
        affect_score = max(
            0.0,
            1.0 - vector.distance_to(target) / max_distance,
        )
        tag_score = _tag_score(profile, tag_scores, vector)
        genre_score = _genre_score(profile, genre_scores)
        score = (
            MOOD_AFFECT_WEIGHT * affect_score
            + MOOD_TAG_WEIGHT * tag_score
            + MOOD_GENRE_WEIGHT * genre_score
        )
        predictions.append(
            MoodProfilePrediction(
                profile=profile,
                score=score,
                affect_score=affect_score,
                tag_score=tag_score,
                genre_score=genre_score,
            )
        )

    predictions.sort(key=lambda item: item.score, reverse=True)
    return tuple(predictions[:top_k])


def blend_mood_with_profiles(
    affect_vector: MoodVector,
    profiles: Iterable[MoodProfilePrediction],
    *,
    weight: float = 0.25,
) -> MoodVector:
    """Add a small profile/tag correction to Music2Emo's affect vector."""
    if not 0.0 <= weight <= 1.0:
        raise ValueError("Profile blend weight must be between 0 and 1.")

    ranked_profiles = sorted(
        (
            item
            for item in profiles
            if item.profile in MOOD_PRESETS and item.score > 0.0
        ),
        key=lambda item: item.score,
        reverse=True,
    )[:MOOD_BLEND_PROFILE_LIMIT]
    if not ranked_profiles or weight == 0.0:
        return affect_vector

    profile_weights = [item.score**2 for item in ranked_profiles]
    total_weight = sum(profile_weights)
    if total_weight <= 0.0:
        return affect_vector

    centroid = MoodVector(
        valence=sum(
            item_weight * MOOD_PRESETS[item.profile].valence
            for item, item_weight in zip(
                ranked_profiles,
                profile_weights,
                strict=True,
            )
        ) / total_weight,
        arousal=sum(
            item_weight * MOOD_PRESETS[item.profile].arousal
            for item, item_weight in zip(
                ranked_profiles,
                profile_weights,
                strict=True,
            )
        ) / total_weight,
    )
    confidence = weight * min(1.0, ranked_profiles[0].score)

    return MoodVector(
        valence=(1.0 - confidence) * affect_vector.valence
        + confidence * centroid.valence,
        arousal=(1.0 - confidence) * affect_vector.arousal
        + confidence * centroid.arousal,
    )


def _collect_tag_scores(
    tags: Iterable[tuple[str, float]],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for raw_tag, score in tags:
        tag = raw_tag.rsplit("---", maxsplit=1)[-1].strip().casefold()
        scores[tag] = max(scores.get(tag, 0.0), float(score))
    return scores


def _collect_genre_scores(
    genres: Iterable[tuple[str, float]],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for raw_genre, score in genres:
        label = str(raw_genre).strip()
        if not label:
            continue

        parts = [part.strip() for part in label.split("---", maxsplit=1)]
        components = {part.casefold() for part in parts if part}
        bounded_score = max(0.0, min(1.0, float(score)))
        for component in components:
            scores[component] = max(
                scores.get(component, 0.0),
                bounded_score,
            )
    return scores


def _genre_score(
    profile: str,
    genre_scores: dict[str, float],
) -> float:
    aliases = GENRE_GROUPS.get(profile, {})
    evidence = sorted(
        (
            genre_scores.get(alias, 0.0) * relevance
            for alias, relevance in aliases.items()
            if genre_scores.get(alias, 0.0) > 0.0
        ),
        reverse=True,
    )
    multipliers = (1.0, 0.25, 0.1)
    weighted_evidence = list(
        zip(evidence[:3], multipliers, strict=False)
    )
    total_multiplier = sum(
        multiplier
        for _, multiplier in weighted_evidence
    )
    return (
        sum(
            contribution * multiplier
            for contribution, multiplier in weighted_evidence
        ) / total_multiplier
        if total_multiplier > 0.0
        else 0.0
    )


def _tag_score(
    profile: str,
    tag_scores: dict[str, float],
    vector: MoodVector,
) -> float:
    aliases = TAG_GROUPS.get(profile, {})
    evidence = sorted(
        (
            tag_scores.get(alias, 0.0) * relevance
            for alias, relevance in aliases.items()
        ),
        reverse=True,
    )
    multipliers = (1.0, 0.25, 0.1)
    weighted_evidence = list(
        zip(evidence[:3], multipliers, strict=False)
    )
    total_multiplier = sum(
        multiplier
        for _, multiplier in weighted_evidence
    )
    score = (
        sum(
            contribution * multiplier
            for contribution, multiplier in weighted_evidence
        ) / total_multiplier
        if total_multiplier > 0.0
        else 0.0
    )

    if profile in {"happy", "party", "romantic"} and vector.valence < 0:
        score *= 0.35

    if profile in {"melancholic", "dark"} and vector.valence > 0.2:
        score *= 0.35

    if profile == "calm" and vector.valence < -0.3:
        score *= 0.55

    if profile in {"calm", "focus"} and vector.arousal > 0.35:
        score *= 0.55

    if profile in {"dark", "energetic", "party"} and vector.arousal < -0.25:
        score *= 0.55

    return score
