import json
import sys
import time
import urllib.request

url = "http://127.0.0.1:5017/health"
deadline = time.time() + 240
last = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            h = json.loads(r.read().decode())
        st = h.get("status")
        if st != last:
            print("status:", st, "| progress:", h.get("progress"), "| error:", h.get("error"), flush=True)
            last = st
        if st == "ready":
            g = h.get("gpu", {})
            print("READY preset=%s speed=%s" % (g.get("preset"), g.get("speed")), flush=True)
            sys.exit(0)
        if st == "error":
            print("SERVER ERROR:", h.get("error"), flush=True)
            sys.exit(2)
    except Exception as e:
        if last != "down":
            print("waiting for server... (%s)" % e, flush=True)
            last = "down"
    time.sleep(2)
print("TIMEOUT waiting for server")
sys.exit(1)
