#!/usr/bin/env python3
"""Makes a 1080x1080 post image for a draft that doesn't have one yet.

  python3 make_image.py drafts/04-something.md     -> drafts/04-something.png

Headline = the draft's title. Up to 4 key points are pulled from bullet or numbered
lines (•, -, 1️⃣, 1., emoji-led lines). With no bullets, the first strong sentence is
used as a quote. Same dark-and-green look as the Apex site, with your name at the bottom.
A hand-made image with the same name always wins: this never overwrites one.
"""
import html, os, re, sys

FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700;800'
         '&family=Inter:wght@500;600;700&family=JetBrains+Mono:wght@700&display=swap" rel="stylesheet">')
CSS = """*{box-sizing:border-box;margin:0}
body{width:1080px;height:1080px;background:#0b0f17;color:#e6ebf5;font-family:Inter,system-ui,sans-serif;overflow:hidden;position:relative}
.glow{position:absolute;right:-220px;top:-220px;width:760px;height:760px;background:radial-gradient(closest-side,rgba(62,230,168,.22),transparent)}
.pad{position:relative;padding:84px;height:100%;display:flex;flex-direction:column}
.eyebrow{font:700 22px/1 "JetBrains Mono",monospace;letter-spacing:.16em;text-transform:uppercase;color:#3ee6a8}
h1{font:800 HSIZEpx/1.06 "Space Grotesk",Inter,sans-serif;margin:26px 0 0;letter-spacing:-.01em}
h1 em{font-style:normal;color:#3ee6a8}
.pts{margin-top:44px;display:grid;gap:16px}
.p{display:flex;gap:22px;align-items:center;background:#141c2b;border:2px solid #243049;border-radius:22px;padding:22px 26px;font:700 PSIZEpx/1.3 Inter}
.p b{font:800 40px "Space Grotesk";color:#3ee6a8;min-width:44px}
.quote{margin-top:48px;background:#141c2b;border:2px solid #3ee6a8;border-radius:24px;padding:34px 36px;font:700 40px/1.35 Inter}
.foot{margin-top:auto;display:flex;justify-content:space-between;align-items:center;font:600 24px Inter;color:#9aa6bd}
.foot b{color:#e6ebf5}
.dot{display:inline-block;width:14px;height:14px;border-radius:50%;background:#3ee6a8;box-shadow:0 0 16px #3ee6a8;margin-right:12px;vertical-align:middle}"""
BULLET = re.compile(r"^\s*(?:[•\-\*]|\d+[.)]|\d️?⃣|[\U0001F300-\U0001FAFF☀-➿]️?)\s*(.+)$")
EMOJI = re.compile(r"^([\U0001F300-\U0001FAFF☀-➿]️?)\s*")


def parse(path):
    text = open(path, encoding="utf-8").read().strip()
    first, _, rest = text.partition("\n")
    title = first.lstrip("# ").strip()
    lines = [l.strip() for l in rest.splitlines() if l.strip()]
    pts = []
    for l in lines:
        m = BULLET.match(l)
        if m and len(m.group(1)) > 8 and not l.endswith("?"):
            pts.append(re.split(r"(?<=[.!])\s", m.group(1).strip())[0].rstrip("."))
    quote = None
    punch = next((l for l in lines if not BULLET.match(l) and 30 <= len(l) <= 120 and not l.endswith("?")
                  and l not in lines[:1] and not l.endswith(":") and "http" not in l and "://" not in l),
                 None) if 2 <= len(pts) <= 3 else None
    if len(pts) < 2:
        pts = []
        sents = re.split(r"(?<=[.!?])\s+", " ".join(lines))
        quote = next((s for s in sents if 40 <= len(s) <= 140 and not s.endswith("?")), sents[0][:140] if sents else title)
    return title, pts[:4], quote or punch


def page(title, pts, quote):
    em = EMOJI.match(title)
    eyebrow = (em.group(1) + " " if em else "✍️ ") + "Lessons from work"
    t = EMOJI.sub("", title)
    words = t.split()
    if len(words) > 3:  # highlight the last two words
        t = html.escape(" ".join(words[:-2])) + " <em>" + html.escape(" ".join(words[-2:])) + "</em>"
    else:
        t = html.escape(t)
    hsize = 76 if len(title) < 34 else 64 if len(title) < 56 else 54
    body = ""
    if pts:
        psize = 30 if max(len(p) for p in pts) < 46 else 26
        body = '<div class="pts">' + "".join(f'<div class="p"><b>{i}</b><div>{html.escape(p)}</div></div>'
                                             for i, p in enumerate(pts, 1)) + "</div>"
        if quote:
            body += f'<div class="quote" style="font-size:32px;margin-top:28px">{html.escape(quote)}</div>'
    else:
        psize = 30
        body = f'<div class="quote">“{html.escape(quote)}”</div>'
    css = CSS.replace("HSIZE", str(hsize)).replace("PSIZE", str(psize))
    return (f"<html><head>{FONTS}<style>{css}</style></head><body><div class='glow'></div><div class='pad'>"
            f"<div class='eyebrow'>{html.escape(eyebrow)}</div><h1>{t}</h1>{body}"
            "<div class='foot'><span><span class='dot'></span><b>Demetrius Reynolds</b></span>"
            "<span>Operations · Mobile, AL</span></div></div></body></html>")


def make(path):
    out = os.path.splitext(path)[0] + ".png"
    if os.path.exists(out):
        return out
    from playwright.sync_api import sync_playwright
    tmp = os.path.splitext(path)[0] + ".imgsrc.html"
    open(tmp, "w", encoding="utf-8").write(page(*parse(path)))
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1080, "height": 1080})
            pg.goto("file://" + os.path.abspath(tmp))
            pg.wait_for_timeout(1200)
            pg.screenshot(path=out)
            b.close()
    finally:
        os.remove(tmp)
    return out


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(make(a))
