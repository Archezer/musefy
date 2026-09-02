function filenamePart(value) {
  return (value || "playlist")
    .replace(/[<>:"/\\|?*]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "playlist";
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "SAVE_PLAYLIST_EXPORT") {
    return;
  }

  const content = JSON.stringify(message.export, null, 2);
  const url = `data:application/json;charset=utf-8,${encodeURIComponent(content)}`;
  const filename = `music-recs-${message.export.playlist.source}/${filenamePart(
    message.export.playlist.title,
  )}.json`;

  chrome.downloads.download({ url, filename, saveAs: true }, () => {
    if (chrome.runtime.lastError) {
      sendResponse({ ok: false, error: chrome.runtime.lastError.message });
      return;
    }

    sendResponse({ ok: true });
  });

  return true;
});
