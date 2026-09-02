# Music Recs — VK + Spotify Playlist Exporter

This is a development build of a Chromium/Firefox Manifest V3 extension for
exporting **playlist metadata** from the currently open VK Music or Spotify
page.

It exports only:

- playlist title and URL;
- track order;
- artist;
- title;
- visible duration, when VK shows one.

It does not read, export, transmit, or store cookies, passwords, VK/Spotify
tokens, audio URLs, or audio files.

## Install locally in Chrome or Edge

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select this `vk-spotify-playlist-exporter` folder.
5. Pin the extension if desired.

## Use

### VK Music

1. Open a VK Music playlist in the browser.
2. In VK, click **Show all** if VK displays that control.
3. Open the extension and click **Export current playlist**.
4. Let it scroll until the count stops increasing, then save the JSON file.

The extension verifies that the **Show all** control is no longer visible before
exporting. It attaches itself to the current VK tab when export begins, so it
also works after an extension reload without requiring a manual page refresh.
The blue **Export playlist for Music Recs** page button may also appear after
the script attaches; it is an optional shortcut.

### Spotify

1. Open a Spotify playlist in the browser.
2. Log in only if the page itself requires it.
3. Open the extension and select **Export current playlist**.
4. Let it scroll until the count stops increasing, then save the JSON file.

The JSON file is an intermediate format for a future import action in the
desktop app. The planned importer will search YouTube for each
`artist — title` pair; it will not download audio from VK or Spotify.

## Why Spotify OAuth is not needed here

The extension reads only the artist/title rows already rendered in the current
Spotify tab. Therefore it does not call Spotify Web API and does not require a
Spotify client ID, redirect URI, OAuth token, or Dashboard test-user allowlist.
Private playlists work when the user can already view them in Spotify Web
Player.

## Development notes

VK and Spotify DOM structures are not public APIs and can change. The
extractors intentionally fail with a clear message if they cannot find
artist/title rows instead of exporting an empty or guessed playlist. Do not
widen the extension's permissions to read cookies or browse outside VK and
Spotify.
