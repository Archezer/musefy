// This popup chooses the source from the active playlist tab.
const exportButton = document.querySelector("#export-button");
const statusElement = document.querySelector("#status");

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
  const filename = `music-recs-vk/${filenamePart(payload.playlist.title)}.json`;

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

async function sendToPlaylistTab(tabId, source) {
  const message = {
    type: source === "vk" ? "VK_EXPORT_PLAYLIST" : "SPOTIFY_EXPORT_PLAYLIST",
  };
  const file = source === "vk" ? "content.js" : "spotify-content.js";

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
      throw new Error("Open a VK Music or Spotify playlist first.");
    }

    setStatus(`Loading ${source === "vk" ? "VK" : "Spotify"} playlist…`);
    const payload = await sendToPlaylistTab(tab.id, source);

    if (!payload?.ok) {
      throw new Error(payload?.error || "VK playlist export failed.");
    }

    downloadExport(payload.export);
  } catch (error) {
    setStatus(error.message || "VK playlist export failed.", { error: true });
  } finally {
    exportButton.disabled = false;
  }
});
