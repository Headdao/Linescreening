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
  <div id="warnings"></div>
  <div id="content"><div class="empty">按「重新擷取判讀」開始</div></div>
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
    (data.warnings || []).map(w => `<div class="warn">⚠ ${w}</div>`).join("");
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
run();
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


def make_server(port: int = 8765) -> ThreadingHTTPServer:  # noqa: FBT001, FBT002
    cfg = load_config()

    class Handler(BaseHTTPRequestHandler):
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
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                except Exception as exc:  # noqa: BLE001 — surface as JSON error
                    body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif route == "/api/history":
                body = json.dumps(_history(cfg), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — stdlib signature
            pass  # keep the terminal quiet

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def run_dashboard(port: int = 8765, open_browser: bool = True) -> int:  # noqa: FBT001, FBT002
    console = Console()
    server = make_server(port=port)
    url = f"http://127.0.0.1:{port}"
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
