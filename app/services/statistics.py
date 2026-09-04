"""Interesting, explainable listening statistics for the desktop dashboard."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.domain.models import InteractionType
from app.storage.protocols import MusicStore


@dataclass(frozen=True)
class ListeningStat:
    label: str
    subtitle: str = ""
    count: int = 0
    duration_ms: int = 0


@dataclass(frozen=True)
class ListeningStatistics:
    period_start: datetime
    period_end: datetime
    completed_listens: int
    listening_ms: int
    active_days: int
    new_finds: tuple[ListeningStat, ...]
    top_tracks: tuple[ListeningStat, ...]
    favorite_artists: tuple[ListeningStat, ...]
    favorite_genres: tuple[ListeningStat, ...]
    skipped_tracks: tuple[ListeningStat, ...]
    skipped_count: int
    liked_tracks: int
    daily: tuple[DailyListeningStatistics, ...] = ()
    monthly: tuple[MonthlyListeningStatistics, ...] = ()


@dataclass(frozen=True)
class DailyListeningStatistics:
    day: date
    listening_ms: int = 0
    completed_listens: int = 0
    skipped: int = 0
    track_count: int = 0
    top_tracks: tuple[ListeningStat, ...] = ()
    top_artists: tuple[ListeningStat, ...] = ()
    top_genres: tuple[ListeningStat, ...] = ()


@dataclass(frozen=True)
class MonthlyListeningStatistics:
    month: date
    listening_ms: int = 0
    completed_listens: int = 0
    skipped: int = 0
    track_count: int = 0
    top_genre: str = ""
    top_tracks: tuple[ListeningStat, ...] = ()


class ListeningStatisticsService:
    """Compute a rolling 30-day snapshot from durable interactions."""

    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def build(
        self,
        user_id: str,
        *,
        now: datetime | None = None,
        days: int = 30,
    ) -> ListeningStatistics:
        period_end = (now or datetime.now(UTC)).astimezone(UTC)
        period_start = (
            period_end.replace(hour=0, minute=0, second=0, microsecond=0)
            - timedelta(days=max(1, days) - 1)
        )
        tracks = {track.id: track for track in self.store.list_tracks()}
        interactions = [
            interaction
            for interaction in self.store.list_interactions()
            if interaction.user_id == user_id
            and period_start <= self._as_utc(interaction.created_at) <= period_end
        ]

        listen_counts: Counter[str] = Counter()
        listen_dates: set[object] = set()
        skipped_counts: Counter[str] = Counter()
        liked_count = 0
        listening_ms = 0
        daily_listens: dict[date, Counter[str]] = defaultdict(Counter)
        daily_skips: Counter[date] = Counter()
        daily_durations: dict[date, Counter[str]] = defaultdict(Counter)
        daily_genres: dict[date, Counter[str]] = defaultdict(Counter)

        for interaction in interactions:
            track = tracks.get(interaction.track_id)
            if track is None:
                continue
            interaction_type = interaction.interaction_type
            if interaction_type == InteractionType.LISTEN:
                listen_counts[track.id] += 1
                interaction_day = self._as_utc(interaction.created_at).date()
                listen_dates.add(interaction_day)
                duration_ms = track.duration_ms or 0
                listening_ms += duration_ms
                daily_listens[interaction_day][track.id] += 1
                daily_durations[interaction_day][track.id] += duration_ms
                for genre in track.genres:
                    if genre.strip():
                        daily_genres[interaction_day][genre.strip().casefold()] += 1
            elif interaction_type == InteractionType.SKIP:
                skipped_counts[track.id] += 1
                daily_skips[self._as_utc(interaction.created_at).date()] += 1
            elif interaction_type == InteractionType.LIKE:
                liked_count += 1

        top_tracks = tuple(
            ListeningStat(
                label=tracks[track_id].title,
                subtitle=tracks[track_id].artist,
                count=count,
                duration_ms=(tracks[track_id].duration_ms or 0) * count,
            )
            for track_id, count in listen_counts.most_common(8)
        )

        artist_counts: Counter[str] = Counter()
        genre_counts: Counter[str] = Counter()
        for track_id, count in listen_counts.items():
            track = tracks[track_id]
            artist_counts[track.artist] += count
            for genre in track.genres:
                if genre.strip():
                    genre_counts[genre.strip().casefold()] += count

        favorite_artists = tuple(
            ListeningStat(label=artist, count=count)
            for artist, count in artist_counts.most_common(8)
        )
        favorite_genres = tuple(
            ListeningStat(label=genre.title(), count=count)
            for genre, count in genre_counts.most_common(8)
        )
        skipped_tracks = tuple(
            ListeningStat(
                label=tracks[track_id].title,
                subtitle=tracks[track_id].artist,
                count=count,
            )
            for track_id, count in skipped_counts.most_common(8)
        )

        new_find_ids = sorted(
            (
                track
                for track in tracks.values()
                if period_start <= self._as_utc(track.created_at) <= period_end
            ),
            key=lambda track: (
                listen_counts.get(track.id, 0),
                self._as_utc(track.created_at),
            ),
            reverse=True,
        )
        new_finds = tuple(
            ListeningStat(
                label=track.title,
                subtitle=track.artist,
                count=listen_counts.get(track.id, 0),
            )
            for track in new_find_ids[:8]
        )

        # The grid is exactly ``days`` calendar cells, including today.
        first_day = period_end.date() - timedelta(days=max(1, days) - 1)
        daily: list[DailyListeningStatistics] = []
        for offset in range(max(1, days)):
            day = first_day + timedelta(days=offset)
            counts = daily_listens.get(day, Counter())
            daily_track_stats = tuple(
                ListeningStat(
                    label=tracks[track_id].title,
                    subtitle=tracks[track_id].artist,
                    count=count,
                    duration_ms=daily_durations[day][track_id],
                )
                for track_id, count in counts.most_common(5)
                if track_id in tracks
            )
            artist_counts_for_day: Counter[str] = Counter()
            for track_id, count in counts.items():
                if track_id in tracks:
                    artist_counts_for_day[tracks[track_id].artist] += count
            daily.append(
                DailyListeningStatistics(
                    day=day,
                    listening_ms=sum(daily_durations[day].values()),
                    completed_listens=sum(counts.values()),
                    skipped=daily_skips.get(day, 0),
                    track_count=len(counts),
                    top_tracks=daily_track_stats,
                    top_artists=tuple(
                        ListeningStat(label=artist, count=count)
                        for artist, count in artist_counts_for_day.most_common(5)
                    ),
                    top_genres=tuple(
                        ListeningStat(label=genre.title(), count=count)
                        for genre, count in daily_genres[day].most_common(5)
                    ),
                )
            )

        monthly = self._build_monthly_statistics(user_id, period_end)

        return ListeningStatistics(
            period_start=period_start,
            period_end=period_end,
            completed_listens=sum(listen_counts.values()),
            listening_ms=listening_ms,
            active_days=len(listen_dates),
            new_finds=new_finds,
            top_tracks=top_tracks,
            favorite_artists=favorite_artists,
            favorite_genres=favorite_genres,
            skipped_tracks=skipped_tracks,
            skipped_count=sum(skipped_counts.values()),
            liked_tracks=liked_count,
            daily=tuple(daily),
            monthly=monthly,
        )

    def _build_monthly_statistics(
        self,
        user_id: str,
        period_end: datetime,
    ) -> tuple[MonthlyListeningStatistics, ...]:
        """Build twelve calendar-month bars for the month view."""

        current_month = period_end.date().replace(day=1)
        months = tuple(
            self._shift_month(current_month, offset)
            for offset in range(-11, 1)
        )
        month_start = datetime(
            months[0].year,
            months[0].month,
            1,
            tzinfo=UTC,
        )
        tracks = {track.id: track for track in self.store.list_tracks()}
        interactions = [
            interaction
            for interaction in self.store.list_interactions()
            if interaction.user_id == user_id
            and month_start
            <= self._as_utc(interaction.created_at)
            <= period_end
        ]
        listen_counts: dict[date, Counter[str]] = defaultdict(Counter)
        durations: dict[date, Counter[str]] = defaultdict(Counter)
        genre_counts: dict[date, Counter[str]] = defaultdict(Counter)
        skips: Counter[date] = Counter()
        for interaction in interactions:
            track = tracks.get(interaction.track_id)
            if track is None:
                continue
            timestamp = self._as_utc(interaction.created_at)
            month = timestamp.date().replace(day=1)
            if interaction.interaction_type == InteractionType.LISTEN:
                listen_counts[month][track.id] += 1
                durations[month][track.id] += track.duration_ms or 0
                for genre in track.genres:
                    if genre.strip():
                        genre_counts[month][genre.strip().casefold()] += 1
            elif interaction.interaction_type == InteractionType.SKIP:
                skips[month] += 1

        results: list[MonthlyListeningStatistics] = []
        for month in months:
            counts = listen_counts[month]
            results.append(
                MonthlyListeningStatistics(
                    month=month,
                    listening_ms=sum(durations[month].values()),
                    completed_listens=sum(counts.values()),
                    skipped=skips[month],
                    track_count=len(counts),
                    top_genre=(
                        genre_counts[month].most_common(1)[0][0].title()
                        if genre_counts[month]
                        else ""
                    ),
                    top_tracks=tuple(
                        ListeningStat(
                            label=tracks[track_id].title,
                            subtitle=tracks[track_id].artist,
                            count=count,
                            duration_ms=durations[month][track_id],
                        )
                        for track_id, count in counts.most_common(5)
                    ),
                )
            )
        return tuple(results)

    @staticmethod
    def _shift_month(value: date, offset: int) -> date:
        month_index = value.year * 12 + value.month - 1 + offset
        year, month_index = divmod(month_index, 12)
        return date(year, month_index + 1, 1)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
