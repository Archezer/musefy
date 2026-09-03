# Musefy

A Windows desktop application for a **local music library**. It imports audio
from files, YouTube, Spotify and SoundCloud links, analyses each track locally, and builds
recommendations without uploading the library or listening history to a cloud
service.

The app is designed around three complementary signals:

- **MAEST** generates genre predictions and a 768-dimensional musical embedding
  for every track;
- **Music2Emo** estimates valence, arousal and mood-oriented tags;
- local playback events and playlist context personalise ranking over time.

The project is a personal-library tool. Respect YouTube, Spotify, SoundCloud and copyright
rules when importing content.

## Features

- Import local audio files (`mp3`, `m4a`, `mp4`, `flac`, `wav`, `ogg`, `opus`).
- Search YouTube, import a direct YouTube link, or load a YouTube playlist.
- Import a Spotify track, album or playlist: Spotify supplies metadata, then
  the app searches YouTube for matching audio candidates.
- Search SoundCloud, load a direct track URL, or load a SoundCloud set and
  choose which tracks to import through `yt-dlp`.
- Use Firefox YouTube cookies automatically when a browser session is required.
- Analyse new tracks in the background with CUDA when it is available.
- Store genre hierarchy, mood profile and one reusable MAEST embedding per
  track in a local SQLite database.
- Browse the library, create playlists, delete tracks, and manage a separate
  playback queue.
- Play normally, shuffle, smart shuffle, or start a mood session.
- Get three recommendation styles: global recommendations, track radio, and
  mood-first recommendations.

## How the recommendation system works

Analysis happens once when a track is added or when **Reanalyze all** is used.
The resulting features are saved locally, so ordinary recommendations do not
run a neural network again.

```text
audio file
  ├─ MAEST ──────> genre predictions + 768-D embedding
  └─ Music2Emo ──> valence, arousal, mood tags and mood profiles
                         ↓
                  local SQLite database
                         ↓
playback / likes / skips / playlists / selected mood
                         ↓
                     ranked queue
```

### Global recommendations

The main library recommendation feed combines local interactions, artist and
genre affinity, exploration, and cooldown rules. It intentionally learns from
the library the user actually owns.

### Track radio

Starting radio from a track ranks other tracks primarily by cosine similarity
of their MAEST embeddings. This is useful when the user wants music that sounds
musically close to the selected track, regardless of its popularity score.

### Mood sessions

Mood sessions prioritise mood features rather than the global library score.
Feedback inside a mood session is stored separately, so liking a calm study
track does not make it dominate the general library feed. The available profiles
include melancholic, calm, happy, energetic, dark, romantic, focus and party.

### Queue and smart shuffle

Shuffle never rewrites a playlist. It creates a temporary playback order in the
queue. Smart shuffle also inserts a suitable bridge track from the library after
every two playlist tracks, while leaving the original playlist untouched.

The **Back** button restarts the current track when it has already progressed;
press it again to return to the previous queue item. **Next** only moves through
the queue; **Skip** additionally records negative feedback.

## Requirements

- Windows 10/11 x64;
- Python 3.12 or 3.13;
- [uv](https://docs.astral.sh/uv/);
- FFmpeg shared build for TorchCodec audio decoding;
- NVIDIA GPU with a current driver is strongly recommended for fast analysis;
- Firefox is recommended for reliable YouTube authentication when YouTube asks
  to verify the browser session.

PyTorch, CUDA runtime packages and ONNX Runtime GPU are installed by the Python
environment. A separate CUDA Toolkit is normally not required, but the NVIDIA
driver must be present.

## Installation

Clone the repository and enter it:

```powershell
git clone https://github.com/Archezer/music-recommendation-system.git
cd music-recommendation-system
```

Install the locked Python environment:

```powershell
$env:UV_CACHE_DIR = "$pwd\.uv-cache"
uv sync --locked
```

### Install FFmpeg

Install the shared Windows build used by TorchCodec:

```powershell
winget install --id Gyan.FFmpeg.Shared -e
```

Close and reopen the terminal (or VS Code), then verify it:

```powershell
ffmpeg -version
```

If PowerShell still cannot find `ffmpeg`, make sure the package's `bin` folder
is in `PATH`, then reopen the terminal again. This is a system installation,
not a package to add through `uv`.

### Add the model files

Large model weights are deliberately excluded from Git. Download the approved
artifacts from their official sources and place them at these paths before
running analysis:

```text
data/models/maest/maest.onnx
data/models/music2emo/inference/data/btc_model_large_voca.pt
```

The exact files used by Musefy are:

- [MAEST 30s, PaSST, 519 styles (ONNX)](https://essentia.upf.edu/models/feature-extractors/maest/discogs-maest-30s-pw-519l-2.onnx)
  (about 348 MB), saved as `data/models/maest/maest.onnx`;
- [Music2Emo chord model](https://huggingface.co/amaai-lab/music2emo/resolve/main/inference/data/btc_model_large_voca.pt?download=true)
  (about 12 MB), saved as
  `data/models/music2emo/inference/data/btc_model_large_voca.pt`.

From PowerShell, both files can be downloaded in one step after `uv sync
--locked`:

```powershell
New-Item -ItemType Directory -Force `
  data\models\maest, data\models\music2emo\inference\data

curl.exe -L --fail -o data\models\maest\maest.onnx `
  "https://essentia.upf.edu/models/feature-extractors/maest/discogs-maest-30s-pw-519l-2.onnx"

curl.exe -L --fail -o data\models\music2emo\inference\data\btc_model_large_voca.pt `
  "https://huggingface.co/amaai-lab/music2emo/resolve/main/inference/data/btc_model_large_voca.pt?download=true"
```

The repository already contains the MAEST labels and Music2Emo support files,
including `saved_models/J_all.ckpt`. The MERT backbone is downloaded
automatically by Transformers on the first analysis from
[`m-a-p/MERT-v1-95M`](https://huggingface.co/m-a-p/MERT-v1-95M); that first
analysis therefore requires an Internet connection and several hundred MB of
free disk space. Do not commit model binaries, cookies, tokens, your database,
or audio library; `.gitignore` excludes them on purpose.

The model licenses are different, so review the linked model cards before
redistributing a bundle: MAEST is CC BY-NC-SA 4.0, Music2Emo is Apache 2.0,
and MERT is CC BY-NC 4.0.

### Optional CUDA check

```powershell
uv run python -c "import torch, onnxruntime as ort; print('Torch CUDA:', torch.cuda.is_available()); print('ONNX providers:', ort.get_available_providers())"
```

For GPU inference, the output should include `Torch CUDA: True` and
`CUDAExecutionProvider`. The app automatically falls back to CPU if CUDA is
unavailable, but genre and mood analysis will be much slower.

## Run the desktop app

```powershell
uv run python -m app.desktop
```

### Build a pinned Windows bundle

The repository includes the flat turquoise lyre mark (`assets/musefy-lyre.svg`)
and its dark tile background (`assets/musefy-background.png`). A repeatable
PyInstaller script combines them into the Windows ICO. From the project
environment, run:

```powershell
uv run python scripts/build_musefy.py
```

For a one-click build from Explorer, double-click `build_musefy.bat` in the
project root. It uses the local `.venv` when available and otherwise falls
back to `uv`.

The portable onedir bundle is written to `dist/Musefy/Musefy.exe`. User data
and ML models are intentionally kept outside the executable because they can
be very large; copy a `data/` folder next to the executable or set
`MUSEFY_DATA_DIR`. Right-click `Musefy.exe` in Explorer and choose **Pin to
taskbar** (or **Create shortcut**). If Windows still shows an old icon, unpin
the previous Musefy shortcut and pin the freshly built executable again; the
taskbar can cache shortcut icons.

The app stores its local state in:

```text
data/music.db                 SQLite library, playlists and interactions
data/library/                 imported audio files
data/youtube_cookies.txt      optional exported YouTube cookies
data/spotify_token.json       optional Spotify OAuth token
```

None of these files are meant to be committed or shared.

## Importing music

Open **Add from YouTube or Spotify** from the desktop app. The dialog accepts a
search query or one URL and detects the source automatically.

### Local files

Use the local-file import action and select supported audio files. The app
copies them into `data/library/`, reads tags where possible, saves the track in
the database, and schedules analysis in the background.

### YouTube search and direct URLs

- Enter text and press **Search** to review YouTube candidates.
- Paste a normal YouTube video URL and press **Load** to import its audio.
- Paste a canonical playlist URL such as
  `https://www.youtube.com/playlist?list=...` and press **Load** to retrieve
  its items before downloading selected tracks.

The importer requests audio-only formats and prefers M4A/AAC where available;
it does not intentionally save the full video. A YouTube video already present
in the library is recognised by source ID, so it is not duplicated. If the
database record exists but the local audio file was removed, importing it again
restores that record's file.

Playlist import shows successful and failed items and offers a retry for failed
ones. Some videos may still be unavailable because they are private,
region-restricted, age-restricted, removed, or require a browser session.

#### Firefox cookies for YouTube

YouTube occasionally returns an error such as *“Sign in to confirm you're not
a bot.”* The app first tries to read cookies from the default Firefox profile.

1. Install Firefox if needed.
2. Sign in to YouTube in Firefox and confirm the browser can open the target
   video normally.
3. **Close Firefox completely** before importing in the app.
4. Retry the import.

Firefox locks its cookie database while it is running; this is why closing it is
required at the moment of cookie extraction. You do not need to keep Firefox
closed while listening to music. Open it again after the import if you like;
for another import that needs fresh browser cookies, close it again first.

If Firefox cannot be used, export your own fresh YouTube cookies in Netscape
cookie-file format to `data/youtube_cookies.txt`, then retry. An alternative
location can be configured with:

```powershell
$env:YTDLP_COOKIES_FILE = "C:\path\to\youtube_cookies.txt"
```

Cookie files and browser sessions are sensitive credentials. Never commit them,
send them to another person, or use cookies from an account you do not control.

### Spotify links and authorization

Paste a Spotify track, album or playlist URL into the same URL field and press
**Load**.

Spotify is used for **track metadata and playlist order**, not as an audio
download source. For every Spotify item, the app searches YouTube, lets the
user review candidates where appropriate, and imports the matched audio from
YouTube. Check each match and make sure your use complies with the platforms'
terms and applicable law.

Public Spotify links can often work without authentication. Spotify OAuth is
recommended for a more reliable metadata fallback and is required for private
or collaborative playlists that your account can access.

#### Configure Spotify OAuth once

1. Create an application in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Add this Redirect URI to the application's settings exactly:

   ```text
   http://127.0.0.1:8888/callback
   ```

3. Copy `.env.example` to `.env` in the project root and set the client ID:

   ```dotenv
   SPOTIFY_CLIENT_ID=your_spotify_client_id
   SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
   ```

4. In the import dialog, use **Authenticate** with a Spotify URL. The app opens
   the default browser, uses OAuth with PKCE, and waits for the local callback.
5. Approve access. The token is stored locally in `data/spotify_token.json` and
   used automatically by later Spotify imports.

No Spotify client secret is required. If the Spotify application is still in
Development Mode, add the Spotify account as a test user in the Developer
Dashboard. Never commit `.env` or `data/spotify_token.json`.

### SoundCloud search and downloads

In the import dialog, enter an artist/title query and click **Search SoundCloud**.
The app shows the first five matching tracks; select one and click **Download
selected**. A pasted SoundCloud track URL is downloaded directly. A pasted
`/sets/…` URL is resolved into its tracks, which can be selected individually
before downloading. The app imports each resulting audio file into the local
library and never stores the temporary download directory.

Use this only for tracks you own or have explicit permission to download. Some
tracks do not expose a downloadable file, so SoundCloud or `yt-dlp` can still
reject the request. Musefy first requests SoundCloud's original uploaded file,
then falls back to a full-length audio stream; it refuses preview-only streams
instead of importing a 30-second clip. For a private or account-restricted
track, set `SOUNDCLOUD_OAUTH_TOKEN` or `SOUNDCLOUD_COOKIES_FILE` in `.env` using
credentials for an account authorized to access that track. The integration
intentionally skips playlists.

### VK Music, Spotify and Yandex Music browser exporter

The development extension in
[`extensions/vk-spotify-playlist-exporter`](extensions/vk-spotify-playlist-exporter) exports
the visible metadata of the currently open VK Music, Spotify or Yandex Music playlist to a
JSON file. When the desktop app is running, the extension sends the export to a
localhost bridge and saves it under `playlist_exports/<source>` next to the
`extensions` folder. If the app is not
running, it falls back to the browser's Downloads folder. It collects only track order, artist, title and duration; it does not
read cookies, tokens, audio URLs or audio files.

In the desktop app, click **Import exported playlist** and select one of these
JSON files. The app then reuses the existing YouTube search, download, library
analysis and local-playlist pipeline, while reporting tracks that could not be
matched or downloaded.

For Spotify, this is an alternative to API-based metadata import: it works from
the user's already-open Spotify Web Player and therefore does not require the
project's Spotify client ID, OAuth callback, or Dashboard test-user allowlist.
Install and usage instructions are in the extension's
[README](extensions/vk-spotify-playlist-exporter/README.md).

## Analysis pipeline

New and restored tracks are analysed asynchronously, so the UI remains usable
while another track is being imported.

1. Audio is decoded to mono 16 kHz.
2. The track is split into overlapping 30-second windows; it is not reduced to
   only its first 30 seconds.
3. MAEST processes all windows, averages their results, stores ranked genres,
   and stores one normalized 768-dimensional embedding for the whole track.
4. Music2Emo derives valence, arousal, tags and the final mood profiles.

MAEST and Music2Emo prefer CUDA when available. The heavier mood components are
released after approximately five minutes without analysis work, so they do not
stay resident forever. Existing database values are reused until a track is
explicitly reanalysed.

For a visual, step-by-step inspection of the MAEST preprocessing and output,
open [notebooks/maest_pipeline.ipynb](notebooks/maest_pipeline.ipynb).

## Library management

- **Delete** removes the selected track's database record, its playlist and
  interaction entries, and its local file when it is located in `data/library/`.
  If the file is already missing, Delete still removes the orphaned record.
- Right-click a track to add it to the end of the queue. During a playlist
  session, manually queued tracks play next after the current item.
- Use **Reanalyze all** after replacing models or changing analysis logic.

## Development checks

Run these from the project root:

```powershell
uv run pytest -q
uv run ruff check app tests
```

If imports fail only in a direct `pytest` invocation, use `uv run pytest` from
the repository root so the project environment and package path are active.

## Troubleshooting

### `ffmpeg` is not recognised

Install `Gyan.FFmpeg.Shared`, confirm that its `bin` directory is in `PATH`, and
restart the terminal or VS Code. Then run `ffmpeg -version` again.

### `TorchCodec is required` or a TorchCodec DLL cannot load

Run `uv sync --locked`, install the FFmpeg shared build, and restart the
terminal. Verify `ffmpeg -version` before retrying the app.

### YouTube says that sign-in or cookies are required

Sign in to YouTube in Firefox, close Firefox completely, and retry. If that
does not work, replace `data/youtube_cookies.txt` with a fresh export from your
own browser session. Cookies can expire, and YouTube availability varies by
video and region.

### YouTube says it cannot copy the Firefox cookie database

Firefox is still running in the background. Close every Firefox window and
ensure its process has exited, then retry. Use the exported-cookie fallback if
Firefox cannot be closed.

### Spotify OAuth cannot finish

Confirm that `.env` contains `SPOTIFY_CLIENT_ID` and that the Redirect URI in
the Spotify dashboard exactly matches `http://127.0.0.1:8888/callback`. Also
ensure port `8888` is free while authentication is running.

### Genre analysis runs on CPU

Run the CUDA check above. Update the NVIDIA driver if `torch.cuda.is_available()`
is `False` or `CUDAExecutionProvider` is absent. CPU mode is supported but
slower.

### A model file is missing

Run the download block in [Add the model files](#add-the-model-files). The
required artifacts are the [MAEST ONNX file](https://essentia.upf.edu/models/feature-extractors/maest/discogs-maest-30s-pw-519l-2.onnx)
and the [Music2Emo chord model](https://huggingface.co/amaai-lab/music2emo/resolve/main/inference/data/btc_model_large_voca.pt?download=true).
They are intentionally not stored in Git because of their size.

## Privacy and responsible use

The database, audio files, embeddings, moods, cookies and Spotify token remain
on the local machine unless you choose to copy them elsewhere. Browser cookies
and OAuth tokens grant access to an account: treat them like passwords.

This project does not remove platform restrictions. Content availability,
authentication requirements and import success are controlled by YouTube,
Spotify, rights holders and local law.
