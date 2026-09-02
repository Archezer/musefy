import json
from pathlib import Path

from app.services.playlist_exports import read_playlist_export


def test_playlist_export_reads_optional_cover_url(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "playlist.json"
    export_path.write_text(
        json.dumps(
            {
                "format": "music-recommendation-system.spotify-playlist",
                "playlist": {
                    "source": "spotify",
                    "title": "Night drive",
                    "url": "https://open.spotify.com/playlist/example",
                    "cover_url": "https://i.scdn.co/image/example",
                },
                "tracks": [
                    {
                        "position": 1,
                        "artist": "Artist",
                        "title": "Track",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    playlist = read_playlist_export(export_path)

    assert playlist.cover_url == "https://i.scdn.co/image/example"
