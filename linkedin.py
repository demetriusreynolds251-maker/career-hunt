#!/usr/bin/env python3
"""LinkedIn posting for Career Hunt, using LinkedIn's official API (Share on LinkedIn).

One-time setup:
  1. secrets/linkedin_app.json = {"client_id": "...", "client_secret": "..."}
  2. python3 linkedin.py --auth-url          -> the "Allow" link to tap
  3. python3 linkedin.py --code THE_CODE     -> saves secrets/linkedin_token.json
  4. python3 linkedin.py --whoami            -> checks it works

The bot calls post(text, image_path) only when you tap ✅ Approve.
The token lasts about 60 days; the bot reminds you before it runs out.
"""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "secrets", "linkedin_app.json")
TOKEN = os.path.join(HERE, "secrets", "linkedin_token.json")
REDIRECT = "https://demetriusreynolds251-maker.github.io/linkedin-callback/"
SCOPES = "openid profile w_member_social"
VERSIONS = ["202610", "202609", "202608", "202606", "202604", "202601", "202510"]  # newest first; first one LinkedIn accepts wins


def _load(p):
    with open(p) as f:
        return json.load(f)


def _save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def ready():
    """True when a token exists and hasn't expired."""
    try:
        t = _load(TOKEN)
        return t.get("expires_at", 0) > time.time() + 300
    except Exception:
        return False


def days_left():
    try:
        return int((_load(TOKEN)["expires_at"] - time.time()) // 86400)
    except Exception:
        return None


def auth_url():
    a = _load(APP)
    q = urllib.parse.urlencode({"response_type": "code", "client_id": a["client_id"], "redirect_uri": REDIRECT,
                                "scope": SCOPES, "state": "careerhunt"})
    return "https://www.linkedin.com/oauth/v2/authorization?" + q


def _req(method, url, data=None, headers=None, raw=False):
    h = {"User-Agent": "career-hunt/1.0"}
    h.update(headers or {})
    body = data if (data is None or isinstance(data, (bytes, bytearray))) else json.dumps(data).encode()
    if body is not None and "Content-Type" not in h and not isinstance(data, (bytes, bytearray)):
        h["Content-Type"] = "application/json"
    r = urllib.request.urlopen(urllib.request.Request(url, data=body, method=method, headers=h), timeout=60)
    content = r.read()
    if raw:
        return r, content
    return json.loads(content) if content else None


def exchange(code):
    a = _load(APP)
    form = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code.strip(), "redirect_uri": REDIRECT,
                                   "client_id": a["client_id"], "client_secret": a["client_secret"]}).encode()
    t = _req("POST", "https://www.linkedin.com/oauth/v2/accessToken", form,
             {"Content-Type": "application/x-www-form-urlencoded"})
    t["expires_at"] = time.time() + int(t.get("expires_in", 0))
    me = _req("GET", "https://api.linkedin.com/v2/userinfo", headers={"Authorization": "Bearer " + t["access_token"]})
    t["person_urn"] = "urn:li:person:" + me["sub"]
    t["name"] = me.get("name")
    _save(TOKEN, t)
    return t


def _rest(method, path, data=None, raw=False):
    t = _load(TOKEN)
    last = None
    for v in VERSIONS:
        try:
            return _req(method, "https://api.linkedin.com/rest/" + path, data, raw=raw, headers={
                "Authorization": "Bearer " + t["access_token"], "LinkedIn-Version": v,
                "X-Restli-Protocol-Version": "2.0.0"})
        except urllib.error.HTTPError as e:
            msg = e.read()[:400]
            last = f"{e.code} {msg!r}"
            if e.code == 426 or b"VERSION" in msg.upper():   # version not active -> try the next one
                continue
            raise RuntimeError(f"LinkedIn said {last}")
    raise RuntimeError(f"No LinkedIn API version accepted: {last}")


def upload_image(path):
    t = _load(TOKEN)
    init = _rest("POST", "images?action=initializeUpload", {"initializeUploadRequest": {"owner": t["person_urn"]}})
    v = init["value"]
    with open(path, "rb") as f:
        _req("PUT", v["uploadUrl"], f.read(), {"Authorization": "Bearer " + t["access_token"],
                                               "Content-Type": "application/octet-stream"}, raw=True)
    return v["image"]


def post(text, image_path=None, alt="Post image"):
    """Publishes to the member's own feed. Returns the public URL of the post."""
    t = _load(TOKEN)
    body = {"author": t["person_urn"], "commentary": text, "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    if image_path:
        body["content"] = {"media": {"id": upload_image(image_path), "altText": alt[:120]}}
    r, _ = _rest("POST", "posts", body, raw=True)
    urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id") or ""
    return "https://www.linkedin.com/feed/update/" + urn + "/" if urn else "https://www.linkedin.com/in/me/recent-activity/all/"


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--auth-url"]:
        print(auth_url())
    elif a[:1] == ["--code"] and len(a) > 1:
        t = exchange(a[1])
        print("connected as", t.get("name"), "· days left", days_left())
    elif a[:1] == ["--whoami"]:
        t = _load(TOKEN)
        print(t.get("name"), t.get("person_urn"), "ready" if ready() else "EXPIRED", "· days left", days_left())
    else:
        print(__doc__)
