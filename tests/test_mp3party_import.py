from pathlib import Path

from app.domain.models import Track
from app.services import mp3party_import
from app.services.mp3party_import import (
    Mp3PartyCandidate,
    Mp3PartyImportService,
)

TRACK_HTML = """
<div class="song-item track" data-a-song-id="song-11377383">
  <div class="track__user-panel"
       data-js-artist-name="Yeat"
       data-js-id="11377383"
       data-js-image="/system/artists/imgs/yeat.jpg"
       data-js-song-title="2TONE (Feat. Don Toliver)"
       data-js-url="https://dl2.mp3party.net/online/11377383.mp3">
    <div class="track__infoWrapper">
      <span class="track__info">03:40</span>
      <span class="track__info">320 kbps</span>
      <span class="track__info">8.4 МБ</span>
    </div>
  </div>
</div>
"""

TRACK_HTML_WITH_DOWNLOAD_ENDPOINT = """
<div class="song-item track" data-a-song-id="song-11377383">
  <div class="track__user-panel"
       data-js-artist-name="Yeat"
       data-js-id="11377383"
       data-js-image="/system/artists/imgs/yeat.jpg"
       data-js-song-title="2TONE (Feat. Don Toliver)"
       data-js-url="https://dl2.mp3party.net/online/11377383.mp3">
    <div class="track__infoWrapper">
      <span class="track__info">03:40</span>
    </div>
  </div>
  <a class="icon-btn js-download"
     data-download-url="https://dl2.mp3party.net/download/11377383"
     data-track-id="11377383"
     href="/music/11377383"></a>
</div>
"""

SEARCH_HTML = """
<div class="track__user-panel"
     data-js-artist-name="Yeat"
     data-js-id="11377383"
     data-js-image="/system/artists/imgs/yeat.jpg"
     data-js-song-title="2TONE (Feat. Don Toliver)"
     data-js-url="https://dl2.mp3party.net/online/11377383.mp3">
  <span class="track__info">03:40</span>
</div>
<div class="track__user-panel"
     data-js-artist-name="The Toasters"
     data-js-id="8973810"
     data-js-image=""
     data-js-song-title="2Tone Army"
     data-js-url="https://dl2.mp3party.net/online/8973810.mp3">
  <span class="track__info">03:35</span>
</div>
"""


class _FakeResponse:
    def __init__(self, body: str | bytes) -> None:
        self.body = body.encode() if isinstance(body, str) else body
        self.headers = {"Content-Length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int = -1) -> bytes:
        if not self.body:
            return b""
        body, self.body = self.body, b""
        return body


class _FakeIngestionService:
    def ingest(
        self,
        source_path: Path,
        *,
        title: str,
        artist: str,
        fallback_title: str,
        source: str,
        source_id: str,
        source_url: str,
    ) -> Track:
        return Track(
            id="track-1",
            title=title or fallback_title,
            artist=artist,
            source=source,
            source_id=source_id,
            source_url=source_url,
            local_path=str(source_path),
        )


def test_mp3party_url_detection() -> None:
    assert Mp3PartyImportService.is_supported_url(
        "https://mp3party.net/music/11377383"
    )
    assert Mp3PartyImportService.is_supported_url(
        "https://www.mp3party.net/music/11377383?from=search"
    )
    assert not Mp3PartyImportService.is_supported_url(
        "https://mp3party.net/artist/yeat"
    )
    assert not Mp3PartyImportService.is_supported_url(
        "https://mp3party.net/music/not-a-number"
    )


def test_mp3party_search_uses_q_and_parses_results(monkeypatch) -> None:
    calls: list[str] = []

    def fake_urlopen(request, *, timeout):
        assert timeout == 120
        calls.append(request.full_url)
        return _FakeResponse(SEARCH_HTML)

    monkeypatch.setattr(mp3party_import, "urlopen", fake_urlopen)

    candidates = Mp3PartyImportService(_FakeIngestionService()).search(
        " Yeat 2TONE ",
        max_results=1,
    )

    assert calls == ["https://mp3party.net/search?q=Yeat+2TONE"]
    assert len(candidates) == 1
    assert isinstance(candidates[0], Mp3PartyCandidate)
    assert candidates[0].track_id == "11377383"
    assert candidates[0].title == "2TONE (Feat. Don Toliver)"
    assert candidates[0].duration_ms == 220_000
    assert candidates[0].audio_url.endswith("/online/11377383.mp3")


def test_mp3party_direct_url_downloads_the_exposed_mp3(monkeypatch) -> None:
    page_url = "https://mp3party.net/music/11377383"
    audio_url = "https://dl2.mp3party.net/online/11377383.mp3"
    calls: list[str] = []

    def fake_urlopen(request, *, timeout):
        assert timeout == 120
        calls.append(request.full_url)
        if request.full_url == page_url:
            return _FakeResponse(TRACK_HTML)
        if request.full_url == audio_url:
            return _FakeResponse(b"ID3" + b"audio")
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr(mp3party_import, "urlopen", fake_urlopen)

    track = Mp3PartyImportService(_FakeIngestionService()).download(page_url)

    assert calls == [page_url, audio_url]
    assert track.source == "mp3party"
    assert track.source_id == "11377383"
    assert track.source_url == page_url
    assert track.title == "2TONE (Feat. Don Toliver)"


def test_mp3party_prefers_the_site_download_endpoint(monkeypatch) -> None:
    page_url = "https://mp3party.net/music/11377383"
    stream_url = "https://dl2.mp3party.net/online/11377383.mp3"
    download_url = "https://dl2.mp3party.net/download/11377383"
    calls: list[str] = []

    def fake_urlopen(request, *, timeout):
        assert timeout == 120
        calls.append(request.full_url)
        if request.full_url == page_url:
            return _FakeResponse(TRACK_HTML_WITH_DOWNLOAD_ENDPOINT)
        if request.full_url == download_url:
            return _FakeResponse(b"ID3" + b"audio")
        if request.full_url == stream_url:
            raise AssertionError("The player stream should not be used")
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr(mp3party_import, "urlopen", fake_urlopen)

    track = Mp3PartyImportService(_FakeIngestionService()).download(page_url)

    assert calls == [page_url, download_url]
    assert track.source_id == "11377383"


def test_mp3party_direct_url_selects_the_requested_track(monkeypatch) -> None:
    page_url = "https://mp3party.net/music/11377383"
    page_html = """
    <div class="track__user-panel"
         data-js-artist-name="Other"
         data-js-id="999"
         data-js-song-title="Recommendation"
         data-js-url="https://dl2.mp3party.net/online/999.mp3"></div>
    """ + TRACK_HTML + """
    <a class="c-button c-button_download js-dw-btn"
       data-track-id="11377383"
       href="https://dl2.mp3party.net/download/11377383"></a>
    """

    def fake_urlopen(request, *, timeout):
        assert request.full_url == page_url
        return _FakeResponse(page_html)

    monkeypatch.setattr(mp3party_import, "urlopen", fake_urlopen)

    candidate = Mp3PartyImportService(_FakeIngestionService()).candidate_from_url(
        page_url
    )

    assert candidate.track_id == "11377383"
    assert candidate.download_url == (
        "https://dl2.mp3party.net/download/11377383"
    )
