#!/usr/bin/env python3
"""Public Google autocomplete evidence, human pace (>=7s between requests).
Stops at first non-200 / throttle / non-JSON response."""
import json, time, random, sys, urllib.request, urllib.parse, datetime, os
phr = json.load(open("evidence/phrases.json"))
outp = "evidence/google_autocomplete.jsonl"
done = set()
if os.path.exists(outp):
    done = {json.loads(l)["phrase"] for l in open(outp)}
f = open(outp, "a")
for p, path in phr:
    if p in done:
        continue
    url = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode(
        {"client": "firefox", "hl": "en", "gl": "us", "q": p})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
            data = json.loads(body)
    except Exception as e:
        print("STOP:", p, repr(e)[:200], flush=True)
        sys.exit(2)
    f.write(json.dumps({"phrase": p, "path": path, "suggestions": data[1],
                        "fetched_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}) + "\n")
    f.flush()
    print(p, len(data[1]), flush=True)
    time.sleep(7 + random.random() * 2)
print("DONE")
