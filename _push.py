import json, subprocess, sys, urllib.request, urllib.error

OWNER, REPO = "UserC23", "jdkdads-loon"
API = "https://api.github.com"

def token():
    out = subprocess.run(["git", "credential", "fill"],
                         input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    sys.exit("no token")

TOK = token()

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOK}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "wb-push")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]

files = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
print("files:", len(files))

tree = []
for p in files:
    with open(p, encoding="utf-8") as f:
        content = f.read()
    st, res = call("POST", f"/repos/{OWNER}/{REPO}/git/blobs",
                   {"content": content, "encoding": "utf-8"})
    if st not in (200, 201):
        sys.exit(f"blob {p} failed {st}: {res}")
    tree.append({"path": p, "mode": "100644", "type": "blob", "sha": res["sha"]})

st, res = call("POST", f"/repos/{OWNER}/{REPO}/git/trees", {"tree": tree})
if st not in (200, 201):
    sys.exit(f"tree failed {st}: {res}")
tree_sha = res["sha"]

st, ref = call("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/main")
parents = [ref["object"]["sha"]] if st == 200 else []
print("parent:", parents)

msg = subprocess.run(["git","log","-1","--pretty=%B"],capture_output=True,text=True).stdout
st, res = call("POST", f"/repos/{OWNER}/{REPO}/git/commits",
               {"message": msg, "tree": tree_sha, "parents": parents})
if st not in (200, 201):
    sys.exit(f"commit failed {st}: {res}")
sha = res["sha"]
print("commit:", sha)

st, res = call("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/main",
               {"sha": sha, "force": False})
print("ref:", st, res.get("ref") if isinstance(res, dict) else res)
print("SHA", sha)
