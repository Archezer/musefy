// Spotify Web Player metadata extractor.
const SPOTIFY_EXPORT_FORMAT = "music-recommendation-system.spotify-playlist";
const MAX_SCROLL_STEPS = 180;
const SCROLL_DELAY_MS = 450;
const STABLE_SCROLL_STEPS = 6;

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function textOf(element) {
  return element?.textContent?.replace(/\s+/g, " ").trim() || "";
}

function parseDuration(value) {
  const parts = value
    .trim()
    .split(":")
    .map((part) => Number.parseInt(part, 10));

  if (!parts.length || parts.some((part) => Number.isNaN(part))) {
    return null;
  }

  return parts.reduce((seconds, part) => seconds * 60 + part, 0);
}

function playlistGrid() {
  const playlistTitle = textOf(document.querySelector("main h1"));
  const grids = [...document.querySelectorAll('main [role="grid"]')];

  return (
    grids.find((grid) => grid.getAttribute("aria-label") === playlistTitle) ||
    grids.find((grid) => grid.querySelector('a[href^="/track/"]')) ||
    null
  );
}

function parseTrack(row) {
  const title = textOf(row.querySelector('a[href^="/track/"]'));
  const artistLinks = [...row.querySelectorAll('a[href^="/artist/"]')];
  const artist = artistLinks.map(textOf).filter(Boolean).join(", ");

  if (!artist || !title) {
    return null;
  }

  const durationFromCell = textOf(
    row.querySelector(
      '[data-testid="tracklist-duration"], [aria-colindex="5"]',
    ),
  );
  const durationFromText = row.innerText
    .split("\n")
    .map((line) => line.trim())
    .reverse()
    .find((line) => /^(?:\d+:)?[0-5]?\d:\d{2}$/.test(line));

  return {
    artist,
    title,
    duration_seconds: parseDuration(durationFromCell || durationFromText || ""),
  };
}

function collectTracks() {
  const grid = playlistGrid();

  if (!grid) {
    return [];
  }

  const rows = [...grid.querySelectorAll('[role="row"]')].filter((row) =>
    Boolean(row.querySelector('a[href^="/track/"]')),
  );
  const tracks = [];
  const seen = new Set();

  for (const row of rows) {
    const track = parseTrack(row);

    if (!track) {
      continue;
    }

    const key = `${track.artist}\u0000${track.title}\u0000${track.duration_seconds ?? ""}`;

    if (!seen.has(key)) {
      seen.add(key);
      tracks.push(track);
    }
  }

  return tracks;
}

function notifyProgress(count) {
  chrome.runtime.sendMessage({
    type: "PLAYLIST_EXPORT_PROGRESS",
    count,
  });
}

function playlistTitle() {
  return textOf(document.querySelector("main h1")) ||
    document.title.replace(/\s*-\s*Spotify$/i, "").trim() ||
    "Spotify playlist";
}

function scrollContainer() {
  let current = playlistGrid()?.parentElement;

  while (current) {
    const style = window.getComputedStyle(current);
    const scrollable = /(auto|scroll)/.test(style.overflowY);

    if (scrollable && current.scrollHeight > current.clientHeight) {
      return current;
    }

    current = current.parentElement;
  }

  return document.scrollingElement;
}

async function exportPlaylist() {
  const allTracks = new Map();
  let stableSteps = 0;
  let previousCount = 0;
  const container = scrollContainer();

  for (let step = 0; step < MAX_SCROLL_STEPS; step += 1) {
    for (const track of collectTracks()) {
      const key = `${track.artist}\u0000${track.title}\u0000${track.duration_seconds ?? ""}`;
      allTracks.set(key, track);
    }

    notifyProgress(allTracks.size);
    const atBottom =
      container.scrollTop + container.clientHeight >= container.scrollHeight - 4;

    if (allTracks.size === previousCount && atBottom) {
      stableSteps += 1;
    } else {
      stableSteps = 0;
    }

    if (stableSteps >= STABLE_SCROLL_STEPS) {
      break;
    }

    previousCount = allTracks.size;
    container.scrollTo({ top: container.scrollHeight, behavior: "instant" });
    await sleep(SCROLL_DELAY_MS);
  }

  const tracks = [...allTracks.values()].map((track, index) => ({
    position: index + 1,
    ...track,
  }));

  if (!tracks.length) {
    throw new Error(
      "No tracks were found. Open a Spotify playlist page and retry.",
    );
  }

  return {
    format: SPOTIFY_EXPORT_FORMAT,
    version: 1,
    exported_at: new Date().toISOString(),
    playlist: {
      source: "spotify",
      title: playlistTitle(),
      url: window.location.href,
    },
    tracks,
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "SPOTIFY_EXPORT_PLAYLIST") {
    return;
  }

  exportPlaylist()
    .then((exportData) => sendResponse({ ok: true, export: exportData }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;
});
