chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id) chrome.tabs.sendMessage(tab.id, {type: "TOGGLE_PANEL"}).catch(() => {});
});

function ensureLocalServer() {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage("info.songy.course_launcher", {action: "start"}, (response) => {
      const error = chrome.runtime.lastError;
      if (error) return reject(new Error(error.message));
      if (!response?.ok) return reject(new Error(response?.error || "无法启动本机课程服务"));
      resolve(response);
    });
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "ENSURE_LOCAL_SERVER") return false;
  ensureLocalServer()
    .then((response) => sendResponse(response))
    .catch((error) => sendResponse({ok: false, error: error.message}));
  return true;
});
