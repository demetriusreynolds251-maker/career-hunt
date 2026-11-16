#!/usr/bin/env python3
"""Posts a starter message (purpose + template) into every empty Career Hunt channel.
Safe to re-run: channels that already have messages are skipped."""
import json, os, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOK = open(os.path.join(HERE, "secrets", "discord_bot_token.txt")).read().strip()
H = {"Authorization": "Bot " + TOK, "User-Agent": "DiscordBot (career-hunt, 1.0)", "Content-Type": "application/json"}

SITE = "https://demetriusreynolds251-maker.github.io/apex/"
GH = "https://github.com/demetriusreynolds251-maker"

STARTERS = {
"📋・how-it-works": """# 📋 How Career Hunt works

**1. ✍️ Drafts come in.** Post drafts land in ✍️・post-drafts with buttons:
 ✅ **Approve** → a copy-ready version drops into ✅・approved-posts
 ❌ **Reject** → filed away
 ✏️ **Needs edits** → a thread opens; say what to change

**2. 📋 You post it yourself.** Nothing is ever sent to LinkedIn automatically. Copy, paste, post. That keeps it 100% you.

**3. 🤝 People first.** Every person gets a card in 🗂️・contacts. Follow-ups show up in 🔁・follow-ups.

**4. 📈 Every Sunday** fill in the 📈・weekly-scorecard and drop wins in 🎉・wins.

Only you can press the buttons. 🔒""",

"✅・approved-posts": """# ✅ Approved posts
When you tap **✅ Approve** on a draft, the final copy-ready text lands here.
📋 Long-press → Copy Text → paste into LinkedIn → Post. Then react ✅ here so we know it went out.""",

"📅・post-schedule": """# 📅 Post schedule
Aim: **2 posts a week** 🗓️ (Tuesday + Thursday mornings get the most eyes)

**This week**
• Tue: 🧪 The story of Apex (waiting in ✍️・post-drafts)
• Thu: 🧑‍💼 Operations lesson (waiting in ✍️・post-drafts)

**Next week**
• Tue: 💡 What I'm learning about AI tools
• Thu: 🙌 Shout-out to someone who helped you""",

"☀️・daily-checkins": """# ☀️ Daily check-in (2 minutes)
Copy, fill, send:
```
☀️ Date:
🤝 Connections sent today:
💬 Follow-ups sent:
👀 Comments left on others' posts:
🎯 One thing I'll do tomorrow:
```
Small daily reps beat one big push. 💪""",

"💬・message-drafts": """# 💬 Message drafts
Templates. Always add **one real detail** about the person before sending. ✨

**🤝 Connection request (under 300 characters)**
> Hi [Name], I saw your post about [topic] and liked how you [specific thing]. I lead operations in Mobile, AL and build data tools on the side. Would love to connect.

**🔁 Follow-up after connecting**
> Thanks for connecting, [Name]! I'm curious how your team handles [their area]. I've been digging into [related thing] lately. No ask, just like comparing notes. 🙂

**☕ Coffee chat ask**
> [Name], would you be open to a 15-minute call sometime next week? I'd love to hear how you got into [their field]. Happy to share what I've learned building Apex too.""",

"🎂・birthdays": """# 🎂 Birthdays & work anniversaries
LinkedIn shows these under **My Network → Catch up**. A short, personal note goes a long way:
> Happy work anniversary, [Name]! 🎉 [X] years at [Company], and I remember your post about [thing]. Hope year [X+1] is a great one.
Log who you messaged here. ✍️""",

"🗂️・contacts": """# 🗂️ Contacts (one card per person)
Copy this for each person:
```
👤 Name:
🏢 Role / Company:
📍 Where we met:
💬 What we talked about:
⭐ Something personal (kids, sport, hometown):
➡️ Next step + date:
```""",

"🆕・new-connections": """# 🆕 New connections
Drop each new connection here (name + one line about them). Anyone who replies moves to 🌱・warm-leads. 🌱""",

"🔁・follow-ups": """# 🔁 Follow-ups
Rule: **follow up within 3 days** ⏰
Format: `🔁 [Name]: [what to say] (by [date])`
React ✅ when done.""",

"🌱・warm-leads": """# 🌱 Warm leads
People actively talking with you. Keep each one moving:
`🌱 [Name] · [Company] · last talked [date] · next: [step]`""",

"🙏・referrals-and-intros": """# 🙏 Referrals & intros
Who can introduce you to whom. And who **you** can help introduce. Give first. 🤝
`🙏 [Your contact] → could intro me to → [Person / Company] · why:`""",

"📨・applications": """# 📨 Applications
One line per application, updated as it moves:
`📨 [Company] · [Role] · applied [date] · 🔵 applied / 🟡 interview / 🟢 offer / 🔴 no`""",

"📞・interviews": """# 📞 Interview prep
```
🏢 Company / Role:
🗓️ Date & time:
👤 Who I'm meeting:
🎯 Why I want this:
⭐ 3 stories to tell (operations wins, Apex, team leadership):
❓ 3 questions to ask:
💌 Thank-you note sent?
```""",

"🔔・job-alerts": """# 🔔 Job alerts
Paste roles that look interesting here. The good ones move to 🔎・job-leads with a fit score.
Tip: set LinkedIn job alerts for **Operations Manager · Operations Analyst · Business Operations · Supply Chain / Logistics** in Mobile, AL + Remote.""",

"🔎・job-leads": """# 🔎 Job leads
`🔎 [Company] · [Role] · [link] · fit ⭐⭐⭐⭐☆ · why it fits:`
Fit = skills match + growth + pay + commute/remote.""",

"📄・resume-and-cover": """# 📄 Resume & cover letters
Keep one master resume, then tailor per role. Post each tailored version here with the role it's for.
Must-haves: 📊 numbers on every bullet · 🛠️ tools (Excel, SAP, Python, SQL) · 🧪 Apex as a project with the link.""",

"🎉・wins": """# 🎉 Wins
Big or small, it all counts: a reply, a good call, a post that landed, an interview, an offer. 🏆
First win: 🚀 **Apex is live on GitHub with its own website.**""",

"📈・weekly-scorecard": """# 📈 Weekly scorecard (every Sunday)
```
Week of:
🤝 New genuine connections:  / 10
🔁 Follow-ups sent:           / 10
✍️ Posts published:           / 2
📨 Applications:              / 5
☕ Conversations:             / 2
🏆 Best moment this week:
```""",

"🧪・apex-showcase": f"""# 🧪 Apex showcase
🌐 Website: {SITE}
💻 GitHub: {GH}
📊 Tennis results (official tracker, Oct 22 – Nov 15): Top 3 picks **81%**, Elite 6 picks **75%**
Use this when someone asks "what have you built?" 💡""",

"🛠️・helping-others": """# 🛠️ Helping others
Projects you're helping people with: spreadsheets, process clean-ups, small data tools.
`🛠️ [Person] · [project] · what I did · what's next`
Helping is the best networking there is. 🤝""",

"💡・ideas": """# 💡 Ideas
**Post ideas**
• 🧑‍💼 What running operations taught me about building software
• 📦 One spreadsheet that should be a system (and how I'd fix it)
• 🤖 How I actually use AI tools day to day, honestly
• 🙌 Shout-out to someone who taught me something this year
• 📉 A mistake I made and what I changed

**Project ideas**
• 📊 A simple tool that turns a messy spreadsheet into a dashboard""",
}


def call(m, u, b=None):
    for _ in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request("https://discord.com/api/v10" + u, method=m, headers=H,
                                       data=None if b is None else json.dumps(b).encode()), timeout=20)
            raw = r.read()
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(json.loads(e.read()).get("retry_after", 2) + .5)
                continue
            raise


def main():
    gid = [x for x in call("GET", "/users/@me/guilds") if "career hunt" in x["name"].lower()][0]["id"]
    n = 0
    for c in call("GET", f"/guilds/{gid}/channels"):
        text = STARTERS.get(c["name"])
        if c["type"] != 0 or not text or call("GET", f"/channels/{c['id']}/messages?limit=1"):
            continue
        call("POST", f"/channels/{c['id']}/messages", {"content": text[:2000]})
        n += 1
    print("filled", n, "channels")


if __name__ == "__main__":
    main()
