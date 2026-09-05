# Musefy

A Windows desktop application for a **local music library**. It imports audio
from files, YouTube, Spotify and SoundCloud links, analyses each track locally, and builds
recommendations without uploading the library or listening history to a cloud
service.

<img width="1229" height="822" alt="image" src="https://github.com/user-attachments/assets/f9c8ac76-fcca-49f5-9705-f86f1fd736e0" />


The app is designed around three complementary signals:

- **MAEST** generates genre predictions and a 768-dimensional musical embedding
  for every track;
- **Music2Emo** estimates valence, arousal and mood-oriented tags;
- local playback events and playlist context personalise ranking over time.

The project is a personal-library tool. Respect YouTube, Spotify, SoundCloud and copyright
rules when importing content.

## Features

- Import local audio files (`mp3`, `m4a`, `mp4`, `flac`, `wav`, `ogg`, `opus`).
- Search ***YouTube***, import a direct ***YouTube*** link, or load a ***YouTube playlist***.
- Import a ***Spotify track***, ***album*** or ***playlist***: Spotify supplies metadata, then
  the app searches YouTube for matching audio candidates.
- Sync newly saved ***Spotify favorites*** at startup and every five minutes, with
  a playlist-style review flow for selecting the tracks to download.
- Search ***SoundCloud***, load a ***direct track URL***, or load a ***SoundCloud set*** and
  choose which tracks to import through `yt-dlp`.
- Search ***MP3Party***, choose a result, or load a direct ***MP3Party track URL***.
- ***Use Firefox YouTube cookies automatically when a browser session is required***.
- Analyse new tracks in the background with CUDA when it is available.
- Store genre hierarchy, mood profile and one reusable MAEST embedding per
  track in a local SQLite database.
- Browse the library, create playlists, delete tracks, and manage a separate
  playback queue.
- Play normally, shuffle, smart shuffle, or start a mood session.
- Get four recommendation styles: global recommendations, track radio,
  mood-first recommendations, and the personalized **My Wave** session.

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
playback / likes / skips / playlists / selected mood / My Wave
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
Mood/My Wave scoring and session refill run in a background worker, with
cooperative cancellation when the user starts another queue or closes the app.

The **My Wave** entry in the Mood card builds a local profile from positive
listening signals, combining the user's mood centroid with audio similarity and
artist/genre affinity. Its recommendation impressions and subsequent playback
events are stored locally, and the Listening statistics window reports
the regular listening dashboard while the recommendation metrics remain
available locally for analysis (completion rate, skip rate, Recall@10,
NDCG@10 and artist diversity).

### Queue and smart shuffle

Shuffle never rewrites a playlist. It creates a temporary playback order in the
queue. Smart shuffle also inserts a suitable bridge track from the library after
every two playlist tracks, while leaving the original playlist untouched.

The **Back** button restarts the current track when it has already progressed;
press it again to return to the previous queue item. **Next** only moves through
the queue; **Skip** additionally records negative feedback.

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

The importer requests the best available audio-only stream. WebM/Opus sources
are remuxed to Ogg Opus without re-encoding, so the source quality is retained;
it does not intentionally save the full video. A YouTube video already present
in the library is recognised by source ID, so it is not duplicated. If the
database record exists but the local audio file was removed, importing it again
restores that record's file.

Playlist import shows successful and failed items. For every failed item you can
search YouTube again for a fresh candidate (or retry the existing download),
including tracks that were not found during the initial playlist search. Some
videos may still be unavailable because they are private,
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

#### Ready-to-use Windows installer

For a normal user, download the small `Musefy-Setup.exe` from GitHub Releases
and run it. This profile selector checks whether `nvidia-smi` can see a working
NVIDIA driver, then downloads the matching CPU or CUDA package from the same
release. The downloaded package is verified with SHA-256 and launched
automatically. The user does not manually handle the package parts.

The selected package contains the Musefy runtime, the desktop application, all
local ML models including MERT, the shared FFmpeg files, and the browser
extension. Python, `uv`, Git, the repository and manual model downloads are not
required on the user's PC.
Internet access is required during the first installation so the selector can
download the package; after installation, local analysis does not need model
downloads.

An NVIDIA driver is optional. The selector uses the CUDA package when a working
NVIDIA driver is detected, while the application performs the final
`torch.cuda.is_available()` check and falls back to CPU if CUDA cannot start. A
separate CUDA Toolkit is not required. The release also provides the complete
CPU installer directly and the CUDA installer as automatically joined parts for
manual or scripted downloads.

The release build is generated from the open source code with:

```powershell
.\build_release.bat v1.0.0
```

The maintainer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) once to
build the release packages. `build_release.bat` uses the same source installer
to prepare Python, `uv`, dependencies, FFmpeg and model files, then builds CPU
and CUDA variants, splits packages that exceed GitHub's per-file limit, and
creates the one-file selector. The source code remains open in this repository;
the release assets are only convenient distribution artifacts.

The generated `build/`, `dist/` and model binaries are intentionally ignored by
Git. Do not commit the multi-gigabyte installers to the source repository;
publish the selector and profile assets as a GitHub Release.

The release build includes the preinstalled Rick Astley demo track. Keep the
legally obtained audio file at
`data/library/Rick Astley — Rick Astley - Never Gonna Give You Up.m4a` on the
builder's machine. This single file is explicitly tracked; all other files in
`data/library/` remain ignored. The build copies the track into the installer
and imports it into a new user's library on first launch.

#### Complete source installation (Windows)

The steps below install the desktop app, its local ML models and the optional
playlist browser extension. Run the commands from the repository root unless a
command says otherwise.

##### 1. Check prerequisites

- [Git for Windows](https://git-scm.com/download/win), if you are cloning the
  repository. Windows 10/11 should also have the App Installer (`winget`) so
  the BAT can install shared FFmpeg when it is missing.
- An up-to-date NVIDIA driver is optional. A separate CUDA Toolkit is not
  required for running the CUDA profile.

`install_musefy.bat` installs the managed Python 3.12 runtime and `uv` when
needed, installs the locked dependencies, installs FFmpeg through `winget`,
downloads all three Music2Emo/MAEST files and the MERT-v1-95M snapshot, and
verifies PyTorch plus ONNX Runtime. Completed downloads are reused on a rerun.

##### 2. Clone the repository and run the installer

```powershell
git clone https://github.com/Archezer/musefy.git
Set-Location musefy
.\install_musefy.bat
```

The installer creates `.venv` in the project directory and installs the exact
locked dependency set for one profile. It chooses `cuda` when `nvidia-smi`
reports a working NVIDIA GPU; otherwise it chooses `cpu`. It then downloads all
required model files automatically and stores the MERT snapshot in
`data\models\mert`.

The repository includes the preinstalled Rick Astley demo track. On the first
source launch, Musefy imports it into the local database automatically, so the
library is not empty after installation.

If CUDA dependencies install but the verification cannot start CUDA, the BAT
automatically switches the environment to the CPU profile. It does not install
the full CUDA Toolkit because the packaged PyTorch CUDA runtime does not need
it. To force a profile for troubleshooting, set `MUSEFY_FORCE_PROFILE` to
`cpu` or `cuda` before running the BAT.

##### 3. Launch Musefy from source

The installer creates Musefy shortcuts in the Start Menu and on the desktop.
Open Musefy from either shortcut, then right-click it and choose **Pin to
taskbar** if you want a permanent taskbar button. The pinned shortcut remains
available after a Windows restart. The terminal command remains available for
troubleshooting:

```powershell
.venv\Scripts\python.exe -m app.desktop
```

Check the interpreter and GPU from the same directory if needed:

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available())"
.venv\Scripts\python.exe -c "import onnxruntime as ort; print('ONNX providers:', ort.get_available_providers())"
```

With no extra configuration, source runs keep the database and library under
the repository's `data\` directory:

```text
data\music.db                    SQLite database
data\library\                    imported audio files
data\models\maest\              MAEST model and labels
data\models\music2emo\          Music2Emo files
data\youtube_cookies.txt         optional Firefox/Netscape cookies
playlist_exports\                browser-extension exports
```

Start the app from the repository root:

```powershell
.venv\Scripts\python.exe -m app.desktop
```

To keep the database, library and models elsewhere, set `MUSEFY_DATA_DIR`
before launching. The directory is created automatically:

```powershell
$env:MUSEFY_DATA_DIR = "D:\Musefy\data"
.venv\Scripts\python.exe -m app.desktop
```

`MUSEFY_DATA_DIR` affects `music.db`, `library`, models, covers and cookies in a
source run. In an installed build, user data is stored in
`%LOCALAPPDATA%\Musefy\data`; bundled models remain read-only inside the
installed application. Set `MUSEFY_DATA_DIR` only when you need a custom data
location.

On the first track analysis, a packaged build may take a little longer while
the included MERT model is loaded. Analysis then runs in the background and
the interface remains usable.

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

4. In the import dialog, click **Spotify OAuth**, or open **Spotify settings**
   from the three-dot menu. The app opens the default browser, uses OAuth with
   PKCE, and waits for the local callback.
5. Approve access. The token is stored locally in `data/spotify_token.json` and
   used automatically by later Spotify imports. The consent screen includes
   Spotify's `user-library-read` permission for favorite sync.

No Spotify client secret is required. If the Spotify application is still in
Development Mode, add the Spotify account as a test user in the Developer
Dashboard. Never commit `.env` or `data/spotify_token.json`. The sync
checkpoint is also local runtime data and should not be shared.

#### Spotify Sync Last

After OAuth, press **Sync Last** either in the import dialog or in Spotify
settings. Musefy makes one explicit request, reads tracks saved since the
previous **Sync Last** click, searches YouTube for matching audio, and opens
the normal playlist-style selection screen. Nothing is downloaded until you
select the tracks and confirm.

The last successful Spotify cursor and already-seen track IDs are stored in
`data/spotify_fav_sync.json`, so restarting Musefy keeps the same incremental
window. The first manual sync uses the existing cursor when one is present;
otherwise it offers the current saved-track library once so you can establish
your baseline.

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
credentials for an account authorized to access that track. SoundCloud sets are
resolved into individual tracks, so each one can be selected before importing.

### MP3Party search and downloads

Click **Find with MP3Party**, enter an artist/title query, and select a result.
A direct URL such as `https://mp3party.net/music/11377383` is also accepted.
The importer uses the MP3 URL exposed by the selected track page and stores
only the resulting audio file in the local library. Use it only for tracks you
own or have explicit permission to download.

### VK Music, Spotify and Yandex Music browser exporter

The development extension in
[`extensions/vk-spotify-playlist-exporter`](extensions/vk-spotify-playlist-exporter) exports
the visible metadata of the currently open VK Music, Spotify or Yandex Music playlist to a
JSON file. When the desktop app is running, the extension sends the export to a
localhost bridge and saves it under `playlist_exports/<source>`. In a source
checkout this is next to the `extensions` folder; in an installed build it is
under `%LOCALAPPDATA%\Musefy\playlist_exports`. If the app is not running, it
falls back to the browser's Downloads folder. It collects only track order, artist, title and duration; it does not
read cookies, tokens, audio URLs or audio files.

In the desktop app, click **Import exported playlist** and select one of these
JSON files. The app then reuses the existing YouTube search, download, library
analysis and local-playlist pipeline, while reporting tracks that could not be
matched or downloaded.

For Spotify, this is an alternative to API-based metadata import: it works from
the user's already-open Spotify Web Player and therefore does not require the
project's Spotify client ID, OAuth callback, or Dashboard test-user allowlist.

#### Install the extension locally

The extension is a local, unpacked Manifest V3 extension. It does not need an
online store account.

- **Chrome or Edge:** open `chrome://extensions` or `edge://extensions`, enable
  **Developer mode**, click **Load unpacked**, and select the folder
  `extensions/vk-spotify-playlist-exporter` in a source checkout, or
  `%LOCALAPPDATA%\Programs\Musefy\extensions\vk-spotify-playlist-exporter` in
  the default installed build. Pin **Playlist Exporter** to keep its button
  visible.
- **Firefox:** open `about:debugging#/runtime/this-firefox`, click **Load
  Temporary Add-on**, and select the `manifest.json` inside the same source or
  installed extension folder. Firefox removes a temporary add-on after a
  browser restart, so load it again when needed.

#### Use the extension

1. Start Musefy first. The installed app can be launched from its Start Menu or
   desktop shortcut; a source checkout uses `.venv\Scripts\python.exe -m
   app.desktop`. The local bridge listens on `http://127.0.0.1:8765`.
2. In the same browser, open a playlist in VK Music, Spotify Web Player or
   Yandex Music. The extension works only on these HTTPS hosts and reads the
   playlist that is currently open in the active tab.
3. On VK, click **Show all** first when VK displays that control. Wait until the
   playlist rows are visible, then click the extension icon and choose
   **Export current playlist**. The extension scrolls the list until the number
   of tracks stops increasing and shows progress in the popup.
4. When Musefy is running, the JSON is saved to `playlist_exports\<source>\` in
   a source checkout or `%LOCALAPPDATA%\Musefy\playlist_exports\<source>\` in
   the installed build. If the app is closed or the bridge is unavailable, the
   extension saves the same JSON through the browser's Downloads dialog instead.
5. In Musefy choose **Import exported playlist** and select the JSON file. The
   app searches YouTube for each `artist — title` pair, lets you review matches,
   then downloads and analyses the selected tracks into a local playlist.

The extension exports only playlist title/URL, order, artist, title and visible
duration. It never reads or sends cookies, passwords, OAuth tokens, audio URLs
or audio files. Full source-specific notes and troubleshooting are in the
extension's [README](extensions/vk-spotify-playlist-exporter/README.md).

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
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check app tests
```

Run these commands after `install_musefy.bat` from the repository root so the
selected PyTorch profile is active. To create the complete CPU/CUDA release
packages and the release checker, use `build_release.bat`.

## Troubleshooting

### `ffmpeg` is not recognised

Install `Gyan.FFmpeg.Shared`, confirm that its `bin` directory is in `PATH`, and
restart the terminal or VS Code. Then run `ffmpeg -version` again.

### `TorchCodec is required` or a TorchCodec DLL cannot load

Run `.\install_musefy.bat`, install the FFmpeg shared build, and restart the
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

Run `.\install_musefy.bat` again. It checks the known model paths and
re-downloads incomplete files, including the [MAEST ONNX
file](https://essentia.upf.edu/models/feature-extractors/maest/discogs-maest-30s-pw-519l-2.onnx)
and the Music2Emo files from Hugging Face. They are intentionally not stored in
Git because of their size.

## Privacy and responsible use

The database, audio files, embeddings, moods, cookies and Spotify token remain
on the local machine unless you choose to copy them elsewhere. Browser cookies
and OAuth tokens grant access to an account: treat them like passwords.

This project does not remove platform restrictions. Content availability,
authentication requirements and import success are controlled by YouTube,
Spotify, rights holders and local law.
