#!/usr/bin/env python3
"""Career Hunt bot: posts LinkedIn post drafts to Discord with real buttons.

  ✅ Approve      -> card turns green, a clean copy-ready version goes to the approved channel,
                    draft file moves to drafts/approved/
  ❌ Reject       -> card turns red, file moves to drafts/rejected/
  ✏️ Needs edits  -> card turns orange and a thread opens so you can say what to change;
                    the file stays in drafts/ marked "needs edits"

New drafts: drop a .md or .txt file in drafts/ (first line = title, rest = the post).
A rewrite can start its body with <!-- replaces: old-file.md --> and the old card collapses into a link to the new one.
An image with the same name (e.g. 04-x.md + 04-x.png) is shown on the card and sent with the approved copy.
No image? make_image.py makes one from the title and key points, so every post has one.
The bot checks every 60 seconds. Nothing is ever posted to LinkedIn. You copy and post it yourself.

Only the server owner and people with Manage Server can press the buttons.
Every button press gets a visible "what happens next" reply. Every message in a Career Hunt channel gets an
answer (and contacts, applications, interviews, leads get a follow-up reminder in 🔁 follow-ups).
Edit notes written in a draft's thread are saved to drafts/edit_requests.jsonl and confirmed.
All channel messages are logged to logs/channel_log.jsonl.
Runs from ~/CareerHunt with its own token (secrets/discord_bot_token.txt).
"""
import asyncio, json, os, shutil, sys
from datetime import datetime

import discord
from discord.ext import tasks

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linkedin
import inbox

HERE = os.path.dirname(os.path.abspath(__file__))
DRAFTS = os.path.join(HERE, "drafts")
STATE = os.path.join(DRAFTS, "state.json")
TOKEN_FILE = os.path.join(HERE, "secrets", "discord_bot_token.txt")
DRAFTS_CH = "post-drafts"          # matches ✍️・post-drafts or ✍️┃post-drafts
APPROVED_CH = ("approved-posts", "post-calendar", "post-schedule")

GREEN, RED, ORANGE, BLUE = 0x2ECC71, 0xE74C3C, 0xF39C12, 0x5865F2


def log(*a):
    print(datetime.now().strftime("%m/%d %H:%M:%S"), *a, flush=True)


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE)


def read_draft(path):
    text = open(path, encoding="utf-8").read().strip()
    first, _, rest = text.partition("\n")
    title = first.lstrip("# ").strip() or os.path.basename(path)
    return title[:240], rest.strip() or title


def find_channel(guild, keys):
    keys = (keys,) if isinstance(keys, str) else keys
    for k in keys:
        for ch in guild.text_channels:
            if ch.name.endswith(k):
                return ch
    return None


def image_for(key):
    stem = os.path.splitext(key)[0]
    for sub in ("", "approved", "rejected"):
        for ext in (".png", ".jpg", ".jpeg"):
            p = os.path.join(DRAFTS, sub, stem + ext)
            if os.path.exists(p):
                return p
    return None


def nice_time(iso=None):
    d = datetime.fromisoformat(iso) if iso else datetime.now()
    return d.strftime("%a %b %d, %Y · %I:%M %p").replace(" 0", " ")


def card(title, body, status, color, who=None, img=None, drafted=None, decided=None):
    e = discord.Embed(title="✍️ " + title, description=body[:4000], color=color, timestamp=datetime.now().astimezone())
    if img:
        e.set_image(url="attachment://" + os.path.basename(img))
    e.add_field(name="Status", value=status, inline=True)
    e.add_field(name="Words", value=str(len(body.split())), inline=True)
    e.add_field(name="🗓️ Timeline (only you see this)", inline=False,
                value="📝 Drafted: " + nice_time(drafted) + ("\n" + decided if decided else ""))
    if who:
        e.set_footer(text=who)
    return e


def allowed(inter):
    m = inter.user
    g = inter.guild
    return g is not None and (m.id == g.owner_id or getattr(m.guild_permissions, "manage_guild", False))


REMINDERS = os.path.join(HERE, "logs", "reminders.json")
CHANNEL_LOG = os.path.join(HERE, "logs", "channel_log.jsonl")
EDIT_REQUESTS = os.path.join(DRAFTS, "edit_requests.jsonl")
CHECKINS = os.path.join(HERE, "logs", "checkins.json")


def load_json(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


def append_jsonl(p, row):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def add_reminder(text, days, where):
    from datetime import timedelta
    rs = load_json(REMINDERS, [])
    due = (datetime.now() + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
    rs.append({"text": text[:300], "due": due.isoformat(timespec="seconds"), "where": where,
               "made": datetime.now().isoformat(timespec="seconds")})
    save_json(REMINDERS, rs)
    return due


def first_line(text, n=80):
    t = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return (t[:n] + "…") if len(t) > n else t


def streak(dates):
    from datetime import date, timedelta
    ds, d, n = set(dates), date.today(), 0
    while d.isoformat() in ds:
        n += 1
        d -= timedelta(days=1)
    return n


# channel name ending -> (reply, follow-up reminder days or None)
REPLIES = {
    "welcome": ("👋 Thanks! Everything starts in 📋・how-it-works. Post drafts are in ✍️・post-drafts.", None),
    "how-it-works": ("📋 Got it. Questions about how something works? Ask here anytime.", None),
    "goals": ("📌 Goals noted! Job leads and post drafts will follow these.", None),
    "post-drafts": ("💡 Idea saved! A full draft with an image and buttons will come back in this channel.", None),
    "approved-posts": ("🎉 Nice! If that means it's live on LinkedIn, it's logged as a win. Keep the streak going! 💪", None),
    "post-schedule": ("📅 Added to the schedule notes. Aim: 2 posts a week.", None),
    "message-drafts": ("💬 Saved. Before sending, add **one real detail** about the person. ✨", None),
    "birthdays": ("🎂 Logged! A short personal note goes a long way.", None),
    "contacts": ("📇 Contact saved! ⏰ Follow-up reminder set for **{due}** in 🔁・follow-ups.", 3),
    "new-connections": ("🆕 Welcome to the network! ⏰ I'll remind you to follow up on **{due}** in 🔁・follow-ups.", 3),
    "warm-leads": ("🌱 Warm lead noted! ⏰ Check-in reminder set for **{due}**.", 4),
    "referrals-and-intros": ("🙏 Intro idea saved! ⏰ Reminder to ask on **{due}**. Remember: give first. 🤝", 3),
    "follow-ups": ("🔁 Noted! React ✅ on a reminder once it's done.", None),
    "applications": ("📨 Application logged! 🍀 ⏰ I'll nudge you to follow up on **{due}**.", 7),
    "interviews": ("📞 Interview noted, you've got this! 💌 ⏰ Thank-you note reminder set for **{due}**.", 1),
    "job-alerts": ("🔔 Saved. If it's a strong fit, move it to 🔎・job-leads with a fit score.", None),
    "job-leads": ("🔎 Lead saved! ⏰ Reminder to apply or decide by **{due}**.", 2),
    "resume-and-cover": ("📄 Saved. Tailor the top 3 bullets to the job post. 🎯", None),
    "wins": ("🎉🎉 Love it! Logged in your wins. Small wins add up! 🏆", None),
    "weekly-scorecard": ("📈 Scorecard saved! Pick one thing to beat next week. 💪", None),
    "apex-showcase": ("🧪 Noted for the Apex showcase.", None),
    "helping-others": ("🛠️ Saved. Helping others is the best networking there is. 🤝 ⏰ Check-in reminder on **{due}**.", 7),
    "ideas": ("💡 Idea saved! The good ones become post drafts with images.", None),
    "general": ("👋 Hey! Each channel has a purpose. Start with 📋・how-it-works.", None),
}


async def handle_message(bot, msg):
    ch = msg.channel
    text = msg.content or ""
    if not bot.read_text and not text:
        text = "(message)"
    where = f"#{getattr(ch, 'name', '?')}"
    append_jsonl(CHANNEL_LOG, {"at": datetime.now().isoformat(timespec="seconds"), "channel": getattr(ch, "name", "?"),
                               "author": msg.author.display_name, "text": text,
                               "attachments": [a.url for a in msg.attachments]})
    # his own version of a LinkedIn reply, typed in the reply's edit thread
    if isinstance(ch, discord.Thread) and ch.name.startswith("✏️ reply to"):
        rs = load_json(REPLIES_STATE, {})
        r = rs.get(str(ch.id))
        if r and bot.read_text and text.strip():
            r["status"] = "replaced"
            save_json(REPLIES_STATE, rs)
            await msg.reply("📝 Got it! Here's your version, ready for ✅ Approve. 👇", mention_author=False)
            await post_alert(msg.guild, r["alert"], draft=text.strip(), extras=False)
        else:
            await msg.reply("📝 Got it, but I can't read the text yet. Turn on Message Content Intent first. 🙏",
                            mention_author=False)
        return
    # notes inside a draft's edit thread
    if isinstance(ch, discord.Thread) and ch.parent and ch.parent.name.endswith(DRAFTS_CH):
        st = load_state()
        key = next((k for k, v in st.items() if v.get("message_id") == ch.id), None)  # thread id == card message id
        title = st.get(key, {}).get("title", ch.name)
        append_jsonl(EDIT_REQUESTS, {"at": datetime.now().isoformat(timespec="seconds"), "draft": key,
                                     "title": title, "notes": text, "thread": ch.id})
        if key:
            st[key]["edit_notes"] = (st[key].get("edit_notes") or []) + [text]
            st[key]["status"] = "edit notes received"
            save_state(st)
        await msg.reply(f"📝 **Got it!** Your notes for *{title}* are saved:\n> {first_line(text, 180)}\n"
                        "🔄 A new version with an image and ✅/❌/✏️ buttons will come back in ✍️・post-drafts. "
                        "The old card will be marked as replaced. Add more notes here anytime.\n-# 🕒 " + nice_time(), mention_author=False)
        log("edit notes", key)
        return
    name = getattr(ch, "name", "")
    if name.endswith("daily-checkins"):
        ds = load_json(CHECKINS, [])
        today = datetime.now().date().isoformat()
        if today not in ds:
            ds.append(today)
            save_json(CHECKINS, ds)
        n = streak(ds)
        await msg.reply(f"☀️ Check-in logged! 🔥 Streak: **{n} day{'s' if n != 1 else ''}**. See you tomorrow. 💪\n-# 🕒 {nice_time()}",
                        mention_author=False)
        return
    for suffix, (reply, days) in REPLIES.items():
        if name.endswith(suffix):
            due = ""
            if days:
                d = add_reminder(f"{first_line(text, 120)}", days, where)
                due = d.strftime("%a %b %d, 9 AM")
            await msg.reply(reply.format(due=due) + f"\n-# 🕒 {nice_time()}", mention_author=False)
            if suffix == "approved-posts" and "post" in text.lower():
                wins = find_channel(msg.guild, "wins")
                st = load_state()
                last = max((v for v in st.values() if v.get("status") == "approved"),
                           key=lambda v: v.get("decided_at", ""), default=None)
                if wins and last:
                    await wins.send(f"🎉 **Posted on LinkedIn:** {last['title']}\n🗓️ {nice_time()}")
            if suffix == "post-drafts":
                append_jsonl(os.path.join(DRAFTS, "ideas.jsonl"), {"at": datetime.now().isoformat(timespec="seconds"), "idea": text})
            return



async def publish_to_linkedin(key, d, channel):
    """Posts an approved draft to LinkedIn (official API) and reports back in Discord. Never raises."""
    if not linkedin.ready():
        await channel.send("🔌 LinkedIn auto-posting isn't connected yet, so this one is waiting in ✅・approved-posts. "
                           "Once it's connected, tap **🚀 Post to LinkedIn** there.")
        return False
    ip = image_for(key)
    try:
        url = await asyncio.to_thread(linkedin.post, d["body"], ip, d["title"])
    except Exception as e:
        log("linkedin post failed", key, e)
        await channel.send(f"⚠️ **Couldn't post to LinkedIn:** {str(e)[:300]}\n"
                           "The copy-ready version is in ✅・approved-posts, so you can post it by hand.\n-# 🕒 " + nice_time())
        return False
    st = load_state()
    if key in st:
        st[key]["linkedin_url"], st[key]["posted_at_linkedin"] = url, datetime.now().isoformat(timespec="seconds")
        save_state(st)
    await channel.send(f"🚀 **Posted to LinkedIn!** {d['title']}\n🔗 {url}\n-# 🕒 {nice_time()}")
    wins = find_channel(channel.guild, "wins")
    if wins:
        await wins.send(f"🎉 **Posted on LinkedIn:** {d['title']}\n🔗 {url}\n🗓️ {nice_time()}")
    log("linkedin posted", key, url)
    return True


class PostNow(discord.ui.View):
    """'🚀 Post to LinkedIn' button on approved posts (for posts approved before LinkedIn was connected)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Post to LinkedIn", emoji="🚀", style=discord.ButtonStyle.primary, custom_id="ch:postnow")
    async def postnow(self, inter, button):
        if not allowed(inter):
            await inter.response.send_message("Only the server owner can post. 🙏", ephemeral=True)
            return
        st = load_state()
        key = next((k for k, v in st.items() if inter.message.id in (v.get("approved_msg_id"),)), None)
        if not key:
            await inter.response.send_message("I can't find this post's draft. 🤔", ephemeral=True)
            return
        if st[key].get("linkedin_url"):
            await inter.response.send_message(f"✅ Already posted: {st[key]['linkedin_url']}", ephemeral=True)
            return
        await inter.response.edit_message(view=None)
        ok = await publish_to_linkedin(key, st[key], inter.channel)
        if not ok:
            await inter.message.edit(view=PostNow())



REPLIES_STATE = os.path.join(HERE, "logs", "reply_cards.json")
KIND_LABEL = {"connection": "🤝 New connection", "invitation": "📩 Connection invite", "message": "📨 New LinkedIn message"}


def reply_card(a, draft, status, color, note=None):
    e = discord.Embed(title=f"{KIND_LABEL.get(a['kind'], '🔔 LinkedIn')}: {a['name']}", color=color,
                      timestamp=datetime.now().astimezone())
    if a.get("snippet"):
        e.add_field(name="💬 They said", value=a["snippet"][:1000], inline=False)
    e.add_field(name="✍️ Suggested reply (edit before approving if you like)", value=draft[:1000], inline=False)
    e.add_field(name="Status", value=status, inline=True)
    if a.get("profile"):
        e.add_field(name="Profile", value=a["profile"], inline=True)
    e.set_footer(text=note or "Nothing is sent until you approve, and you hit Send yourself")
    return e


def open_link(a):
    if a["kind"] == "message":
        return "https://www.linkedin.com/messaging/"
    if a["kind"] == "invitation":
        return "https://www.linkedin.com/mynetwork/invitation-manager/"
    return a.get("profile") or "https://www.linkedin.com/mynetwork/invite-connect/connections/"


class ReplyButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _go(self, inter, action):
        if not allowed(inter):
            await inter.response.send_message("Only the server owner can do this. 🙏", ephemeral=True)
            return
        rs = load_json(REPLIES_STATE, {})
        r = rs.get(str(inter.message.id))
        if not r:
            await inter.response.send_message("I can't find this alert. 🤔", ephemeral=True)
            return
        a, draft = r["alert"], r["draft"]
        when = nice_time()
        if action == "ok":
            await inter.response.edit_message(embed=reply_card(a, draft, "✅ Approved · " + when, GREEN), view=None)
            link = discord.ui.View()
            link.add_item(discord.ui.Button(label="Open in LinkedIn", emoji="🔗", url=open_link(a)))
            await inter.followup.send(f"✅ **Approved reply to {a['name']}**: long-press → Copy, then tap **🔗 Open in LinkedIn**, "
                                      f"paste and Send. 📲\n-# 🕒 {when}", view=link)
            await inter.channel.send(draft)
            r["status"] = "approved"
        elif action == "skip":
            await inter.response.edit_message(embed=reply_card(a, draft, "⏭️ Skipped · " + when, 0x95A5A6), view=None)
            await inter.followup.send(f"⏭️ Skipped {a['name']}. Nothing was sent.\n-# 🕒 {when}")
            r["status"] = "skipped"
        else:
            await inter.response.edit_message(embed=reply_card(a, draft, "✏️ Editing · " + when, ORANGE), view=self)
            try:
                th = await inter.message.create_thread(name=("✏️ reply to " + a["name"])[:95])
                await th.send("Type your version of the message here. I'll turn it into the final reply with ✅ ❌ buttons. ✍️")
            except discord.HTTPException:
                pass
            r["status"] = "editing"
        rs[str(inter.message.id)] = r
        save_json(REPLIES_STATE, rs)
        log("reply", action, a["name"])

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id="ch:rep_ok")
    async def ok(self, inter, button):
        await self._go(inter, "ok")

    @discord.ui.button(label="Edit", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="ch:rep_edit")
    async def ed(self, inter, button):
        await self._go(inter, "edit")

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.danger, custom_id="ch:rep_skip")
    async def sk(self, inter, button):
        await self._go(inter, "skip")


async def post_alert(guild, a, draft=None, extras=True):
    target = find_channel(guild, "message-drafts" if a["kind"] == "message" else "new-connections")
    if not target:
        return
    draft = draft or inbox.draft_for(a)
    m = await target.send(embed=reply_card(a, draft, "🕒 Waiting for you", BLUE), view=ReplyButtons())
    rs = load_json(REPLIES_STATE, {})
    rs[str(m.id)] = {"alert": a, "draft": draft, "status": "waiting", "posted": datetime.now().isoformat(timespec="seconds")}
    save_json(REPLIES_STATE, rs)
    if extras and a["kind"] in ("connection", "message"):
        contacts = find_channel(guild, "contacts")
        if contacts and a["kind"] == "connection":
            await contacts.send(f"👤 **{a['name']}**\n📍 Where we met: LinkedIn (connected {nice_time()})\n"
                                f"🔗 {a.get('profile') or 'profile link not in the email'}\n➡️ Next step: send the welcome message")
        due = add_reminder(f"Follow up with {a['name']} on LinkedIn", 3, "#" + target.name)
        await target.send(f"⏰ Follow-up reminder set for **{due.strftime('%a %b %d, 9 AM')}** in 🔁・follow-ups.\n-# 🕒 {nice_time()}")


class DraftButtons(discord.ui.View):
    """Persistent view: the buttons keep working after the bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _decide(self, inter, decision):
        if not allowed(inter):
            await inter.response.send_message("Only the server owner can approve or reject drafts. 🙏", ephemeral=True)
            return
        st = load_state()
        key = next((k for k, v in st.items() if v.get("message_id") == inter.message.id), None)
        if not key:
            await inter.response.send_message("I can't find the file for this draft. 🤔", ephemeral=True)
            return
        d = st[key]
        title, body = d["title"], d["body"]
        img = d.get("image")
        when = nice_time()
        drafted = d.get("posted_at")
        who = f"{inter.user.display_name} · {when}"
        if decision == "approve":
            await inter.response.edit_message(embed=card(title, body, "✅ Approved", GREEN, "Approved by " + who, img, drafted, "✅ Approved: " + when), view=None)
            dest = find_channel(inter.guild, APPROVED_CH)
            if dest:
                head = await dest.send(f"✅ **Approved:** {title}\n🗓️ {when}\n"
                                       + ("🚀 Posting it to LinkedIn for you now. Copy-ready version below 👇" if linkedin.ready()
                                          else "🖼️ Save the image, 📋 copy the text below, then post both on LinkedIn 👇"),
                                       view=None if linkedin.ready() else PostNow())
                d["approved_msg_id"] = head.id
                ip = image_for(key)
                if ip:
                    await dest.send(file=discord.File(ip))
                for i in range(0, len(body), 1900):
                    await dest.send(body[i:i + 1900])
            sub, status = "approved", "approved"
        elif decision == "reject":
            await inter.response.edit_message(embed=card(title, body, "❌ Rejected", RED, "Rejected by " + who, img, drafted, "❌ Rejected: " + when), view=None)
            sub, status = "rejected", "rejected"
        else:
            await inter.response.edit_message(embed=card(title, body, "✏️ Needs edits", ORANGE, "Sent back by " + who, img, drafted, "✏️ Sent back for edits: " + when), view=self)
            try:
                th = await inter.message.create_thread(name=("✏️ edits: " + title)[:95])
                await th.send("What should change? Reply here (tone, length, add or cut something) and the next version will come back with buttons. ✍️")
            except discord.HTTPException:
                pass
            sub, status = None, "needs edits"
        try:
            if decision == "approve":
                dest = find_channel(inter.guild, APPROVED_CH)
                await inter.followup.send(
                    f"✅ **Approved:** {title}\n"
                    + (f"🚀 Posting to LinkedIn now. Watch {dest.mention if dest else 'the approved channel'} for the link."
                       if linkedin.ready() else
                       f"👉 Next: open {dest.mention if dest else 'the approved channel'} → 🖼️ save the image → 📋 copy the text → "
                       "LinkedIn: **Start a post → add the photo → paste → Post**, or tap 🚀 once LinkedIn is connected."))
            elif decision == "reject":
                await inter.followup.send(f"❌ **Rejected:** {title}. Filed away, nothing else happens. "
                                          "Want a different angle on it? Drop the idea in this channel and a new draft will follow. ✍️")
            else:
                await inter.followup.send(f"✏️ **Sent back for edits:** {title}\n"
                                          "👉 Write what to change in the thread under the draft. I'll confirm I got it, "
                                          "and a new version with an image and buttons will come back here.")
        except discord.HTTPException:
            pass
        d["status"], d["decided_at"] = status, datetime.now().isoformat(timespec="seconds")
        if decision == "approve" and linkedin.ready():
            save_state(st)
            dest = find_channel(inter.guild, APPROVED_CH) or inter.channel
            await publish_to_linkedin(key, d, dest)
            st = load_state(); d = st[key]; d["status"] = "approved"
        src = os.path.join(DRAFTS, key)
        if sub and os.path.exists(src):
            os.makedirs(os.path.join(DRAFTS, sub), exist_ok=True)
            shutil.move(src, os.path.join(DRAFTS, sub, key))
        save_state(st)
        log(decision, key)

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id="ch:approve")
    async def approve(self, inter, button):
        await self._decide(inter, "approve")

    @discord.ui.button(label="Reject", emoji="❌", style=discord.ButtonStyle.danger, custom_id="ch:reject")
    async def reject(self, inter, button):
        await self._decide(inter, "reject")

    @discord.ui.button(label="Needs edits", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="ch:edit")
    async def edit(self, inter, button):
        await self._decide(inter, "edit")


class Bot(discord.Client):
    def __init__(self, read_text=True):
        intents = discord.Intents.default()
        intents.message_content = read_text
        self.read_text = read_text
        super().__init__(intents=intents)

    async def setup_hook(self):
        self.add_view(DraftButtons())
        self.add_view(PostNow())
        self.add_view(ReplyButtons())
        self.inbox_loop.start()
        self.scan.start()
        self.remind.start()

    async def on_message(self, msg):
        if msg.author.bot or not msg.guild or "career hunt" not in msg.guild.name.lower():
            return
        try:
            await handle_message(self, msg)
        except Exception as e:  # never let one message break the bot
            log("on_message error", type(e).__name__, e)


    @tasks.loop(minutes=3)
    async def inbox_loop(self):
        await self.wait_until_ready()
        if not inbox.configured():
            return
        guild = next((g for g in self.guilds if "career hunt" in g.name.lower()), None)
        if not guild:
            return
        try:
            alerts = await asyncio.to_thread(inbox.fetch)
        except Exception as e:
            log("inbox error", type(e).__name__, str(e)[:200])
            if not getattr(self, "_inbox_warned", False):
                self._inbox_warned = True
                ch = find_channel(guild, "follow-ups")
                if ch:
                    await ch.send(f"⚠️ I couldn't read your Gmail for LinkedIn alerts: {str(e)[:200]}\nAsk Claude to check the app password.")
            return
        self._inbox_warned = False
        for a in alerts:
            await post_alert(guild, a)
            log("inbox alert", a["kind"], a["name"])

    @tasks.loop(minutes=10)
    async def remind(self):
        await self.wait_until_ready()
        guild = next((g for g in self.guilds if "career hunt" in g.name.lower()), None)
        ch = guild and find_channel(guild, "follow-ups")
        if not ch:
            return
        left = linkedin.days_left()
        today = datetime.now().date().isoformat()
        if left is not None and left <= 5 and getattr(self, "_li_warned", None) != today:
            self._li_warned = today
            await ch.send(f"🔌 **LinkedIn connection expires in {max(left,0)} day(s).** Ask Claude for a fresh Allow link "
                          "so ✅ Approve keeps posting automatically.")
        rs = load_json(REMINDERS, [])
        now = datetime.now()
        changed = False
        for r in rs:
            if not r.get("sent") and datetime.fromisoformat(r["due"]) <= now:
                await ch.send(f"⏰ **Follow-up due:** {r['text']}\n↪️ from {r['where']} · set {nice_time(r['made'])} · due {nice_time(r['due'])}. React ✅ when done.")
                r["sent"] = now.isoformat(timespec="seconds")
                changed = True
        if changed:
            save_json(REMINDERS, rs)

    async def on_ready(self):
        log("ready as", self.user, "in", [g.name for g in self.guilds])

    @tasks.loop(seconds=60)
    async def scan(self):
        await self.wait_until_ready()
        guild = next((g for g in self.guilds if "career hunt" in g.name.lower()), None)
        ch = guild and find_channel(guild, DRAFTS_CH)
        if not ch:
            return
        st = load_state()
        for f in sorted(os.listdir(DRAFTS)):
            p = os.path.join(DRAFTS, f)
            if not f.endswith((".md", ".txt")) or not os.path.isfile(p) or f in st:
                continue
            title, body = read_draft(p)
            replaces = None
            if body.startswith("<!-- replaces:"):
                head, _, body = body.partition("-->")
                replaces = head.split(":", 1)[1].strip()
                body = body.strip()
            ip = image_for(f)
            if not ip:  # every post gets an image: make one from the draft
                proc = await asyncio.create_subprocess_exec(sys.executable, os.path.join(HERE, "make_image.py"), p,
                                                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                _, err = await proc.communicate()
                if proc.returncode:
                    log("image failed", f, (err or b"")[-300:].decode(errors="ignore"))
                ip = image_for(f)
            kw = {"file": discord.File(ip)} if ip else {}
            msg = await ch.send(embed=card(title, body, "🕒 Waiting for you", BLUE, "Tap a button below 👇", ip, datetime.now().isoformat(timespec="seconds")),
                                view=DraftButtons(), **kw)
            st[f] = {"message_id": msg.id, "title": title, "body": body, "status": "waiting",
                     "image": os.path.basename(ip) if ip else None,
                     "posted_at": datetime.now().isoformat(timespec="seconds")}
            if replaces and replaces in st:
                st[f]["replaces"] = replaces
                await self.collapse_old(ch, st[replaces], msg, title)
                st[replaces]["status"], st[replaces]["replaced_by"] = "replaced", f
            save_state(st)
            log("posted", f)

    async def collapse_old(self, ch, old, new_msg, new_title):
        """Shrink a replaced draft card to a short note that links to the new version."""
        try:
            m = await ch.fetch_message(old["message_id"])
            e = discord.Embed(title="♻️ OLD VERSION (replaced): " + old["title"][:200], color=0x95A5A6,
                              description=f"Rewritten from your notes, so this card has no buttons anymore.\n\n"
                                          f"👉 **[Tap here for the new version with ✅ ❌ ✏️ buttons]({new_msg.jump_url})**\n"
                                          f"*{new_title}*\n\nℹ️ Nothing on this card goes to LinkedIn. Only the text in "
                                          f"✅・approved-posts is meant to be posted.")
            await m.edit(embed=e, attachments=[], view=None)
            await new_msg.reply("🆕 **New version** of an earlier draft, rewritten from your notes. Tap ✅ ❌ or ✏️ below. 👇",
                                mention_author=False)
        except discord.HTTPException as ex:
            log("collapse failed", ex)


if __name__ == "__main__":
    tok = open(TOKEN_FILE).read().strip()
    try:
        Bot(read_text=True).run(tok, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        log("Message Content Intent is off in the Developer Portal; replies will be generic")
        Bot(read_text=False).run(tok, log_handler=None)
