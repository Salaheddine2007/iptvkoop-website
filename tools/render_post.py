"""Render a blog post into tools/post_layout.html (the homepage-styled layout).

Used by tools/publish_post.py (new posts) and by the one-off restyle of existing posts.
Placeholders in the layout: {{SEO}} {{TITLE}} {{DATE_ISO}} {{DATE}} {{READ}} {{ARTICLE}} {{NAV}}
The prev/next block is wrapped in <!--NAV-->…<!--/NAV--> so it can be swapped later.
"""
import html, os, re
from datetime import datetime

TOOLS = os.path.dirname(os.path.abspath(__file__))
MONTHS = {"nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
                 "september", "oktober", "november", "december"]}
LABELS = {"nl": {"prev": "Vorig artikel", "next": "Volgend artikel", "read": "min leestijd"}}

def layout_available():
    return os.path.exists(os.path.join(TOOLS, "post_layout.html"))

def nice_date(iso, lang="nl"):
    d = datetime.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[lang][d.month - 1]} {d.year}"

def nav_html(prev=None, nxt=None, lang="nl"):
    lab = LABELS[lang]
    parts = []
    if prev:
        parts.append(f'<a class="kp-prev" href="{prev["url"]}" rel="prev"><small>&larr; {lab["prev"]}</small>'
                     f'<span>{html.escape(prev["title"])}</span></a>')
    if nxt:
        parts.append(f'<a class="kp-next" href="{nxt["url"]}" rel="next"><small>{lab["next"]} &rarr;</small>'
                     f'<span>{html.escape(nxt["title"])}</span></a>')
    return "<!--NAV-->" + (f'<nav class="kp-pn" aria-label="Artikelen">{"".join(parts)}</nav>' if parts else "") + "<!--/NAV-->"

def replace_nav(page, new_nav):
    return re.sub(r"<!--NAV-->.*?<!--/NAV-->", lambda m: new_nav, page, count=1, flags=re.S)

def render(seo_head, title, date_iso, article, prev=None, nxt=None, lang="nl"):
    # the banner shows the H1 -> drop the article's own first H1 (exactly one H1 per page)
    article = re.sub(r"<h1\b[^>]*>.*?</h1>\s*", "", article, count=1, flags=re.S | re.I)
    # some old articles carry extra H1s inside the text -> demote to H2
    article = re.sub(r"<(/?)h1\b", r"<\1h2", article, flags=re.I)
    words = len(re.sub(r"<[^>]+>", " ", article).split())
    page = open(os.path.join(TOOLS, "post_layout.html"), encoding="utf-8").read()
    for k, v in (("{{SEO}}", "<!--SEO-->" + seo_head + "<!--/SEO-->"), ("{{TITLE}}", html.escape(title)), ("{{DATE_ISO}}", date_iso),
                 ("{{DATE}}", nice_date(date_iso, lang)), ("{{READ}}", f"{max(1, round(words / 220))} {LABELS[lang]['read']}"),
                 ("{{NAV}}", nav_html(prev, nxt, lang)), ("{{ARTICLE}}", "<!--ARTICLE-->" + article + "<!--/ARTICLE-->")):
        page = page.replace(k, v)
    return page

def parse_rendered(page):
    """(seo_head, title, date_iso, article) back out of a page made by render()."""
    seo = re.search(r"<!--SEO-->(.*?)<!--/SEO-->", page, re.S).group(1)
    art = re.search(r"<!--ARTICLE-->(.*?)<!--/ARTICLE-->", page, re.S).group(1)
    title = html.unescape(re.search(r'<header class="kp-hero">.*?<h1>(.*?)</h1>', page, re.S).group(1))
    date_iso = re.search(r'<time datetime="([^"]+)"', page).group(1)
    return seo, title, date_iso, art
