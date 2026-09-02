const YANDEX_EXPORT_FORMAT = "music-recommendation-system.yandex-playlist";
const MAX_SCROLL_STEPS = 240;
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

function sourceIndexOf(row) {
  const indexedRow = row.matches("[data-index]")
    ? row
    : row.closest("[data-index]");
  const value = Number.parseInt(indexedRow?.getAttribute("data-index"), 10);

  return Number.isInteger(value) && value >= 0 ? value : null;
}

function playlistRegion() {
  return document.querySelector(
    '[aria-label^="Список треков плейлиста"], [aria-label^="Playlist tracks"]',
  );
}

function trackRows() {
  const region = playlistRegion();

  if (!region) {
    return [];
  }

  const tracks = [];
  const seen = new Set();

  const rows = [
    ...region.querySelectorAll('[data-index], [class*="CommonTrack_root"]'),
  ].filter((row) => row.querySelector(
    '[class*="Meta_title"], [class*="Meta_text"]',
  ));

  for (const row of rows) {
    const title = textOf(row.querySelector(
      '[class*="Meta_title"], [class*="Meta_text"]',
    ));
    const artistElement = row.querySelector(
      '[class*="SeparatedArtists"], [class*="Meta_artists"]',
    );
    const artist = textOf(artistElement);
    const durationText = [...textOf(row).matchAll(
      /(?:^|\s)(\d{1,2}:\d{2})(?=\s|$)/g,
    )]
      .map((match) => match[1])
      .pop();

    if (!title || !artist) {
      continue;
    }

    const track = {
      artist,
      title,
      duration_seconds: durationText ? parseDuration(durationText) : null,
      source_index: sourceIndexOf(row),
    };
    const key = track.source_index ??
      `${track.artist}\u0000${track.title}\u0000${track.duration_seconds ?? ""}`;

    if (!seen.has(key)) {
      seen.add(key);
      tracks.push(track);
    }
  }

  // Older Yandex markup has track links instead of Meta_* spans.
  if (tracks.length) {
    return tracks;
  }

  for (const link of region.querySelectorAll('a[href*="/track/"]')) {
    const title = textOf(link);
    let current = link.parentElement;
    let artistScope = null;
    let durationScope = null;

    while (current && current !== region) {
      const currentText = textOf(current);

      if (!artistScope && current.querySelector('a[href*="/artist/"]')) {
        artistScope = current;
      }

      if (
        !durationScope &&
        /(?:^|\s)\d{1,2}:\d{2}(?=\s|$)/.test(currentText)
      ) {
        durationScope = current;
      }

      if (artistScope && durationScope) {
        break;
      }

      current = current.parentElement;
    }

    if (!title || !artistScope) {
      continue;
    }

    const row = durationScope || artistScope;
    const artists = [...artistScope.querySelectorAll('a[href*="/artist/"]')]
      .map(textOf)
      .filter(Boolean);
    const durationText = [...textOf(durationScope || row).matchAll(
      /(?:^|\s)(\d{1,2}:\d{2})(?=\s|$)/g,
    )]
      .map((match) => match[1])
      .pop();
    const artist = [...new Set(artists)].join(", ");

    if (!artist) {
      continue;
    }

    const track = {
      artist,
      title,
      duration_seconds: durationText ? parseDuration(durationText) : null,
      source_index: sourceIndexOf(link),
    };
    const key = track.source_index ??
      `${track.artist}\u0000${track.title}\u0000${track.duration_seconds ?? ""}`;

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
  return (
    textOf(document.querySelector("main h1")) ||
    textOf(document.querySelector("h1")) ||
    document.title.replace(/\s*[—–-]\s*Яндекс Музыка.*$/i, "").trim() ||
    "Yandex Music playlist"
  );
}

function playlistCoverUrl() {
  const main = document.querySelector("main");
  const image = main?.querySelector("img[src]");

  return image?.currentSrc || image?.src || null;
}

function scrollContainer() {
  const region = playlistRegion();
  let current = region;

  while (current) {
    const style = window.getComputedStyle(current);

    if (
      /(auto|scroll)/.test(style.overflowY) &&
      current.scrollHeight > current.clientHeight
    ) {
      return current;
    }

    current = current.parentElement;
  }

  return document.scrollingElement || document.documentElement;
}

function scrollTopOf(container) {
  return container === document.scrollingElement ||
    container === document.documentElement
    ? window.scrollY
    : container.scrollTop;
}

function scrollToTop(container) {
  if (
    container === document.scrollingElement ||
    container === document.documentElement
  ) {
    window.scrollTo({ top: 0, behavior: "instant" });
    return;
  }

  container.scrollTo({ top: 0, behavior: "instant" });
}

function scrollDown(container) {
  const distance = Math.max(container.clientHeight * 0.8, 400);

  if (
    container === document.scrollingElement ||
    container === document.documentElement
  ) {
    window.scrollBy({ top: distance, behavior: "instant" });
    return;
  }

  container.scrollTo({
    top: Math.min(container.scrollHeight, container.scrollTop + distance),
    behavior: "instant",
  });
}

function expectedTrackCount() {
  const regionText = textOf(playlistRegion());
  const mainText = textOf(document.querySelector("main"));
  const matches = [regionText, mainText]
    .join(" ")
    .matchAll(/(?:трек(?:и|а|ов)?|tracks?)\s+(\d+)|(\d+)\s+(?:трек(?:и|а|ов)?|tracks?)/gi);
  const counts = [...matches]
    .map((match) => Number.parseInt(match[1] || match[2], 10))
    .filter((count) => Number.isInteger(count) && count > 0);

  return counts.length ? Math.max(...counts) : null;
}

async function exportPlaylist() {
  const region = playlistRegion();

  if (!region) {
    throw new Error(
      "Yandex playlist tracks were not found. Open the playlist page and retry.",
    );
  }

  const allTracks = new Map();
  let stableSteps = 0;
  let previousCount = 0;
  let discoveryOrder = 0;
  const container = scrollContainer();
  const expectedCount = expectedTrackCount();

  // Yandex virtualizes the list and renders only the visible rows. Always
  // start at the top, even if the user opened the exporter while at the end.
  scrollToTop(container);
  await sleep(SCROLL_DELAY_MS);

  for (let step = 0; step < MAX_SCROLL_STEPS; step += 1) {
    for (const track of trackRows()) {
      const fallbackKey = `${track.artist}\u0000${track.title}\u0000${track.duration_seconds ?? ""}`;
      const key = track.source_index ?? fallbackKey;

      if (!allTracks.has(key)) {
        allTracks.set(key, { ...track, discovery_order: discoveryOrder });
        discoveryOrder += 1;
      }
    }

    notifyProgress(allTracks.size);
    const atBottom =
      scrollTopOf(container) + container.clientHeight >= container.scrollHeight - 4;

    const highestIndex = Math.max(
      -1,
      ...[...allTracks.values()]
        .map((track) => track.source_index)
        .filter((index) => Number.isInteger(index)),
    );

    if (allTracks.size === previousCount && atBottom) {
      stableSteps += 1;
    } else {
      stableSteps = 0;
    }

    if (
      (expectedCount !== null && highestIndex >= expectedCount - 1) ||
      stableSteps >= STABLE_SCROLL_STEPS
    ) {
      break;
    }

    previousCount = allTracks.size;
    scrollDown(container);
    await sleep(SCROLL_DELAY_MS);
  }

  const tracks = [...allTracks.values()]
    .sort((left, right) => {
      if (left.source_index !== null && right.source_index !== null) {
        return left.source_index - right.source_index;
      }

      if (left.source_index !== null) {
        return -1;
      }

      if (right.source_index !== null) {
        return 1;
      }

      return left.discovery_order - right.discovery_order;
    })
    .map(({ source_index: _sourceIndex, discovery_order: _discoveryOrder, ...track }, index) => ({
      position: index + 1,
      ...track,
    }));

  if (!tracks.length) {
    throw new Error("Yandex playlist is visible, but no readable tracks were found.");
  }

  return {
    format: YANDEX_EXPORT_FORMAT,
    version: 2,
    exported_at: new Date().toISOString(),
    playlist: {
      source: "yandex",
      title: playlistTitle(),
      url: window.location.href,
      cover_url: playlistCoverUrl(),
    },
    tracks,
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "YANDEX_EXPORT_PLAYLIST") {
    return;
  }

  exportPlaylist()
    .then((exportData) => sendResponse({ ok: true, export: exportData }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;
});
