import requests, datetime
B = "http://127.0.0.1:8770"
bad = []

def show(name, r, want=200):
    good = r.status_code == want
    print(("PASS" if good else "FAIL"), name, r.status_code, r.text[:300].replace("\n", " "))
    if not good:
        bad.append(name)
    return r

show("health", requests.get(B + "/health"))
exp = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
mandate = {"user": "test-user", "max_total": 50, "allowed_categories": ["accessories"],
           "allowed_merchants": ["Demo Accessories Shop"], "expires_at": exp}
show("create mandate", requests.post(B + "/mandate", json=mandate))
show("get mandate", requests.get(B + "/mandate"))

ok = show("run agent (normal)", requests.post(B + "/agent/run", json={"request": "Buy a phone case under $20", "rogue": False}))
rogue = show("run agent (rogue)", requests.post(B + "/agent/run", json={"request": "Buy a phone case under $20", "rogue": True}))
print("      rogue was blocked:", "BLOCK" in rogue.text)

show("log", requests.get(B + "/log"))
show("verify (before tamper)", requests.get(B + "/log/verify"))
show("tamper", requests.post(B + "/log/tamper"))
show("verify (after tamper)", requests.get(B + "/log/verify"))

try:
    pid = ok.json().get("purchase_id")
    show("dispute report", requests.get(B + "/dispute/" + str(pid)))
except Exception as e:
    print("FAIL dispute report", e)
    bad.append("dispute report")

print()
print("RESULT:", "ALL OK" if not bad else "FAILED: " + ", ".join(bad))
