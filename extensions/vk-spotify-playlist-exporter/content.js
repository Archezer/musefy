// VK Music metadata extractor.
const VK_EXPORT_FORMAT = "music-recommendation-system.vk-playlist";
const MAX_SCROLL_STEPS = 180;
const SCROLL_DELAY_MS = 450;
const STABLE_SCROLL_STEPS = 6;
const EXPORT_BUTTON_ID = "music-recs-vk-export-button";

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function visible(element) {
  const style = window.getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden";
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

function firstText(row, selectors) {
  for (const selector of selectors) {
    const value = textOf(row.querySelector(selector));

    if (value) {
      return value;
    }
  }

  return "";
}

function parseDataAudio(row) {
  const raw = row.getAttribute("data-audio");

  if (!raw) {
    return null;
  }

  try {
    const data = JSON.parse(raw);

    if (Array.isArray(data)) {
      return {
        artist: String(data[4] || "").trim(),
        title: String(data[3] || "").trim(),
        duration_seconds: Number.isFinite(data[5]) ? data[5] : null,
      };
    }

    return {
      artist: String(data.performer || data.artist || "").trim(),
      title: String(data.title || "").trim(),
      duration_seconds: Number.isFinite(data.duration) ? data.duration : null,
    };
  } catch {
    return null;
  }
}

function parseRenderedTrackText(row) {
  const lines = row.innerText
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .filter((line) => !/^начать прослушивание$/i.test(line));
  const durationIndex = lines.findIndex((line) =>
    /^(?:\d+:)?[0-5]?\d:\d{2}$/.test(line),
  );
  const details = durationIndex === -1 ? lines : lines.slice(0, durationIndex);

  if (details.length < 2) {
    return null;
  }

  return {
    title: details[0],
    artist: details.slice(1).join(", "),
    duration_seconds:
      durationIndex === -1 ? null : parseDuration(lines[durationIndex]),
  };
}

function parseTrack(row) {
  const dataTrack = parseDataAudio(row);
  const renderedTrack = parseRenderedTrackText(row);
  const artist = dataTrack?.artist || firstText(row, [
    '[data-testid*="Artist"]',
    '[data-testid*="Performer"]',
    ".audio_row__performers",
    ".audio_row__performer",
    ".audio_row__performer_title .audio_row__performers",
    '[class*="performer"]',
    '[class*="artist"]',
  ]) || renderedTrack?.artist;
  const title = dataTrack?.title || firstText(row, [
    '[data-testid*="Title"]',
    '[data-testid*="TrackName"]',
    "._audio_row__title_inner",
    ".audio_row__title_inner",
    ".audio_row__title",
    '[class*="title"]',
  ]) || renderedTrack?.title;

  if (!artist || !title) {
    return null;
  }

  const durationText = firstText(row, [
    ".audio_row__duration",
    ".audio_row__duration_text",
    '[class*="duration"]',
  ]);

  return {
    artist,
    title,
    duration_seconds:
      dataTrack?.duration_seconds ??
      renderedTrack?.duration_seconds ??
      parseDuration(durationText),
  };
}

function deepQueryAll(selectors) {
  const elements = [];
  const roots = [document];
  const visitedRoots = new Set();

  while (roots.length) {
    const root = roots.pop();

    if (!root || visitedRoots.has(root)) {
      continue;
    }

    visitedRoots.add(root);
    elements.push(...root.querySelectorAll(selectors));

    for (const element of root.querySelectorAll("*")) {
      if (element.shadowRoot) {
        roots.push(element.shadowRoot);
      }
    }
  }

  return elements;
}

function isTopmostRow(row) {
  const rect = row.getBoundingClientRect();

  if (rect.width < 40 || rect.height < 12) {
    return false;
  }

  const x = Math.min(rect.right - 4, rect.left + Math.max(24, rect.width / 2));
  const y = Math.min(rect.bottom - 4, rect.top + Math.max(8, rect.height / 2));
  const topElement = document.elementFromPoint(x, y);

  return Boolean(
    topElement && (row.contains(topElement) || topElement.contains(row)),
  );
}

function trackRows() {
  const modal = document.querySelector('[data-testid="MusicPlaylistModal"]');
  const modalRows = modal?.querySelectorAll(
    '[data-testid="MusicPlaylistTracks_MusicTrackRow"]',
  );

  if (modalRows?.length) {
    return [...modalRows];
  }

  const playlistRows = deepQueryAll(
    '[data-testid="MusicPlaylistTracks_MusicTrackRow"]',
  );

  if (playlistRows.length) {
    return playlistRows;
  }

  const rows = deepQueryAll(
    ".audio_row, .audio_item, [data-audio], [data-audio-id], .audio_row__inner, [class*='Audio'][class*='Item']",
  );
  const topmostRows = rows.filter(isTopmostRow);

  // VK keeps the underlying music page in the DOM while a playlist modal is
  // open. Prefer rows that are actually on top of that modal.
  return topmostRows.length ? topmostRows : rows;
}

function collectTracks() {
  const rows = trackRows();
  const tracks = [];
  const seen = new Set();

  for (const row of rows) {
    const track = parseTrack(row);

    if (!track) {
      continue;
    }

    const key = `${track.artist}\u0000${track.title}\u0000${track.duration_seconds ?? ""}`;

    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    tracks.push(track);
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
  return firstText(document, [
    ".audio_page__title",
    ".AudioPlaylistSnippet__title",
    "h1",
  ]) || document.title.replace(/\s*[—–-]\s*VK.*$/i, "").trim() || "VK playlist";
}

function showAllButton() {
  const scope =
    document.querySelector('[data-testid="MusicPlaylistModal"]') ||
    document.querySelector('[data-testid="MusicPlaylistPage"]');

  if (!scope) {
    // The canonical /music/playlist/ route already renders the playlist page.
    // Do not inspect the whole VK homepage, where recommendation sections may
    // contain their own “Show all” button.
    return null;
  }

  return [...scope.querySelectorAll("button, a, [role='button']")].find(
    (element) => {
      const label = textOf(element).toLowerCase();
      return label.includes("показать все") || label.includes("show all");
    },
  );
}

function scrollContainer() {
  const modalBody =
    document.querySelector('[data-testid="MusicPlaylistModal_Body"]') ||
    document.querySelector('[data-testid="MusicPlaylistPage_Body"]');

  if (modalBody && modalBody.scrollHeight > modalBody.clientHeight) {
    return modalBody;
  }

  const row = trackRows()[0];
  let current = row?.parentElement;

  while (current) {
    const style = window.getComputedStyle(current);
    const scrollable = /(auto|scroll)/.test(style.overflowY);

    if (scrollable && current.scrollHeight > current.clientHeight) {
      return current;
    }

    current = current.parentElement;
  }

  return document.scrollingElement || document.documentElement;
}

async function exportPlaylist() {
  if (showAllButton()) {
    throw new Error("Press “Show all” in the VK playlist, then export again.");
  }

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
      `No readable tracks found (${trackRows().length} candidate rows). Open the playlist itself, press “Show all”, and retry.`,
    );
  }

  return {
    format: VK_EXPORT_FORMAT,
    version: 1,
    exported_at: new Date().toISOString(),
    playlist: {
      source: "vk",
      title: playlistTitle(),
      url: window.location.href,
    },
    tracks,
  };
}

function saveExport(exportData) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: "SAVE_PLAYLIST_EXPORT", export: exportData },
      (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        if (!response?.ok) {
          reject(new Error(response?.error || "Could not save the JSON export."));
          return;
        }

        resolve();
      },
    );
  });
}

async function exportFromPage(button) {
  button.disabled = true;
  button.textContent = "Exporting playlist…";

  try {
    const exportData = await exportPlaylist();
    await saveExport(exportData);
    button.textContent = `Exported ${exportData.tracks.length} tracks`;
  } catch (error) {
    button.textContent = error.message || "Export failed";
  } finally {
    window.setTimeout(() => {
      button.disabled = false;
      button.textContent = "Export playlist for Music Recs";
    }, 2500);
  }
}

function isVkPlaylistPage() {
  return (
    window.location.href.includes("audio_playlist") ||
    window.location.pathname.includes("/music/playlist/")
  );
}

function ensureExportButton() {
  if (!isVkPlaylistPage() || document.getElementById(EXPORT_BUTTON_ID)) {
    return;
  }

  const button = document.createElement("button");
  button.id = EXPORT_BUTTON_ID;
  button.type = "button";
  button.textContent = "Export playlist for Music Recs";
  button.title = "Export visible artist and track names to JSON";
  Object.assign(button.style, {
    position: "fixed",
    right: "24px",
    bottom: "24px",
    zIndex: "2147483647",
    padding: "10px 14px",
    border: "1px solid #77c6f5",
    borderRadius: "7px",
    background: "#2374a5",
    color: "#ffffff",
    cursor: "pointer",
    font: "600 13px Segoe UI, Arial, sans-serif",
    boxShadow: "0 3px 12px rgba(0, 0, 0, 0.35)",
  });
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    void exportFromPage(button);
  });
  document.body.append(button);
}

const pageObserver = new MutationObserver(ensureExportButton);
pageObserver.observe(document.documentElement, { childList: true, subtree: true });
ensureExportButton();

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "VK_EXPORT_PLAYLIST") {
    return;
  }

  exportPlaylist()
    .then((exportData) => sendResponse({ ok: true, export: exportData }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;
});
