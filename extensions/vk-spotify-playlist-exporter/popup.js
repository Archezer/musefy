// This popup chooses the source from the active playlist tab.
const exportButton = document.querySelector("#export-button");
const statusElement = document.querySelector("#status");
const DESKTOP_BRIDGE_URL = "http://127.0.0.1:8765/api/playlist-import";

function setStatus(text, { error = false } = {}) {
  statusElement.textContent = text;
  statusElement.classList.toggle("error", error);
}

function sourceForUrl(url) {
  if (/^https:\/\/(?:vk\.ru|vk\.com)\//i.test(url ?? "")) {
    return "vk";
  }

  if (/^https:\/\/(?:open|play)\.spotify\.com\//i.test(url ?? "")) {
    return "spotify";
  }

  if (/^https:\/\/music\.yandex\.ru\//i.test(url ?? "")) {
    return "yandex";
  }

  return null;
}

function filenamePart(value) {
  return (value || "playlist")
    .replace(/[<>:"/\\|?*]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "playlist";
}

function downloadExport(payload) {
  const content = JSON.stringify(payload, null, 2);
  const url = URL.createObjectURL(
    new Blob([content], { type: "application/json" }),
  );
  const filename = `music-recs-${payload.playlist.source}/${filenamePart(
    payload.playlist.title,
  )}.json`;

  chrome.downloads.download({ url, filename, saveAs: true }, () => {
    URL.revokeObjectURL(url);

    if (chrome.runtime.lastError) {
      setStatus(`Could not save JSON: ${chrome.runtime.lastError.message}`, {
        error: true,
      });
      return;
    }

    setStatus(`Exported ${payload.tracks.length} tracks.`);
  });
}

async function saveExportToDesktop(payload) {
  const response = await fetch(DESKTOP_BRIDGE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json().catch(() => ({}));

  if (!response.ok || !result.ok) {
    throw new Error(result.error || "Desktop app is unavailable.");
  }

  setStatus(
    `Saved ${result.track_count} tracks to ${result.relative_path}.`,
  );
}

async function saveExport(payload) {
  try {
    await saveExportToDesktop(payload);
  } catch {
    setStatus("Desktop app is unavailable; saving JSON to Downloads…");
    downloadExport(payload);
  }
}

async function sendToPlaylistTab(tabId, source) {
  const message = {
    type: {
      vk: "VK_EXPORT_PLAYLIST",
      spotify: "SPOTIFY_EXPORT_PLAYLIST",
      yandex: "YANDEX_EXPORT_PLAYLIST",
    }[source],
  };
  const file = {
    vk: "content.js",
    spotify: "spotify-content.js",
    yandex: "yandex-content.js",
  }[source];

  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: [file],
    });
    return chrome.tabs.sendMessage(tabId, message);
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "PLAYLIST_EXPORT_PROGRESS") {
    return;
  }

  setStatus(`Loading playlist… ${message.count} tracks found.`);
});

exportButton.addEventListener("click", async () => {
  exportButton.disabled = true;
  setStatus("Checking the current tab…");

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    const source = sourceForUrl(tab?.url);

    if (!tab?.id || !source) {
      throw new Error("Open a VK Music, Spotify or Yandex Music playlist first.");
    }

    const sourceName = {
      vk: "VK",
      spotify: "Spotify",
      yandex: "Yandex Music",
    }[source];
    setStatus(`Loading ${sourceName} playlist…`);
    const payload = await sendToPlaylistTab(tab.id, source);

    if (!payload?.ok) {
      throw new Error(payload?.error || "VK playlist export failed.");
    }

    await saveExport(payload.export);
  } catch (error) {
    setStatus(error.message || "VK playlist export failed.", { error: true });
  } finally {
    exportButton.disabled = false;
  }
});
