"""Local-only web dashboard (`linescreening dashboard`).

- Binds 127.0.0.1 only — nothing outside this Mac can reach it.
- Zero new dependencies: stdlib http server + one embedded vanilla-JS page
  (no CDN, no external assets, no tracking).
- Same data-flow rules as triage: /api/triage captures and (unless
  ?offline=1) sends preview text to the Jev API — exactly like the CLI.

Routes: /            the dashboard page
       /api/triage   GET (re)runs triage, returns the JSON payload
       /api/history  GET recent triage run counts
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from rich.console import Console

from linescreening import report
from linescreening.config import load_config
from linescreening.db import Store

_PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>linescreening</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "PingFang TC", sans-serif;
         background: #0f1115; color: #e6e6e6; }
  header { display: flex; align-items: center; gap: 12px; padding: 14px 22px;
           border-bottom: 1px solid #23262e; position: sticky; top: 0;
           background: #0f1115ee; backdrop-filter: blur(6px); }
  header h1 { font-size: 16px; margin: 0; letter-spacing: .5px; }
  header .meta { color: #8b93a3; font-size: 12px; }
  header button { margin-left: auto; background: #2f6fed; color: #fff; border: 0;
           padding: 8px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; }
  header button:disabled { opacity: .5; cursor: wait; }
  header label { font-size: 12px; color: #8b93a3; }
  main { max-width: 880px; margin: 0 auto; padding: 20px 22px 60px; }
  .warn { background: #3a2f14; color: #ffd479; border-radius: 8px;
          padding: 8px 12px; font-size: 13px; margin: 10px 0; }
  .notice { color: #6b7382; font-size: 12px; margin: 6px 0; }
  .group { margin: 22px 0 8px; font-size: 13px; color: #8b93a3;
           letter-spacing: 1px; }
  .card { display: flex; gap: 14px; background: #171a21; border: 1px solid #23262e;
          border-radius: 12px; padding: 12px 16px; margin: 8px 0; }
  .card .icon { font-size: 20px; }
  .card .body { flex: 1; min-width: 0; }
  .card .name { font-weight: 700; font-size: 15px; }
  .card .name .unread { background: #2f6fed; color: #fff; border-radius: 10px;
          font-size: 11px; padding: 1px 8px; margin-left: 8px; vertical-align: 2px; }
  .card .preview { color: #aab3c2; font-size: 13px; margin-top: 3px;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card .reasons { color: #7d8698; font-size: 12px; margin-top: 5px; }
  .card .conf { width: 90px; align-self: center; text-align: right;
          font-size: 11px; color: #8b93a3; }
  .bar { height: 5px; border-radius: 3px; background: #23262e; margin-top: 4px; }
  .bar > i { display: block; height: 100%; border-radius: 3px; background: #4f9d69; }
  .low { color: #d8a03c; }
  .empty { text-align: center; color: #8b93a3; padding: 80px 0; font-size: 15px; }
  footer { text-align: center; color: #555c68; font-size: 11px; padding: 20px; }
  .ob { max-width: 640px; margin: 24px auto; }
  .ob h2 { font-size: 18px; margin: 8px 0 4px; }
  .ob p.sub { color: #8b93a3; font-size: 13px; margin: 0 0 18px; }
  .step { display: flex; gap: 12px; background: #171a21; border: 1px solid #23262e;
          border-radius: 12px; padding: 14px 16px; margin: 10px 0; align-items: flex-start; }
  .step .mark { font-size: 18px; width: 26px; text-align: center; }
  .step .body { flex: 1; }
  .step .t { font-weight: 700; font-size: 14px; }
  .step .t .opt { color: #6b7382; font-weight: 400; font-size: 12px; }
  .step .h { color: #98a2b3; font-size: 12.5px; margin-top: 4px; line-height: 1.55; }
  .step.done { border-color: #274a35; }
  .step button { background: #2f6fed; color: #fff; border: 0; border-radius: 8px;
          padding: 7px 14px; font-size: 12.5px; cursor: pointer; margin-top: 8px; }
  .keyform { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .keyform input[type=password] { background: #0f1115; border: 1px solid #2a2e38;
          color: #e6e6e6; border-radius: 8px; padding: 8px 10px; width: 260px; }
  .keyform label { font-size: 12px; color: #8b93a3; }
  .ob .skip { background: none; border: 1px solid #2a2e38; color: #8b93a3;
          border-radius: 8px; padding: 8px 14px; font-size: 12.5px;
          cursor: pointer; margin-top: 14px; }
  .ob .msg { font-size: 12.5px; margin-top: 6px; }
</style>
</head>
<body>
<header>
  <h1>LINE 未讀分級</h1>
  <span class="meta" id="status">尚未執行</span>
  <label><input type="checkbox" id="offline"> 離線（不外傳）</label>
  <button id="run">重新擷取判讀</button>
</header>
<main>
  <div id="onboarding" class="ob" style="display:none"></div>
  <div id="mainview" style="display:none">
    <div id="warnings"></div>
    <div id="content"><div class="empty">按「重新擷取判讀」開始</div></div>
  </div>
</main>
<footer>linescreening — 本機儀表板（僅 127.0.0.1）· 判讀時預覽文字送 typesafe.ai（同 CLI）</footer>
<script>
const ICON = {READ_NOW:"🔴", MAYBE:"🟡", READ_SOON:"🔵", CAN_SKIP:"⚪"};
const ORDER = ["READ_NOW","MAYBE","READ_SOON","CAN_SKIP"];
const LABEL = {READ_NOW:"值得讀（現在）", MAYBE:"不確定", READ_SOON:"可稍後讀", CAN_SKIP:"可略過"};
async function run() {
  const btn = document.getElementById("run");
  btn.disabled = true;
  document.getElementById("status").textContent = "擷取中…（會短暫聚焦 LINE）";
  try {
    const q = document.getElementById("offline").checked ? "?offline=1" : "";
    const res = await fetch("/api/triage" + q);
    const data = await res.json();
    render(data);
    document.getElementById("status").textContent =
      new Date(data.ran_at + "Z").toLocaleString("zh-TW") + " · " +
      ({live:"Jev 判讀", mock:"mock", offline:"離線（未判讀）"}[data.mode] || data.mode);
  } catch (e) {
    document.getElementById("status").textContent = "執行失敗：" + e;
  } finally { btn.disabled = false; }
}
function render(data) {
  document.getElementById("warnings").innerHTML =
    (data.warnings || []).map(w => `<div class="warn">⚠ ${w}</div>`).join("") +
    (data.notices || []).map(n => `<div class="notice">ℹ ${n}</div>`).join("");
  const root = document.getElementById("content");
  if (!data.chats.length) {
    root.innerHTML = '<div class="empty">目前沒有可見的未讀聊天 🎉</div>';
    return;
  }
  let html = "";
  for (const g of ORDER) {
    const chats = data.chats.filter(c => c.verdict === g);
    if (!chats.length) continue;
    html += `<div class="group">${ICON[g]} ${LABEL[g]} · ${chats.length} 個聊天</div>`;
    html += chats.map(c => `
      <div class="card">
        <div class="icon">${ICON[c.verdict]}</div>
        <div class="body">
          <div class="name">${esc(c.name)}${unreadBadge(c)}</div>
          <div class="preview">${esc(c.preview || "（無預覽文字）")}</div>
          <div class="reasons">${c.reasons.map(esc).join("；")}</div>
        </div>
        <div class="conf ${c.low_confidence ? "low" : ""}">
          信心 ${c.confidence == null ? "—" : (c.confidence * 100).toFixed(0) + "%"}
          <div class="bar"><i style="width:${(c.confidence ?? 0) * 100}%"></i></div>
        </div>
      </div>`).join("");
  }
  root.innerHTML = html;
}
function unreadBadge(c) {
  return c.unread != null ? `<span class="unread">${c.unread} 未讀</span>` : "";
}
function esc(s) {
  const MAP = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
  return String(s).replace(/[&<>"']/g, m => MAP[m]);
}
document.getElementById("run").addEventListener("click", run);

let pollTimer = null;
function mark(ok) {
  if (ok === true) return "✅";
  if (ok === false) return "⏳";
  return "➖";
}
function stepHtml(id, st) {
  let extra = "";
  if (id === "line" && !st.ok) {
    extra = `<button onclick="openLine()">幫我開啟 LINE</button>`;
  }
  if (id === "key" && !st.ok) {
    extra = `<div class="keyform">
        <input type="password" id="apikey" placeholder="貼上 API key（輸入不顯示）">
        <label><input type="checkbox" id="consent" checked> 同意預覽文字送 typesafe.ai</label>
        <button onclick="saveKey()">儲存並驗證</button>
      </div><div class="msg" id="keymsg"></div>`;
  }
  return `<div class="step ${st.ok ? "done" : ""}">
    <div class="mark">${mark(st.ok)}</div>
    <div class="body">
      <div class="t">${st.title}${st.critical ? "" : ' <span class="opt">（選配）</span>'}</div>
      <div class="h">${st.hint}</div>${extra}
    </div>
  </div>`;
}
async function refreshOnboarding() {
  const s = await (await fetch("/api/setup/status")).json();
  const ob = document.getElementById("onboarding");
  if (s.done || localStorage.ls_skip_setup === "1") {
    ob.style.display = "none";
    document.getElementById("mainview").style.display = "";
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    run();
    return;
  }
  ob.style.display = "";
  document.getElementById("mainview").style.display = "none";
  const rows = Object.entries(s.steps).map(([id, st]) => stepHtml(id, st)).join("");
  ob.innerHTML = `<h2>第一次使用：4 個步驟</h2>
    <p class="sub">每完成一步會自動打勾。macOS 的權限詢問請允許「Linescreening」。</p>
    ${rows}
    <div class="h" style="color:#6b7382;margin-top:10px">※ 允許螢幕錄製後請重開 App 才生效。</div>
    <button class="skip" onclick="skipSetup()">先跳過，用離線模式（只列未讀、不判讀）</button>`;
  if (!pollTimer) pollTimer = setInterval(refreshOnboarding, 4000);
}
async function openLine() {
  await fetch("/api/setup/open-line", {method: "POST"});
  setTimeout(refreshOnboarding, 1200);
}
async function saveKey() {
  const key = document.getElementById("apikey").value;
  const consent = document.getElementById("consent").checked;
  const msg = document.getElementById("keymsg");
  msg.textContent = "驗證中…";
  const res = await fetch("/api/setup/key", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({key, consent}),
  });
  const d = await res.json();
  msg.textContent = d.ok ? (d.detail || "已儲存") : ("失敗：" + (d.error || d.detail));
  if (d.ok) setTimeout(refreshOnboarding, 800);
}
function skipSetup() {
  localStorage.ls_skip_setup = "1";
  refreshOnboarding();
}
refreshOnboarding();
</script>
</body>
</html>
"""


def _history(cfg) -> list[dict]:  # type: ignore[no-untyped-def]
    store = Store(cfg.db_path)
    try:
        rows = store._conn.execute(  # noqa: SLF001 — local helper
            "SELECT ran_at, chats_seen FROM triage_log ORDER BY id DESC LIMIT 30"
        ).fetchall()
        return [{"ran_at": r["ran_at"], "chats_seen": r["chats_seen"]} for r in rows]
    finally:
        store.close()


def _setup_status(cfg) -> dict:  # type: ignore[no-untyped-def]
    """First-run onboarding state — reuses the doctor check engine."""
    from linescreening import checks

    screen_ok = checks.screen_recording_probe()
    line = checks.check_line_running()
    line_window = checks.find_line_window()
    key = checks.check_api_key()
    ax = checks.check_accessibility()
    steps: dict[str, dict] = {
        "screen": {
            "ok": screen_ok,
            "critical": True,
            "title": "螢幕錄製權限",
            "hint": (
                "已允許，擷取正常"
                if screen_ok
                else "系統設定 → 隱私權與安全性 → 螢幕錄製 → 開啟 Linescreening，"
                "然後結束並重開 App（權限在啟動時載入）"
            ),
        },
        "line": {
            "ok": bool(line.ok and line_window),
            "critical": True,
            "title": "LINE 已開啟",
            "hint": "LINE 正在執行"
            if (line.ok and line_window)
            else "開啟 LINE 並讓視窗出現（未最小化）",
        },
        "key": {
            "ok": bool(key.ok),
            "critical": True,
            "title": "Jev API key",
            "hint": "已設定並驗證" if key.ok else "在下方貼上 Typesafe AI 的 API key",
        },
        "ax": {
            "ok": None if ax.ok is None else bool(ax.ok),
            "critical": False,
            "title": "通知中心（選配）",
            "hint": "略過不影響使用；想用請到 輔助使用 授權 Linescreening",
        },
    }
    critical_ok = all(bool(st["ok"]) for st in steps.values() if st["critical"])
    return {"done": critical_ok, "steps": steps}


def make_server(port: int = 8765) -> ThreadingHTTPServer:  # noqa: FBT001, FBT002
    cfg = load_config()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload: dict | list, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 — stdlib naming
            route = urlparse(self.path).path
            query = urlparse(self.path).query
            if route == "/":
                body = _PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif route == "/api/triage":
                offline = "offline=1" in query
                try:
                    payload = report.collect_triage(offline=offline, cfg=cfg)
                    self._json(payload)
                except Exception as exc:  # noqa: BLE001 — surface as JSON error
                    self._json({"error": str(exc)}, status=500)
            elif route == "/api/history":
                self._json(_history(cfg))
            elif route == "/api/setup/status":
                self._json(_setup_status(cfg))
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 — stdlib naming
            route = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except json.JSONDecodeError:
                self._json({"ok": False, "error": "invalid JSON"}, status=400)
                return

            if route == "/api/setup/key":
                from linescreening import keychain
                from linescreening.checks import check_jev_api

                raw = str(data.get("key") or "")
                if not raw.strip():
                    self._json({"ok": False, "error": "key 不可空白"}, status=400)
                    return
                try:
                    keychain.store_key(raw)
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"儲存失敗：{exc}"}, status=500)
                    return
                store = Store(cfg.db_path)
                store.set_meta("cloud_consent", "granted" if data.get("consent") else "denied")
                if not data.get("consent"):
                    store.close()
                    self._json(
                        {
                            "ok": True,
                            "verified": False,
                            "detail": "已儲存，但未同意雲端判讀（將以離線模式運作）",
                        }
                    )
                    return
                store.close()
                probe = check_jev_api()
                self._json(
                    {"ok": bool(probe.ok), "verified": bool(probe.ok), "detail": probe.detail}
                )
            elif route == "/api/setup/open-line":
                from linescreening.capture import activate_app

                try:
                    activate_app("LINE")
                    self._json({"ok": True})
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": str(exc)}, status=500)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — stdlib signature
            pass  # keep the terminal quiet

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def run_dashboard(port: int = 8765, open_browser: bool = True) -> int:  # noqa: FBT001, FBT002
    console = Console()
    url = f"http://127.0.0.1:{port}"
    try:
        server = make_server(port=port)
    except OSError:
        # port taken: almost always another Linescreening instance already
        # serving — just open it instead of failing.
        console.print(
            f"[yellow]連接埠 {port} 已被使用[/yellow] — 已有 linescreening 在執行，開啟現有的。"
        )
        if open_browser:
            import subprocess

            subprocess.run(["open", url], check=False, timeout=10)
        return 0
    console.print(f"[bold green]linescreening 儀表板[/bold green] → {url}")
    console.print("[dim]僅本機可連線；Ctrl+C 停止。[/dim]")
    if open_browser:
        import subprocess

        subprocess.run(["open", url], check=False, timeout=10)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("再見 👋")
    finally:
        server.server_close()
    return 0
