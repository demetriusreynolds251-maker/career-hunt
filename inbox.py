#!/usr/bin/env python3
"""Reads ONLY LinkedIn notification emails from Gmail (read-only, never marks anything read,
never sends email) and turns them into Career Hunt alerts.

Credentials: secrets/gmail.json = {"address": "you@gmail.com", "app_password": "xxxx xxxx xxxx xxxx"}
(a Google "app password", made by you; revoke it anytime at myaccount.google.com/apppasswords).

  python3 inbox.py --test     # connect and list the last LinkedIn emails it would turn into alerts
"""
import email, imaplib, json, os, re, sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS = os.path.join(HERE, "secrets", "gmail.json")
SEEN = os.path.join(HERE, "logs", "inbox_seen.json")
UNKNOWN = os.path.join(HERE, "logs", "inbox_unknown.jsonl")


def configured():
    return os.path.exists(CREDS)


def _hdr(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _bodies(msg):
    text, html = "", ""
    for part in msg.walk():
        ct = part.get_content_type()
        if part.get_content_maintype() == "multipart":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            s = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            continue
        if ct == "text/plain" and not text:
            text = s
        elif ct == "text/html" and not html:
            html = s
    if not text and html:
        text = unescape(re.sub(r"<[^>]+>", " ", html))
    return text, html


def _profile_url(text, html):
    for src in (html, text):
        m = re.search(r"https?://(?:www\.)?linkedin\.com/(?:comm/)?in/([A-Za-z0-9\-_%]+)", src or "")
        if m:
            return "https://www.linkedin.com/in/" + m.group(1).split("?")[0] + "/"
    return None


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


PATTERNS = [
    # (kind, regex on subject that captures the person's name)
    ("connection", re.compile(r"^(.+?) accepted your invitation", re.I)),
    ("connection", re.compile(r"start a conversation with your new connection,? (.+)$", re.I)),
    ("connection", re.compile(r"^(?:you(?:'re| are) now connected with|new connection:?)\s*(.+)$", re.I)),
    ("invitation", re.compile(r"^(.+?) (?:wants to connect|would like to connect|has invited you to connect)", re.I)),
    ("invitation", re.compile(r"^(?:invitation|i'd like to connect)(?: from)?:?\s*(.+)$", re.I)),
    ("message", re.compile(r"^(.+?) (?:sent you a (?:new )?message|messaged you|just messaged you|sent you a message)", re.I)),
    ("message", re.compile(r"^(?:new message from|message from)\s+(.+)$", re.I)),
]


def classify(subject):
    s = _clean(subject)
    for kind, rx in PATTERNS:
        m = rx.search(s)
        if m:
            name = re.sub(r"[,.!:]+$", "", m.group(1)).strip()
            name = re.sub(r"^(?:[A-Z][a-z]+,\s*)", "", name) if kind == "connection" and "," in name else name
            return kind, name
    return None, None


def _snippet(text, name):
    t = _clean(text)
    first = (name or "").split(" ")[0]
    i = t.find(first) if first else -1
    chunk = t[i:i + 400] if i >= 0 else t[:400]
    chunk = re.split(r"(?:View message|Reply|Unsubscribe|This email was intended)", chunk)[0]
    return chunk[:280].strip()


def fetch(days=3, limit=40):
    """New LinkedIn alerts since the last check: list of dicts (kind, name, profile, snippet, subject, at, id)."""
    c = json.load(open(CREDS))
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(c["address"], c["app_password"].replace(" ", ""))
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(SINCE {since} FROM "linkedin.com")')
        ids = (data[0].split() if data and data[0] else [])[-limit:]
        out = []
        for i in ids:
            typ, md = M.fetch(i, "(BODY.PEEK[])")
            if not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            mid = msg.get("Message-ID") or i.decode()
            if mid in seen:
                continue
            seen.add(mid)
            subject = _hdr(msg.get("Subject"))
            kind, name = classify(subject)
            if not kind:
                os.makedirs(os.path.dirname(UNKNOWN), exist_ok=True)
                with open(UNKNOWN, "a") as f:
                    f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "subject": subject}) + "\n")
                continue
            text, html = _bodies(msg)
            out.append({"id": mid, "kind": kind, "name": name, "subject": subject,
                        "profile": _profile_url(text, html), "snippet": _snippet(text, name) if kind == "message" else "",
                        "at": _hdr(msg.get("Date"))})
        os.makedirs(os.path.dirname(SEEN), exist_ok=True)
        json.dump(sorted(seen)[-2000:], open(SEEN, "w"))
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass


def draft_for(alert):
    first = (alert["name"] or "there").split(" ")[0]
    if alert["kind"] == "connection":
        return (f"Hi {first}, thanks for connecting! I'm an operations and business professional based in Mobile, AL, "
                f"and in my spare time I build data tools with AI. A little about me: https://demetriusreynolds251-maker.github.io "
                f"I'd love to hear what you're working on these days. Anything exciting on your plate?")
    if alert["kind"] == "invitation":
        return (f"Hi {first}, thanks for the invite, happy to connect! What made you reach out? "
                f"Always glad to meet people working in operations and business.")
    return (f"Hi {first}, thanks for your message! Happy to help. "
            f"[add your answer here] What's a good time to chat this week?")


if __name__ == "__main__":
    if "--test" in sys.argv:
        had = os.path.exists(SEEN)
        if had:
            os.rename(SEEN, SEEN + ".bak")
        try:
            for a in fetch(days=14):
                print(a["kind"], "|", a["name"], "|", a["profile"], "|", a["snippet"][:60])
        finally:  # a test never changes what the bot considers "already seen"
            if had:
                os.replace(SEEN + ".bak", SEEN)
            elif os.path.exists(SEEN):
                os.remove(SEEN)
    else:
        print(__doc__)
