#!/usr/bin/env python3
"""Career Hunt Discord setup. Builds the categories and emoji channels in the
"Career Hunt" server and posts the welcome + goals templates. Safe to re-run:
existing channels are kept, missing ones are added.

Token: secrets/discord_bot_token.txt (one line) or env CAREER_HUNT_BOT_TOKEN.
  python3 build_server.py --invite   # print the invite link for this bot
  python3 build_server.py            # build the server
"""
import json, os, sys, time, base64, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://discord.com/api/v10"
PERMS = 16 | 1024 | 2048 | 8192 | 16384 | 65536 | 536870912 | (1 << 51)  # + pin messages  # manage channels, view, send, manage msgs, embed, history, webhooks, pin

LAYOUT = [  # merged layout (owner's "・" set + extras), 11/16
 ("📌 START HERE", [
   ("👋・welcome", "What this server is for and how to use it"),
   ("📋・how-it-works", "How drafts, buttons and reminders work"),
   ("📌・goals", "Target roles, cities, salary range and weekly targets")]),
 ("💼 LINKEDIN", [
   ("✍️・post-drafts", "Post drafts with Approve / Reject / Needs edits buttons"),
   ("✅・approved-posts", "Approved, copy-ready posts. You post them on LinkedIn yourself"),
   ("📅・post-schedule", "What's going out and when")]),
 ("🤝 NETWORKING", [
   ("☀️・daily-checkins", "Daily check-in"),
   ("💬・message-drafts", "Personal connection-request and follow-up drafts"),
   ("🎂・birthdays", "Birthdays and work anniversaries to congratulate"),
   ("🗂️・contacts", "One card per person: who, where you met, next step"),
   ("🆕・new-connections", "New connections this week"),
   ("🔁・follow-ups", "Who to follow up with today"),
   ("🌱・warm-leads", "People actively talking with you"),
   ("🙏・referrals-and-intros", "Who can introduce you to whom")]),
 ("🎯 JOB HUNT", [
   ("📨・applications", "Applied → interview → offer / no"),
   ("📞・interviews", "Prep notes, questions to ask, thank-you drafts"),
   ("🔔・job-alerts", "New roles that match"),
   ("🔎・job-leads", "Roles worth applying to, with a fit score"),
   ("📄・resume-and-cover", "Tailored resume and cover letter versions per role")]),
 ("🏆 WINS", [
   ("🎉・wins", "Offers, great conversations, milestones 🎉"),
   ("📈・weekly-scorecard", "Connections made, posts, applications, interviews")]),
 ("🚀 PROJECTS", [
   ("🧪・apex-showcase", "Apex site, GitHub and results updates"),
   ("🛠️・helping-others", "Projects you're helping people with"),
   ("💡・ideas", "Side-project and post ideas")]),
]

WELCOME = """# 👋 Welcome to 🎯 Career Hunt

This is my home base for meeting new people, helping with projects and finding my next role.

**How it works**
🤝 **LinkedIn**: post drafts, connection notes and daily follow-ups. Nothing is posted or sent automatically. I read it, make it mine, and hit send myself.
🧑‍💼 **People**: a simple CRM, one card per person, so every message is personal.
💼 **Job Hunt**: leads, applications, interview prep and tailored resumes.
🚀 **Projects**: Apex and the projects I'm helping others with.
📊 **Progress**: wins and a weekly scorecard.

**House rules** ✅
• Be genuine: every message gets a personal detail
• Follow up within 3 days ⏰
• Give before you ask 🙏
• Celebrate small wins 🎉"""

GOALS = """# 📌 Goals (edit me anytime)

🎯 **Target roles:**
📍 **Locations:** Mobile, AL · remote ·
💵 **Salary range:**
🏢 **Dream companies:**

📈 **Weekly targets**
🤝 New genuine connections: 10
💬 Follow-ups sent: 10
✍️ LinkedIn posts: 2
📨 Applications: 5
☕ Conversations / coffee chats: 2"""

def token():
    # Career Hunt's own token file first. A DISCORD_BOT_TOKEN in the shell may belong to the tennis bot.
    try:
        t = open(os.path.join(HERE, "secrets", "discord_bot_token.txt")).read().strip()
        if t: return t
    except OSError: pass
    t = os.environ.get("CAREER_HUNT_BOT_TOKEN")
    if not t: sys.exit("No token yet: save it to secrets/discord_bot_token.txt")
    return t

def call(method, path, body=None, tok=None):
    for _ in range(6):
        req = urllib.request.Request(API + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bot " + tok, "Content-Type": "application/json",
                     "User-Agent": "DiscordBot (career-hunt, 1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read(); return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 2)) + 0.5); continue
            raise SystemExit(f"Discord said {e.code} on {method} {path}: {e.read()[:300]!r}")
    raise SystemExit("rate limited too long")

def client_id(tok):
    s = tok.split(".")[0]; s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode()

def main():
    tok = token()
    if "--invite" in sys.argv:
        print(f"https://discord.com/oauth2/authorize?client_id={client_id(tok)}&permissions={PERMS}&scope=bot%20applications.commands")
        return
    me = call("GET", "/users/@me", tok=tok)
    guilds = call("GET", "/users/@me/guilds", tok=tok)
    g = [x for x in guilds if "career hunt" in x["name"].lower()]
    if not g: sys.exit(f"Bot {me['username']} isn't in a 'Career Hunt' server yet. In it: {[x['name'] for x in guilds]}")
    gid = g[0]["id"]
    have = call("GET", f"/guilds/{gid}/channels", tok=tok)
    byname = {c["name"]: c for c in have}
    made = 0; ids = {}
    for pos, (cat, chans) in enumerate(LAYOUT):
        c = byname.get(cat) or call("POST", f"/guilds/{gid}/channels", {"name": cat, "type": 4, "position": pos}, tok)
        made += cat not in byname
        for i, (name, topic) in enumerate(chans):
            ch = byname.get(name) or call("POST", f"/guilds/{gid}/channels",
                    {"name": name, "type": 0, "topic": topic, "parent_id": c["id"], "position": i}, tok)
            made += name not in byname; ids[name] = ch["id"]
    for name, text in (("👋・welcome", WELCOME), ("📌・goals", GOALS)):
        cid = ids[name]
        if not call("GET", f"/channels/{cid}/messages?limit=5", tok=tok):
            m = call("POST", f"/channels/{cid}/messages", {"content": text}, tok)
            try: call("PUT", f"/channels/{cid}/pins/{m['id']}", None, tok)
            except SystemExit: print(f"(couldn't pin in {name}; long-press the message and Pin it)")
    print(f"Done: server '{g[0]['name']}', {made} new categories/channels, bot {me['username']}")

if __name__ == "__main__":
    main()
