const host = document.createElement("div");
host.id = "course-studyspace-root";
host.style.cssText = "position:fixed;inset:0 0 0 auto;z-index:2147483647;pointer-events:none";
document.documentElement.appendChild(host);
const root = host.attachShadow({mode: "open"});

root.innerHTML = `
  <style>
    :host { all: initial; }
    * { box-sizing: border-box; }
    .panel { pointer-events:auto; width:55vw; height:100vh; background:#fbfaf7; color:#24231f; border-left:1px solid #dedbd2; box-shadow:-12px 0 38px rgba(42,38,30,.14); font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; display:flex; flex-direction:column; transform:translateX(0); transition:transform .22s ease; }
    .panel.closed { transform:translateX(100%); }
    header { padding:18px 18px 12px; border-bottom:1px solid #e9e5dc; background:rgba(251,250,247,.96); }
    .top { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    h1 { margin:0; font:650 17px/1.2 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; letter-spacing:.01em; }
    .close { border:0; background:transparent; color:#777268; font-size:22px; cursor:pointer; }
    .status-row { display:flex; align-items:center; gap:9px; margin-top:13px; }
    .category { border:1px solid #d5d0c5; border-radius:9px; padding:7px 8px; background:#fff; color:#4f4b43; font-size:12px; }
    .record { border:0; border-radius:10px; background:#20201d; color:white; padding:9px 13px; font-weight:600; cursor:pointer; }
    .record.stop { background:#a53d35; }
    .dot { width:8px; height:8px; border-radius:50%; background:#aaa59a; }
    .dot.live { background:#d54b40; box-shadow:0 0 0 4px rgba(213,75,64,.12); }
    .status { color:#777268; font-size:12px; }
    .progress-wrap { display:flex; align-items:center; gap:9px; margin-top:10px; }
    .progress-wrap[hidden] { display:none; }
    .progress-track { flex:1; height:7px; overflow:hidden; border-radius:999px; background:#e6e1d8; }
    .progress-fill { width:0; height:100%; border-radius:inherit; background:#9a7258; transition:width .35s ease; }
    .progress-wrap.indeterminate .progress-fill { width:34%; animation:progress-scan 1.1s ease-in-out infinite; }
    @keyframes progress-scan { from { transform:translateX(-110%); } to { transform:translateX(300%); } }
    .progress-label { min-width:82px; text-align:right; color:#777268; font-size:11px; font-variant-numeric:tabular-nums; }
    .workspace { min-height:0; flex:1; display:grid; grid-template-columns:1.18fr 1fr; }
    .view { min-width:0; min-height:0; display:flex; flex-direction:column; }
    .view + .view { border-left:1px solid #dedbd2; }
    .column-title { margin:0; padding:12px 18px 10px; border-bottom:1px solid #e9e5dc; font-size:13px; letter-spacing:.04em; color:#6f6a61; }
    .agent-titlebar { min-height:64px; padding:8px 14px; display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:5px 10px; border-bottom:1px solid #e9e5dc; background:#fbfaf7; color:#292929; }
    .agent-brand { display:flex; min-width:0; align-items:center; gap:8px; }
    .agent-context-dot { width:9px; height:9px; flex:0 0 auto; border-radius:50%; background:#10a37f; box-shadow:0 0 0 3px rgba(16,163,127,.1); }
    .agent-controls { display:flex; min-width:0; align-items:center; gap:6px; }
    .agent-select { min-width:0; max-width:168px; border:0; border-radius:7px; padding:6px 8px; background:#f4f0e7; color:#292929; font:600 12px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; cursor:pointer; }
    .agent-select:hover { background:#eee9df; }
    .agent-effort { max-width:82px; color:#6f6a61; font-size:11px; font-weight:500; }
    .terminal-path { flex:0 0 100%; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#50745f; font:11px/1.25 ui-monospace,SFMono-Regular,Menlo,monospace; }
    .transcript-count { margin-left:8px; color:#8b857b; font-size:11px; font-weight:500; letter-spacing:0; }
    .transcript { overflow:auto; padding:15px 18px 100px; }
    .empty { margin:46px 18px; padding:22px; text-align:center; color:#858075; border:1px dashed #d5d0c5; border-radius:14px; }
    .segment { display:grid; grid-template-columns:100px 1fr; gap:10px; padding:10px 8px; margin:0 -8px; border-bottom:1px solid #efebe3; border-radius:8px; cursor:pointer; transition:background .15s ease, box-shadow .15s ease; }
    .segment:hover { background:#f3efe7; }
    .segment.playing { background:#eee5d7; box-shadow:inset 3px 0 #9a7258; }
    .segment.paused { background:#f4efe7; box-shadow:inset 3px 0 #b9a48f; }
    time { color:#9a7258; font-size:12px; font-variant-numeric:tabular-nums; padding-top:2px; }
    .segment p { margin:0; user-select:text; }
    .segment p { white-space:pre-wrap; overflow-wrap:anywhere; }
    .segment.source-note { background:#f4f0e7; margin:5px -8px; padding:10px 8px; border-radius:8px; border-bottom:0; }
    .segment.source-note time { color:#6f675d; font-weight:650; }
    .segment.source-note { cursor:default; }
    .segment.source-note:hover { background:#f4f0e7; }
    [data-panel="agent"] { position:relative; background:#fbfaf7; }
    .chat { overflow:auto; flex:1; padding:18px 16px 126px; background:#fbfaf7; }
    .bubble { max-width:100%; padding:0; margin:0 0 16px; white-space:pre-wrap; color:#292929; font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; }
    .bubble.system { margin-right:auto; }
    .bubble.system:not(.welcome)::before { content:"codex\A"; white-space:pre; color:#50745f; }
    .bubble.user { width:100%; margin-left:0; color:#292929; }
    .bubble.user::before { content:"codex › "; color:#75523b; font-weight:700; }
    .bubble.welcome { max-width:100%; padding:10px 11px; border:1px solid #e1ddd4; border-radius:6px; color:#6f6a61; background:#f4f0e7; }
    .composer { position:absolute; right:0; bottom:0; width:100%; padding:10px 12px 11px; background:linear-gradient(to bottom,rgba(251,250,247,0),#fbfaf7 18%); }
    .composer-shell { border:1px solid #d5d0c5; border-radius:7px; padding:8px 9px; background:#fbfaf7; box-shadow:0 3px 14px rgba(42,38,30,.1); }
    .composer-shell:focus-within { border-color:#a89d8d; box-shadow:0 0 0 1px rgba(117,82,59,.12); }
    .terminal-input-row { display:flex; align-items:flex-start; gap:7px; }
    .terminal-prompt { padding-top:4px; color:#75523b; font:700 13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; white-space:nowrap; }
    textarea { width:100%; min-height:40px; max-height:150px; resize:none; border:0; padding:4px 2px 6px; background:transparent; color:#292929; caret-color:#50745f; font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; outline:none; }
    .send-row { display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .context-pill { display:inline-flex; align-items:center; gap:5px; color:#8b857b; font:10px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; }
    .context-pill::before { content:""; width:7px; height:7px; border-radius:50%; background:#10a37f; }
    .hint { display:block; margin-top:5px; text-align:center; color:#9a948a; font:10px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; }
    .send { width:29px; height:27px; display:grid; place-items:center; border:1px solid #75523b; border-radius:5px; background:#75523b; color:white; padding:0; font-size:15px; line-height:1; cursor:pointer; }
    .send:disabled { border-color:#d5d0c5; background:#eeeae1; color:#aaa399; cursor:default; }
    .selection { color:#75523b; font-size:12px; margin-bottom:7px; max-height:42px; overflow:hidden; }
    .legacy-agent { display:none!important; }
    .native-terminal { min-height:0; flex:1; padding:8px 5px 5px 9px; overflow:hidden; background:#101014; }
    .native-terminal .xterm { height:100%; }
    .native-terminal .xterm-viewport { scrollbar-color:#555 #18181c; }
    .terminal-restart { border:1px solid #d5d0c5; border-radius:6px; padding:4px 8px; background:#f4f0e7; color:#6f6a61; font:11px ui-monospace,SFMono-Regular,Menlo,monospace; cursor:pointer; }
  </style>
  <aside class="panel">
    <header>
      <div class="top"><h1>课程学习助手</h1><button class="close" title="关闭">×</button></div>
      <div class="status-row"><button class="record">生成整节文字稿</button><select class="category" title="课程类别"><option value="">请选择课程类别</option><option>AI课</option><option>写作课</option><option>自学课</option><option>专注课</option><option>思考课</option><option>财富课</option><option>家庭教育课</option><option>教练课</option><option>英语课</option></select><span class="dot"></span><span class="status">无需播放课程</span></div>
      <div class="progress-wrap" hidden><div class="progress-track"><div class="progress-fill"></div></div><span class="progress-label">0%</span></div>
    </header>
    <div class="workspace">
      <section class="view" data-panel="transcript"><h2 class="column-title">课程文字稿 <small class="transcript-count"></small></h2><div class="transcript"><div class="empty">直接读取本节课已有的音频资源<br>无需播放，点击上方按钮即可</div></div></section>
      <section class="view" data-panel="agent">
        <div class="agent-titlebar"><div class="agent-brand"><span class="agent-context-dot" title="Codex CLI"></span><strong style="font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace">codex</strong></div><button class="terminal-restart" title="重新启动当前课程的 Codex">重新启动</button><div class="terminal-path">正在定位课程目录…</div></div>
        <div class="native-terminal"></div>
        <div class="legacy-agent"><select class="agent-model"><option value=""></option></select><select class="agent-effort"><option value=""></option></select><div class="chat"><div class="bubble system welcome"><span data-category-label>正在连接</span></div></div><div class="composer"><div class="selection"></div><textarea></textarea><button class="send">↵</button></div></div>
      </section>
    </div>
  </aside>`;
const terminalStyles = document.createElement("link");
terminalStyles.rel = "stylesheet";
terminalStyles.href = chrome.runtime.getURL("vendor/xterm.css");
root.prepend(terminalStyles);

const panel = root.querySelector(".panel");
const recordButton = root.querySelector(".record");
const dot = root.querySelector(".dot");
const statusText = root.querySelector(".status");
const progressWrap = root.querySelector(".progress-wrap");
const progressFill = root.querySelector(".progress-fill");
const progressLabel = root.querySelector(".progress-label");
const categorySelect = root.querySelector(".category");
const transcript = root.querySelector(".transcript");
const transcriptCount = root.querySelector(".transcript-count");
const textarea = root.querySelector("textarea");
const selectionLabel = root.querySelector(".selection");
const chat = root.querySelector(".chat");
const agentModelSelect = root.querySelector(".agent-model");
const agentEffortSelect = root.querySelector(".agent-effort");
const terminalPath = root.querySelector(".terminal-path");
const nativeTerminalElement = root.querySelector(".native-terminal");
const nativeTerminal = new Terminal({
  cursorBlink: true,
  convertEol: false,
  scrollback: 10000,
  fontFamily: '"SFMono-Regular", Menlo, Monaco, Consolas, monospace',
  fontSize: 12,
  lineHeight: 1.15,
  theme: {background:"#101014", foreground:"#e6e6e6", cursor:"#f2f2f2", selectionBackground:"#4b5563", black:"#202024", brightBlack:"#66666c"}
});
nativeTerminal.open(nativeTerminalElement);
nativeTerminal.write("\x1b[38;5;245m正在打开当前课程的 Codex…\x1b[0m\r\n");
let nativeTerminalSessionId = "";
let nativeTerminalCursor = 0;
let nativeTerminalGeneration = 0;
let nativeTerminalPolling = false;
let availableAgentModels = [];
let processing = false;
let segments = [];
let selectedText = "";
let needsEnhancement = false;
let courseAudioIndex = null;
let studyAudio = null;
let playingSegment = null;
let playingAudio = null;
let playbackStopTimer = null;
let playbackEndHandler = null;
let playingLocalEnd = null;
let playingGlobalEnd = null;
let observedCourseId = "";
let currentCourseMetadata = {};
const ledgerClassifiedCourseIds = new Set();
const watchedJobs = new Set();
const courseCategories = ["AI课", "写作课", "自学课", "专注课", "思考课", "财富课", "家庭教育课", "教练课", "英语课"];
const albumCategoryMap = {"3": "写作课"};

function categoryStorageKey() {
  return `course-studyspace-category-${currentCourseId() || "unknown"}`;
}

function updateAgentEfforts() {
  const selected = availableAgentModels.find((item) => item.model === agentModelSelect.value);
  const options = selected?.supportedReasoningEfforts || [];
  agentEffortSelect.innerHTML = "";
  for (const item of options) {
    const option = document.createElement("option");
    option.value = item.reasoningEffort;
    option.textContent = ({low:"快速", medium:"标准", high:"深入", xhigh:"很深入", max:"极致", ultra:"并行"})[item.reasoningEffort] || item.reasoningEffort;
    if (item.reasoningEffort === selected.defaultReasoningEffort) option.selected = true;
    agentEffortSelect.appendChild(option);
  }
  agentEffortSelect.disabled = options.length === 0;
}

async function loadAgentModels() {
  try {
    const response = await fetch("http://127.0.0.1:4317/codex/models");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "读取失败");
    availableAgentModels = data.models || [];
    const configuredModel = availableAgentModels.some((item) => item.model === data.runtime?.model)
      ? data.runtime.model
      : availableAgentModels.find((item) => item.isDefault)?.model;
    agentModelSelect.innerHTML = "";
    for (const item of availableAgentModels) {
      const option = document.createElement("option");
      option.value = item.model;
      option.textContent = item.displayName || item.model;
      option.title = item.description || "";
      if (item.model === configuredModel) option.selected = true;
      agentModelSelect.appendChild(option);
    }
    updateAgentEfforts();
  } catch (_) {
    agentModelSelect.innerHTML = '<option value="">模型列表不可用</option>';
    agentEffortSelect.disabled = true;
  }
}

agentModelSelect.addEventListener("change", updateAgentEfforts);

function restoreCategory() {
  const albumCategory = albumCategoryMap[currentAlbumId()] || "";
  categorySelect.value = albumCategory || localStorage.getItem(categoryStorageKey()) || "";
  if (albumCategory) localStorage.setItem(categoryStorageKey(), albumCategory);
  root.querySelector("[data-category-label]").textContent = categorySelect.value || "未选择类别";
}

function ensureCategoryOption(category) {
  if (!category || [...categorySelect.options].some((option) => option.value === category)) return;
  const option = document.createElement("option");
  option.value = category;
  option.textContent = category;
  categorySelect.appendChild(option);
}

function detectCategory(course) {
  // Only inspect the current course object. The whole page contains every category menu item.
  const haystack = JSON.stringify(course || {});
  return courseCategories.find((category) => haystack.includes(category)) || "";
}

categorySelect.onchange = () => {
  if (categorySelect.value) localStorage.setItem(categoryStorageKey(), categorySelect.value);
  root.querySelector("[data-category-label]").textContent = categorySelect.value || "未选择类别";
  if (categorySelect.value) statusText.textContent = `已选择 ${categorySelect.value}`;
};
restoreCategory();

const originalBodyWidth = document.body.style.width;
const originalBodyHeight = document.body.style.height;
const originalBodyOverflowX = document.body.style.overflowX;
const originalBodyTransform = document.body.style.transform;
const originalBodyTransformOrigin = document.body.style.transformOrigin;
function setWorkspaceOpen(open) {
  panel.classList.toggle("closed", !open);
  document.body.style.width = open ? "100vw" : originalBodyWidth;
  document.body.style.height = open ? "100vh" : originalBodyHeight;
  document.body.style.overflowX = open ? "hidden" : originalBodyOverflowX;
  document.body.style.transform = open ? "translateX(-27.5vw)" : originalBodyTransform;
  document.body.style.transformOrigin = open ? "center top" : originalBodyTransformOrigin;
  window.dispatchEvent(new Event("resize"));
}
setWorkspaceOpen(true);
root.querySelector(".close").onclick = () => setWorkspaceOpen(false);

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function updateProgress(state = {}) {
  const status = state.status || "idle";
  if (["idle", "interrupted", "error"].includes(status)) {
    progressWrap.hidden = true;
    return;
  }
  const total = Math.max(0, Number(state.total) || 0);
  const completed = Math.max(0, Number(state.completed) || 0);
  const mediaProgress = Math.max(0, Math.min(1, Number(state.media_progress) || 0));
  progressWrap.classList.toggle("indeterminate", !total && ["queued", "reading"].includes(status));
  let percent = 0;
  if (status === "complete") percent = 100;
  else if (status === "enhancing") percent = 96;
  else if (total) {
    const stageFraction = ["transcribing", "downloading"].includes(status) ? mediaProgress : 0;
    percent = Math.min(94, ((completed + stageFraction) / total) * 94);
  }
  progressWrap.hidden = false;
  progressFill.style.width = `${Math.max(0, percent).toFixed(1)}%`;
  const stageProgress = status === "downloading"
    ? Math.max(0, Math.min(1, Number(state.download_progress) || 0))
    : status === "transcribing" ? Math.max(0, Math.min(1, (mediaProgress - 0.2) / 0.8)) : 0;
  const currentDetail = ["transcribing", "downloading"].includes(status) && total === 1
    ? ` · 当前阶段 ${Math.round(stageProgress * 100)}%`
    : "";
  const count = total ? ` · ${Math.min(completed, total)}/${total} 段${currentDetail}` : "";
  progressLabel.textContent = !total && ["queued", "reading"].includes(status)
    ? "正在获取总数…"
    : `${Math.round(percent)}%${count}`;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {...options, signal: controller.signal});
  } finally {
    clearTimeout(timer);
  }
}

function nativeTerminalSize() {
  return {
    cols: Math.max(30, Math.floor(nativeTerminalElement.clientWidth / 7.25)),
    rows: Math.max(8, Math.floor(nativeTerminalElement.clientHeight / 15.5))
  };
}

async function startNativeTerminal(force = false) {
  const courseId = currentCourseId();
  if (!courseId) return;
  const generation = ++nativeTerminalGeneration;
  nativeTerminalSessionId = "";
  nativeTerminalCursor = 0;
  nativeTerminal.reset();
  nativeTerminal.write("\x1b[38;5;245m正在进入课程目录并启动 Codex…\x1b[0m\r\n");
  try {
    const response = await fetch("http://127.0.0.1:4317/terminal/start", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({course_id: Number(courseId), force, ...nativeTerminalSize()})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "终端启动失败");
    if (generation !== nativeTerminalGeneration || currentCourseId() !== courseId) return;
    nativeTerminalSessionId = data.session_id;
    terminalPath.textContent = data.cwd.replace(/^\/Users\/[^/]+/, "~");
    terminalPath.title = data.cwd;
    nativeTerminal.focus();
    pollNativeTerminal();
  } catch (error) {
    nativeTerminal.write(`\r\n\x1b[31m${error.message}\x1b[0m\r\n`);
  }
}

async function pollNativeTerminal() {
  if (nativeTerminalPolling || !nativeTerminalSessionId) return;
  nativeTerminalPolling = true;
  const sessionId = nativeTerminalSessionId;
  try {
    const response = await fetch(`http://127.0.0.1:4317/terminal/output?session_id=${encodeURIComponent(sessionId)}&since=${nativeTerminalCursor}`);
    const data = await response.json();
    if (sessionId !== nativeTerminalSessionId) return;
    if (response.ok && data.data) {
      const binary = atob(data.data);
      const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
      nativeTerminal.write(bytes);
    }
    if (response.ok) nativeTerminalCursor = data.cursor || nativeTerminalCursor;
    if (response.ok && !data.alive) nativeTerminal.write(`\r\n\x1b[38;5;245m[Codex 已退出，点击“重新启动”可再次打开]\x1b[0m\r\n`);
  } catch (_) {
  } finally {
    nativeTerminalPolling = false;
    if (sessionId === nativeTerminalSessionId) setTimeout(pollNativeTerminal, 60);
  }
}

nativeTerminal.onData((data) => {
  if (!nativeTerminalSessionId) return;
  fetch("http://127.0.0.1:4317/terminal/input", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session_id:nativeTerminalSessionId, data})
  }).catch(() => {});
});

let nativeResizeTimer = null;
new ResizeObserver(() => {
  clearTimeout(nativeResizeTimer);
  nativeResizeTimer = setTimeout(() => {
    const size = nativeTerminalSize();
    nativeTerminal.resize(size.cols, size.rows);
    if (nativeTerminalSessionId) fetch("http://127.0.0.1:4317/terminal/resize", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({session_id:nativeTerminalSessionId, ...size})
    }).catch(() => {});
  }, 80);
}).observe(nativeTerminalElement);

root.querySelector(".terminal-restart").onclick = () => startNativeTerminal(true);

function chooseMediaSource(item) {
  const candidates = [];
  const visit = (value, path = "item") => {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      const childPath = `${path}.${key}`;
      if (typeof child === "string" && /^https?:\/\//.test(child) && /url|src|source/i.test(key)) {
        if (!/cover|image|poster|thumb|subtitle|caption/i.test(childPath) && !/\.(?:jpe?g|png|webp|gif|vtt|srt)(?:\?|$)/i.test(child)) {
          candidates.push({url: child, key: childPath});
        }
      } else if (child && typeof child === "object") {
        visit(child, childPath);
      }
    }
  };
  visit(item.attachment || item, "attachment");
  const score = (candidate) => {
    const value = `${candidate.key} ${candidate.url}`.toLowerCase();
    if (/audio/.test(value)) return 100;
    if (/raw_url/.test(value)) return 70;
    if (/\.m3u8(?:\?|$)/.test(value)) return 60;
    if (/\.mp3|\.m4a|\.aac|\.wav|\.flac/.test(value)) return 90;
    if (/\.mp4|\.mov|\.webm/.test(value)) return 50;
    return 20;
  };
  candidates.sort((a, b) => score(b) - score(a));
  const selected = candidates[0] || {url: "", key: ""};
  return {
    ...selected,
    strategy: /audio|\.mp3|\.m4a|\.aac|\.wav|\.flac/i.test(`${selected.key} ${selected.url}`)
      ? "independent-audio"
      : /\.m3u8(?:\?|$)/i.test(selected.url) ? "hls" : "video-container"
  };
}

function renderTranscript() {
  if (!segments.length) return;
  transcript.innerHTML = segments.map((item, index) => {
    const isSourceNote = item.source_type === "page_text";
    const time = isSourceNote || Math.abs(item.end - item.start) < 0.01
      ? formatTime(item.start)
      : `${formatTime(item.start)} → ${formatTime(item.end)}`;
    const title = isSourceNote ? "课程页面原文，无独立音频" : "点击播放；再次点击暂停或继续";
    return `<div class="segment${isSourceNote ? " source-note" : ""}" data-index="${index}" data-playable="${isSourceNote ? "false" : "true"}" title="${title}"><time>${time}</time><p>${escapeHtml(item.text)}</p></div>`;
  }).join("");
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value;
  return node.innerHTML;
}

async function loadTranscript() {
  const requestedCourseId = currentCourseId();
  try {
    const response = await fetch(`http://127.0.0.1:4317/transcript?url=${encodeURIComponent(canonicalCourseUrl())}`);
    if (!response.ok) return;
    const data = await response.json();
    if (currentCourseId() !== requestedCourseId) return;
    if (!ledgerClassifiedCourseIds.has(requestedCourseId) && data.course?.category && courseCategories.includes(data.course.category)) {
      categorySelect.value = data.course.category;
      localStorage.setItem(categoryStorageKey(), data.course.category);
      root.querySelector("[data-category-label]").textContent = data.course.category;
    }
    const ledgerMetadata = ledgerClassifiedCourseIds.has(requestedCourseId) ? currentCourseMetadata : {};
    currentCourseMetadata = {...(data.course || {}), ...ledgerMetadata};
    segments = data.records.flatMap((record) => (record.segments || []).map((segment) => ({
      ...segment,
      content_id: record.content_id,
      order: record.order,
      category: record.category,
      audio_url: record.audio_url || ""
    })));
    renderTranscript();
    const hasRawCharacters = data.course?.raw_audio_characters != null;
    const hasReadingCharacters = data.course?.reading_audio_characters != null;
    const rawCharacters = Number(data.course?.raw_audio_characters);
    const readingCharacters = Number(data.course?.reading_audio_characters);
    transcriptCount.textContent = hasReadingCharacters && Number.isFinite(readingCharacters)
      ? `润色后音频文字 ${readingCharacters.toLocaleString("zh-CN")} 字${Number.isFinite(rawCharacters) ? ` · 原始 ${rawCharacters.toLocaleString("zh-CN")} 字` : ""}`
      : hasRawCharacters && Number.isFinite(rawCharacters) ? `原始音频文字 ${rawCharacters.toLocaleString("zh-CN")} 字` : "";
    if (data.records.length) {
      processing = false;
      needsEnhancement = data.course?.enhancement === "fallback";
      recordButton.textContent = needsEnhancement ? "重试语义整理" : "文字稿已保存";
      recordButton.disabled = !needsEnhancement;
      statusText.textContent = needsEnhancement ? "本机稿可用；Codex 润色可重试" : "已从本机读取，无需重新转写";
      dot.classList.remove("live");
      updateProgress({status: "complete"});
      return true;
    }
    if (data.course?.transcription === "complete") {
      processing = false;
      recordButton.disabled = false;
      recordButton.textContent = "重新生成文字稿";
      statusText.textContent = "检测到旧版空文字稿，请重新生成";
      dot.classList.remove("live");
      updateProgress({status: "error"});
    }
  } catch (_) {}
  return false;
}

async function refreshCourseStatus() {
  const requestedCourseId = currentCourseId();
  if (!requestedCourseId) return;
  try {
    const response = await fetch(`http://127.0.0.1:4317/course-status?url=${encodeURIComponent(canonicalCourseUrl())}`);
    if (!response.ok) return;
    const state = await response.json();
    if (currentCourseId() !== requestedCourseId) return;
    updateProgress(state);
    if (["queued", "downloading", "transcribing", "enhancing"].includes(state.status)) {
      processing = true;
      recordButton.disabled = true;
      recordButton.textContent = "后台处理中";
      dot.classList.add("live");
      statusText.textContent = state.message || "后台处理中";
      if (state.job_id && !watchedJobs.has(state.job_id)) watchJob(state.job_id, requestedCourseId);
    } else if (state.status === "interrupted") {
      processing = false;
      recordButton.disabled = false;
      recordButton.textContent = "继续生成";
      dot.classList.remove("live");
      statusText.textContent = state.message;
    }
  } catch (_) {}
}

async function loadCourseAudioIndex() {
  if (courseAudioIndex) return courseAudioIndex;
  const courseId = currentCourseId();
  const rawToken = localStorage.getItem("flutter.access_token");
  const token = rawToken ? JSON.parse(rawToken) : "";
  if (!courseId || !token) throw new Error("无法读取当前课程音频");
  const response = await fetch(`https://bandu-api.songy.info/v2/courses/${courseId}/contents`, {
    headers: {Authorization: `Bearer ${token}`}
  });
  if (!response.ok) throw new Error("课程音频地址读取失败");
  const json = await response.json();
  const items = json.data || json;
  let cumulative = 0;
  courseAudioIndex = [];
  for (const item of items) {
    if (!["audio", "video"].includes(item.category)) continue;
    const duration = Number(item.duration || item.attachment?.duration || 0) / 1000;
    const url = item.attachment?.raw_url || item.attachment?.url || "";
    courseAudioIndex.push({
      contentId: Number(item.id),
      mediaType: item.category,
      url,
      start: cumulative,
      end: cumulative + duration
    });
    cumulative += duration;
  }
  return courseAudioIndex;
}

function clearPlaybackStopControls() {
  if (playbackStopTimer) clearTimeout(playbackStopTimer);
  playbackStopTimer = null;
  if (playingAudio && playbackEndHandler) playingAudio.removeEventListener("timeupdate", playbackEndHandler);
  playbackEndHandler = null;
}

function stopSegmentPlayback(message = "已暂停") {
  clearPlaybackStopControls();
  playingAudio?.pause();
  playingSegment?.classList.remove("playing");
  playingSegment?.classList.remove("paused");
  playingAudio = null;
  playingSegment = null;
  playingLocalEnd = null;
  playingGlobalEnd = null;
  statusText.textContent = message;
}

function scheduleSegmentStop(audio) {
  clearPlaybackStopControls();
  const finish = () => {
    if (playingAudio === audio && audio.currentTime >= playingLocalEnd - 0.08) {
      stopSegmentPlayback(`本段播放完毕 ${formatTime(playingGlobalEnd)}`);
    }
  };
  playbackEndHandler = finish;
  audio.addEventListener("timeupdate", finish);
  const remainingMs = Math.max(100, (playingLocalEnd - audio.currentTime) / Math.max(audio.playbackRate, 0.1) * 1000);
  playbackStopTimer = setTimeout(() => {
    if (playingAudio === audio) stopSegmentPlayback(`本段播放完毕 ${formatTime(playingGlobalEnd)}`);
  }, remainingMs + 80);
}

async function playAtSegment(item, element, segmentIndex) {
  if (element === playingSegment && playingAudio) {
    if (!playingAudio.paused) {
      clearPlaybackStopControls();
      playingAudio.pause();
      element.classList.remove("playing");
      element.classList.add("paused");
      statusText.textContent = `已暂停 ${formatTime(item.start)}，再次点击继续`;
      return;
    }
    await playingAudio.play();
    element.classList.remove("paused");
    element.classList.add("playing");
    scheduleSegmentStop(playingAudio);
    statusText.textContent = `继续播放 ${formatTime(item.start)}`;
    return;
  }
  stopSegmentPlayback("正在定位音频…");
  const index = await loadCourseAudioIndex();
  let source = index.find((audio) => audio.contentId === Number(item.content_id));
  if (!source) {
    source = index.find((audio) => item.start >= audio.start && item.start < audio.end)
      || index.find((audio) => audio.start >= item.start)
      || index[index.length - 1];
  }
  if (!source?.url) throw new Error("这一段没有对应的音频");
  const localTime = Math.max(0, Number(item.start) - source.start);
  const fileName = decodeURIComponent(new URL(source.url).pathname.split("/").pop() || "");
  const pageAudio = [...document.querySelectorAll("audio,video")].find((media) => {
    const current = media.currentSrc || media.src || "";
    return current === source.url || (fileName && decodeURIComponent(current).includes(fileName));
  });
  const audio = pageAudio || studyAudio || new Audio();
  if (!pageAudio && audio.src !== source.url) {
    audio.pause();
    audio.src = source.url;
    audio.preload = "auto";
  }
  studyAudio = pageAudio ? studyAudio : audio;
  if (audio.readyState < 1) {
    await new Promise((resolve, reject) => {
      audio.addEventListener("loadedmetadata", resolve, {once: true});
      audio.addEventListener("error", () => reject(new Error("音频载入失败")), {once: true});
      audio.load();
    });
  }
  audio.currentTime = localTime;
  await audio.play();
  element.classList.add("playing");
  playingSegment = element;
  playingAudio = audio;

  let globalEnd = Number(item.end);
  if (globalEnd <= Number(item.start) + 0.05) {
    const next = segments.slice(segmentIndex + 1).find((segment) => Number(segment.start) > Number(item.start));
    globalEnd = next ? Number(next.start) : Number(item.start) + 3;
  }
  playingLocalEnd = Math.max(localTime + 0.1, globalEnd - source.start);
  playingGlobalEnd = globalEnd;
  scheduleSegmentStop(audio);
  statusText.textContent = `正在播放 ${formatTime(item.start)}`;
}

transcript.addEventListener("click", async (event) => {
  const element = event.target.closest(".segment");
  if (!element || root.getSelection()?.toString().trim()) return;
  if (element.dataset.playable !== "true") {
    statusText.textContent = "这是课程页面原文，没有独立音频";
    return;
  }
  const segmentIndex = Number(element.dataset.index);
  const item = segments[segmentIndex];
  if (!item) return;
  try {
    await playAtSegment(item, element, segmentIndex);
  } catch (error) {
    statusText.textContent = error.message;
  }
});

function resetAgentView() {
  agentSending = false;
  selectedText = "";
  selectionLabel.textContent = "";
  textarea.value = "";
  streamingBubble = null;
  codexEventCursor = Date.now() / 1000;
  chat.innerHTML = `<div class="bubble system welcome">Codex terminal · <span data-category-label>${escapeHtml(categorySelect.value || "正在连接")}</span><br>当前课程目录已连接。输入任务后按 Enter 执行。</div>`;
  restoreAgentHistory();
  const sendButton = root.querySelector(".send");
  sendButton.disabled = false;
  sendButton.textContent = "↵";
}

function agentHistoryStorageKey(courseId = currentCourseId()) {
  return `course-studyspace-agent-history-${courseId || "unknown"}`;
}

function restoreAgentHistory() {
  try {
    const history = JSON.parse(localStorage.getItem(agentHistoryStorageKey()) || "[]");
    for (const item of Array.isArray(history) ? history.slice(-100) : []) {
      if (!item || !["user", "system"].includes(item.type) || typeof item.text !== "string") continue;
      const bubble = document.createElement("div");
      bubble.className = `bubble ${item.type}`;
      bubble.textContent = item.text;
      chat.appendChild(bubble);
    }
    chat.scrollTop = chat.scrollHeight;
  } catch (_) {}
}

function saveAgentHistory() {
  const courseId = currentCourseId();
  if (!courseId) return;
  const history = [...chat.querySelectorAll(".bubble:not(.welcome):not(.transient)")].map((bubble) => ({
    type: bubble.classList.contains("user") ? "user" : "system",
    text: bubble.textContent
  })).filter((item) => item.text.trim()).slice(-100);
  try {
    localStorage.setItem(agentHistoryStorageKey(courseId), JSON.stringify(history));
  } catch (_) {
    localStorage.setItem(agentHistoryStorageKey(courseId), JSON.stringify(history.slice(-30)));
  }
}

function handleCourseChange() {
  const nextCourseId = currentCourseId();
  if (nextCourseId === observedCourseId) return;
  observedCourseId = nextCourseId;
  processing = false;
  segments = [];
  needsEnhancement = false;
  courseAudioIndex = null;
  currentCourseMetadata = {};
  nativeTerminalGeneration += 1;
  nativeTerminalSessionId = "";
  nativeTerminalCursor = 0;
  nativeTerminal.reset();
  nativeTerminal.write("\x1b[38;5;245m正在切换课程…\x1b[0m\r\n");
  terminalPath.textContent = "正在定位课程目录…";
  terminalPath.title = "";
  stopSegmentPlayback("已切换课程");
  studyAudio?.pause();
  studyAudio = null;
  playingSegment = null;
  restoreCategory();
  recordButton.disabled = false;
  recordButton.textContent = "生成整节文字稿";
  dot.classList.remove("live");
  updateProgress({status: "idle"});
  transcript.innerHTML = `<div class="empty">这是新的课程页面。点击“生成整节文字稿”后，会单独保存这节课的内容。</div>`;
  resetAgentView();
  if (!nextCourseId) {
    statusText.textContent = "请选择一节课程";
    return;
  }
  statusText.textContent = "正在读取当前课程…";
  identifyCourseCategory().finally(loadTranscript);
  refreshCourseStatus();
}

async function identifyCourseCategory() {
  const courseId = currentCourseId();
  if (!courseId) return;
  try {
    const response = await fetch(`http://127.0.0.1:4317/course-classification?course_id=${encodeURIComponent(courseId)}`);
    const result = await response.json();
    if (currentCourseId() !== courseId) return;
    for (const category of result.categories || []) ensureCategoryOption(category);
    if (response.ok && result.found && result.category) {
      ensureCategoryOption(result.category);
      categorySelect.value = result.category;
      ledgerClassifiedCourseIds.add(courseId);
      localStorage.setItem(categoryStorageKey(), result.category);
      root.querySelector("[data-category-label]").textContent = result.category;
      currentCourseMetadata = {...currentCourseMetadata, title: result.title, album_title: result.album_title, workspace_path: result.workspace_path || ""};
      terminalPath.textContent = result.workspace_path || `课程 ${courseId} · 资料目录待生成`;
      terminalPath.title = result.workspace_path || "";
      statusText.textContent = `已按人工总账归类为 ${result.category}`;
      startNativeTerminal();
      return;
    }
  } catch (_) {
    // Fall through to legacy inference only when the local classification ledger is unavailable.
  }
  const albumCategory = albumCategoryMap[currentAlbumId()] || "";
  if (albumCategory) {
    categorySelect.value = albumCategory;
    localStorage.setItem(categoryStorageKey(), albumCategory);
    root.querySelector("[data-category-label]").textContent = albumCategory;
    statusText.textContent = `已根据课程专辑识别为 ${albumCategory}`;
    return;
  }
  if (localStorage.getItem(categoryStorageKey())) return;
  try {
    const rawToken = localStorage.getItem("flutter.access_token");
    const token = rawToken ? JSON.parse(rawToken) : "";
    if (!token) throw new Error("missing login");
    const response = await fetchWithTimeout(`https://bandu-api.songy.info/v2/courses/${courseId}`, {
      headers: {Authorization: `Bearer ${token}`}
    }, 5000);
    if (!response.ok) throw new Error("course lookup failed");
    const json = await response.json();
    if (currentCourseId() !== courseId) return;
    const detected = detectCategory(json.data || json);
    if (detected) {
      categorySelect.value = detected;
      localStorage.setItem(categoryStorageKey(), detected);
      root.querySelector("[data-category-label]").textContent = detected;
      statusText.textContent = `已自动识别为 ${detected}`;
    } else {
      categorySelect.value = "";
      root.querySelector("[data-category-label]").textContent = "未选择类别";
      statusText.textContent = "未能自动识别课程类别，请先选择";
    }
  } catch (_) {
    if (currentCourseId() === courseId) statusText.textContent = "未能自动识别课程类别，请先选择";
  }
}

observedCourseId = currentCourseId();
window.addEventListener("hashchange", handleCourseChange);
window.addEventListener("popstate", handleCourseChange);
// Flutter/SPA navigation does not always emit hashchange or popstate.
setInterval(handleCourseChange, 350);

recordButton.onclick = async () => {
  if (processing) return;
  processing = true;
  recordButton.disabled = true;
  dot.classList.add("live");
  updateProgress({status: "reading"});
  statusText.textContent = "正在读取课程内容…";
  try {
    const courseId = currentCourseId();
    if (!courseId) throw new Error("当前页面没有课程编号");
    if (!categorySelect.value) throw new Error("请先选择这门课属于哪个课程类别");
    const rawToken = localStorage.getItem("flutter.access_token");
    const token = rawToken ? JSON.parse(rawToken) : "";
    if (!token) throw new Error("没有找到当前登录状态");
    const headers = {Authorization: `Bearer ${token}`};
    const contentsResponse = await fetchWithTimeout(
      `https://bandu-api.songy.info/v2/courses/${courseId}/contents`, {headers}, 20000
    );
    if (!contentsResponse.ok) throw new Error("课程内容接口拒绝访问，请重新登录后再试");
    const contentsJson = await contentsResponse.json();
    const contents = contentsJson.data || contentsJson;
    if (!Array.isArray(contents)) throw new Error("网站返回的课程内容格式无法识别");
    let course = {title: document.title.replace(/\s*[-|].*$/, "").trim() || `课程-${courseId}`};
    try {
      const courseResponse = await fetchWithTimeout(
        `https://bandu-api.songy.info/v2/courses/${courseId}`, {headers}, 5000
      );
      if (courseResponse.ok) {
        const courseJson = await courseResponse.json();
        course = courseJson.data || courseJson;
      }
    } catch (_) {
      // Course metadata is optional; content is enough to start transcription.
    }
    const detectedCategory = detectCategory(course);
    if (detectedCategory) {
      categorySelect.value = detectedCategory;
      localStorage.setItem(categoryStorageKey(), detectedCategory);
      root.querySelector("[data-category-label]").textContent = detectedCategory;
    }
    const items = contents.map((item) => {
      const media = ["audio", "video"].includes(item.category) ? chooseMediaSource(item) : {url: "", key: "", strategy: ""};
      return {
        id: item.id,
        order: item.order,
        category: item.category,
        duration: item.duration || item.attachment?.duration || 0,
        text: item.category === "text" ? item.content : "",
        url: media.url,
        media_source_key: media.key,
        media_strategy: media.strategy
      };
    });
    const mediaCount = items.filter((item) => ["audio", "video"].includes(item.category) && item.url).length;
    if (!mediaCount) throw new Error("这节课没有读取到可转写的音频或视频地址");
    updateProgress({status: "queued", total: mediaCount, completed: 0});
    statusText.textContent = `已读取 ${mediaCount} 段媒体，正在创建任务…`;
    const response = await fetch("http://127.0.0.1:4317/transcribe-course", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        course_url: canonicalCourseUrl(),
        course_title: course.title || course.name || `课程-${courseId}`,
        course_category: categorySelect.value,
        force_enhance: needsEnhancement,
        items
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "本机服务无法创建任务");
    if (data.cached) {
      const loaded = await loadTranscript();
      if (!loaded) throw new Error("本机缓存为空，请重新生成文字稿");
      return;
    }
    await watchJob(data.job_id, courseId);
  } catch (error) {
    statusText.textContent = error.name === "AbortError"
      ? "读取课程内容超过 20 秒，请检查登录状态或网络后重试"
      : error.message;
    processing = false;
    recordButton.disabled = false;
    dot.classList.remove("live");
    updateProgress({status: "error"});
  }
};

function canonicalCourseUrl() {
  const courseId = currentCourseId();
  return courseId ? `${location.origin}/#/courses/details?course_id=${courseId}` : location.href;
}

function currentCourseId() {
  return location.href.match(/[?&]course_id=(\d+)/)?.[1] || "";
}

function currentAlbumId() {
  return location.href.match(/[?&]album_id=(\d+)/)?.[1] || "";
}

async function watchJob(jobId, watchedCourseId) {
  if (watchedJobs.has(jobId)) return;
  watchedJobs.add(jobId);
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const response = await fetch(`http://127.0.0.1:4317/jobs/${jobId}`);
    const job = await response.json();
    if (!response.ok) {
      watchedJobs.delete(jobId);
      if (currentCourseId() === watchedCourseId) refreshCourseStatus();
      return;
    }
    if (currentCourseId() === watchedCourseId) {
      statusText.textContent = job.message || job.status;
      updateProgress(job);
    }
    if (job.status === "complete") {
      watchedJobs.delete(jobId);
      if (currentCourseId() === watchedCourseId) {
        processing = false;
        recordButton.disabled = false;
        dot.classList.remove("live");
        updateProgress({status: "complete", total: job.total, completed: job.total});
        await loadTranscript();
      }
      return;
    }
    if (job.status === "error") {
      watchedJobs.delete(jobId);
      if (currentCourseId() === watchedCourseId) {
        processing = false;
        recordButton.disabled = false;
        recordButton.textContent = "继续生成";
        dot.classList.remove("live");
        updateProgress({status: "error"});
        statusText.textContent = job.message || "处理已中断，可继续";
      }
      return;
    }
  }
}

document.addEventListener("mouseup", () => {
  const selection = document.getSelection()?.toString().trim();
  if (!selection || root.getSelection?.()?.toString()) return;
  selectedText = selection.slice(0, 4000);
  selectionLabel.textContent = `已引用：${selectedText}`;
  textarea.focus();
});

let agentSending = false;
async function sendAgentMessage() {
  if (agentSending) return;
  const question = textarea.value.trim();
  if (!question && !selectedText) return;
  addBubble("user", [selectedText ? `引用：${selectedText}` : "", question].filter(Boolean).join("\n\n"));
  const sendButton = root.querySelector(".send");
  agentSending = true;
  sendButton.disabled = true;
  sendButton.textContent = "…";
  try {
    const response = await fetch("http://127.0.0.1:4317/codex/message", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({category: categorySelect.value, course_id: Number(currentCourseId()) || null, course_title: currentCourseMetadata.title || "", album_title: currentCourseMetadata.site_album_title || currentCourseMetadata.album_title || "", text: question || "请处理我划选的内容", selection: selectedText, model: agentModelSelect.value || null, effort: agentEffortSelect.value || null})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Codex 无法开始任务");
    if (data.direct_answer) {
      addBubble("system", data.direct_answer);
      agentSending = false;
      sendButton.disabled = false;
      sendButton.textContent = "↵";
    }
  } catch (error) {
    addBubble("system", `Codex 连接失败：${error.message}`);
    agentSending = false;
    sendButton.disabled = false;
    sendButton.textContent = "↵";
  }
  textarea.value = "";
  selectedText = "";
  selectionLabel.textContent = "";
}

root.querySelector(".send").onclick = sendAgentMessage;
textarea.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  sendAgentMessage();
});

function addBubble(type, text) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${type}`;
  bubble.textContent = text;
  chat.appendChild(bubble);
  chat.scrollTop = chat.scrollHeight;
  saveAgentHistory();
}

let codexEventCursor = 0;
let streamingBubble = null;
async function pollCodexEvents() {
  try {
    const response = await fetch(`http://127.0.0.1:4317/codex/events?category=${encodeURIComponent(categorySelect.value)}&since=${codexEventCursor}`);
    if (!response.ok) return;
    const data = await response.json();
    for (const event of data.events || []) handleCodexEvent(event);
    codexEventCursor = data.now || codexEventCursor;
  } catch (_) {}
}

function handleCodexEvent(event) {
  const method = event.method || "";
  const params = event.params || {};
  if (method === "item/agentMessage/delta") {
    if (!streamingBubble) {
      streamingBubble = document.createElement("div");
      streamingBubble.className = "bubble system";
      streamingBubble.textContent = "";
      chat.appendChild(streamingBubble);
    }
    streamingBubble.textContent += params.delta || "";
    chat.scrollTop = chat.scrollHeight;
  } else if (method === "turn/completed") {
    saveAgentHistory();
    streamingBubble = null;
    agentSending = false;
    const sendButton = root.querySelector(".send");
    sendButton.disabled = false;
    sendButton.textContent = "↵";
  } else if (method === "error") {
    const message = params.error?.message || params.message || "Codex 连接发生错误";
    if (!params.willRetry) {
      addBubble("system", `Codex 未完成：${message}`);
      agentSending = false;
      const sendButton = root.querySelector(".send");
      sendButton.disabled = false;
      sendButton.textContent = "↵";
    }
  } else if (method.includes("requestApproval") && event.id != null) {
    addApprovalCard(String(event.id), method, params);
  } else if (method === "item/commandExecution/outputDelta") {
    const output = params.delta || "";
    if (output.trim()) addBubble("system", `终端输出：\n${output}`);
  }
}

function addApprovalCard(requestId, method, params) {
  const card = document.createElement("div");
  card.className = "bubble system transient";
  const summary = params.command || params.reason || params.grantRoot || method;
  card.textContent = `Codex 请求授权：\n${typeof summary === "string" ? summary : JSON.stringify(summary)}`;
  const actions = document.createElement("div");
  actions.style.cssText = "display:flex;gap:8px;margin-top:10px";
  for (const [label, decision] of [["允许一次", "accept"], ["本次会话允许", "acceptForSession"], ["拒绝", "decline"]]) {
    const button = document.createElement("button");
    button.className = "send";
    button.textContent = label;
    button.onclick = async () => {
      await fetch("http://127.0.0.1:4317/codex/approval", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({request_id:requestId, decision})});
      actions.remove();
    };
    actions.appendChild(button);
  }
  card.appendChild(actions);
  chat.appendChild(card);
  chat.scrollTop = chat.scrollHeight;
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "TOGGLE_PANEL") setWorkspaceOpen(panel.classList.contains("closed"));
});

resetAgentView();
identifyCourseCategory().finally(loadTranscript);
refreshCourseStatus();
