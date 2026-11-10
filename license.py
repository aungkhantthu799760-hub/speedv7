# =====================================================================
# license.py - License Management Module
# =====================================================================

import os
import json
import hashlib
import hmac
import base64
from datetime import datetime, timedelta

LICENSE_FILE = "license.dat"
SECRET_KEY = b"KavinFastSpeed2024SecretKey!@#$%^&*()"

def _encode_license(data: dict) -> str:
    try:
        json_str = json.dumps(data, separators=(',', ':'))
        raw = json_str.encode('utf-8')
        sig = hmac.new(SECRET_KEY, raw, hashlib.sha256).hexdigest()[:16]
        return f"{sig}.{base64.b64encode(raw).decode()}"
    except Exception:
        return ""

def _decode_license(encoded: str) -> dict:
    try:
        if '.' not in encoded: return None
        sig, payload_b64 = encoded.split('.', 1)
        raw = base64.b64decode(payload_b64)
        expected_sig = hmac.new(SECRET_KEY, raw, hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig): return None
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return None

def _generate_license_data(key: str, days: int = 365) -> str:
    try:
        now = datetime.now()
        expiry = now + timedelta(days=days)
        data = {
            "key_hash": hashlib.sha256(key.encode()).hexdigest()[:32],
            "issued": now.strftime("%Y-%m-%d"),
            "expiry": expiry.strftime("%Y-%m-%d"),
            "days": days,
        }
        return _encode_license(data)
    except Exception:
        return ""

def check_approval():
    try:
        if not os.path.exists(LICENSE_FILE): return False, "No license"
        with open(LICENSE_FILE, "r") as f: encoded = f.read().strip()
        if not encoded: return False, "Empty license"

        data = _decode_license(encoded)
        if not data: return False, "Invalid license (signature)"

        expiry_str = data.get("expiry", "")
        try: expiry = datetime.strptime(expiry_str, "%Y-%m-%d")
        except Exception: return False, "Invalid expiry format"

        now = datetime.now()
        if now > expiry: return False, f"Expired on {expiry_str}"

        days_left = (expiry - now).days
        return True, f"{expiry_str} ({days_left}d left)"
    except Exception as e:
        return False, f"Error: {e}"

def activate(key: str):
    try:
        key = key.strip()
        if not key: return False, "Empty key"
        if not key.startswith("KAVINV7-"): return False, "Key must start with KAVINV7-"
        
        days = 365 

        encoded = _generate_license_data(key, days)
        if not encoded: return False, "Failed to generate license"

        with open(LICENSE_FILE, "w") as f: f.write(encoded)

        is_valid, msg = check_approval()
        if is_valid: return True, f"✓ Activated! {msg}"
        return False, "Activation failed"
    except Exception as e:
        return False, f"Error: {e}"

def deactivate():
    try:
        if os.path.exists(LICENSE_FILE): os.remove(LICENSE_FILE)
        return True, "Deactivated"
    except Exception as e:
        return False, f"Error: {e}"

# ============ CLI Test ============
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python license.py [check|activate|deactivate]")
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd == "check":
        print(check_approval())
    elif cmd == "activate" and len(sys.argv) >= 3:
        print(activate(sys.argv[2]))
    elif cmd == "deactivate":
        print(deactivate())
