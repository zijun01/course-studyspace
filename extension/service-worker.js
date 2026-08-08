chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id) chrome.tabs.sendMessage(tab.id, {type: "TOGGLE_PANEL"}).catch(() => {});
});
