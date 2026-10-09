"""Publish one blog post on a static (ex-WordPress) site — replaces the WP REST + Rank Math step.

Lives in each site repo as tools/publish_post.py, next to tools/site.json and tools/posts.json.

  python3 tools/publish_post.py --keyword "iptv kopen" --slug iptv-kopen \
      --title "Iptv Kopen" --meta-title "Iptv Kopen - ..." --meta-desc "..." --article article.html
  python3 tools/publish_post.py --check-slug iptv-kopen     # prints EXISTS / FREE

What it does (what WordPress + Rank Math used to do):
  - builds <slug>/index.html from the site's own post template (same header/footer/design)
  - writes title, meta description, canonical, robots, Open Graph, Twitter, and JSON-LD
    (BlogPosting + BreadcrumbList, + FAQPage when the article has an FAQ section)
  - links the new post <-> previous newest post (prev/next navigation, like WP)
  - adds the URL to sitemap.xml and records it in tools/posts.json
"""
import argparse, html, json, os, re, sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")

def load(name):
    with open(os.path.join(TOOLS, name), encoding="utf-8") as f:
        return json.load(f)

def find_block(doc, open_re, tag):
    """(start, inner_start, inner_end, end) of the first element matching open_re, nesting-aware."""
    m = re.search(open_re, doc)
    if not m:
        return None
    depth, i = 1, m.end()
    t = re.compile(r"<(/?)%s\b[^>]*>" % tag, re.I)
    while depth:
        n = t.search(doc, i)
        if not n:
            return None
        depth += -1 if n.group(1) else 1
        i = n.end()
        if depth == 0:
            return m.start(), m.end(), n.start(), n.end()

def set_meta(doc, attr, name, value):
    pat = re.compile(r'(<meta\s+%s="%s"\s+content=")[^"]*(")' % (attr, re.escape(name)))
    return pat.sub(lambda m: m.group(1) + value + m.group(2), doc, count=1)

def faq_pairs(article):
    """Questions = <h3> after an FAQ <h2>; answer = text until the next heading."""
    m = re.search(r"<h2[^>]*>[^<]*(FAQ|Veelgestelde|Veel gestelde|Usein kysy|Kysymyks)[^<]*</h2>(.*?)(?=<h2|\Z)",
                  article, re.I | re.S)
    if not m:
        return []
    pairs = []
    for q, a in re.findall(r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|\Z)", m.group(2), re.S):
        q = html.unescape(re.sub(r"<[^>]+>", "", q)).strip()
        a = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", a))).strip()
        if q and a:
            pairs.append((q, a))
    return pairs

def schema(site, url, title, desc, now, article):
    org = {"@type": "Organization", "@id": f"{site['base']}/#organization", "name": site["name"], "url": site["base"]}
    if site.get("logo"):
        org["logo"] = {"@type": "ImageObject", "url": site["logo"]}
    graph = [
        org,
        {"@type": "WebSite", "@id": f"{site['base']}/#website", "url": site["base"], "name": site["name"],
         "publisher": {"@id": f"{site['base']}/#organization"}, "inLanguage": site["lang"]},
        {"@type": "BreadcrumbList", "@id": f"{url}#breadcrumb", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": site["base"] + "/"},
            {"@type": "ListItem", "position": 2, "name": title, "item": url}]},
        {"@type": "WebPage", "@id": f"{url}#webpage", "url": url, "name": title, "datePublished": now,
         "dateModified": now, "isPartOf": {"@id": f"{site['base']}/#website"}, "inLanguage": site["lang"],
         "breadcrumb": {"@id": f"{url}#breadcrumb"}},
        {"@type": "BlogPosting", "@id": f"{url}#article", "headline": title, "description": desc,
         "datePublished": now, "dateModified": now, "author": {"@id": f"{site['base']}/#organization"},
         "publisher": {"@id": f"{site['base']}/#organization"}, "mainEntityOfPage": {"@id": f"{url}#webpage"},
         "inLanguage": site["lang"], "wordCount": len(re.sub(r"<[^>]+>", " ", article).split())},
    ]
    qa = faq_pairs(article)
    if qa:
        graph.append({"@type": "FAQPage", "@id": f"{url}#faq", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa]})
    data = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
    return f'<script type="application/ld+json" class="rank-math-schema">{data}</script>', len(qa)

def nav_html(prev=None, nxt=None):
    parts = []
    if prev:
        parts.append(f'<div class="nav-previous"><a href="{prev["url"]}" rel="prev">&larr; {html.escape(prev["title"])}</a></div>')
    if nxt:
        parts.append(f'<div class="nav-next"><a href="{nxt["url"]}" rel="next">{html.escape(nxt["title"])} &rarr;</a></div>')
    return ('<nav class="navigation post-navigation" aria-label="Posts"><div class="nav-links">'
            + "".join(parts) + "</div></nav>")

def replace_nav(doc, new_nav):
    b = find_block(doc, r'<nav class="navigation post-navigation"[^>]*>', "nav")
    return doc[: b[0]] + new_nav + doc[b[3]:] if b else doc

def page_path(slug):
    return os.path.join(REPO, slug, "index.html")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-slug")
    ap.add_argument("--keyword"); ap.add_argument("--slug"); ap.add_argument("--title")
    ap.add_argument("--meta-title"); ap.add_argument("--meta-desc"); ap.add_argument("--article", default="article.html")
    a = ap.parse_args()

    if a.check_slug:
        print("EXISTS" if os.path.exists(page_path(a.check_slug)) else "FREE")
        return

    site, posts = load("site.json"), load("posts.json")
    if os.path.exists(page_path(a.slug)):
        sys.exit(f"ERROR: /{a.slug}/ already exists — pick the next keyword")
    article = open(a.article, encoding="utf-8").read().strip()
    n_words = len(re.sub(r"<[^>]+>", " ", article).split())
    min_words = int(site.get("min_words", 0))
    if n_words < max(300, min_words):
        sys.exit(f"ERROR: article has {n_words} words, minimum is {max(300, min_words)}. "
                 "Expand the article (more depth per section, more H3 subsections, longer FAQ answers) "
                 "in the same file and run this command again.")

    url = f"{site['base']}/{a.slug}/"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    title, mt = html.escape(a.title, quote=True), html.escape(a.meta_title, quote=True)
    md = html.escape(a.meta_desc, quote=True)
    prev = posts[-1] if posts else None

    sys.path.insert(0, TOOLS)
    import render_post as R
    if R.layout_available():
        # homepage-styled layout: write the SEO head ourselves and render the page
        ld, n_faq = schema(site, url, a.title, a.meta_desc, now, article)
        seo = "\n".join([
            f"<title>{mt}</title>",
            f'<meta name="description" content="{md}"/>',
            '<meta name="robots" content="follow, index, max-snippet:-1, max-video-preview:-1, max-image-preview:large"/>',
            f'<link rel="canonical" href="{url}" />',
            f'<meta property="og:locale" content="{site["lang"].replace("-", "_")}" />',
            '<meta property="og:type" content="article" />',
            f'<meta property="og:title" content="{mt}" />',
            f'<meta property="og:description" content="{md}" />',
            f'<meta property="og:url" content="{url}" />',
            f'<meta property="og:site_name" content="{html.escape(site["name"])}" />',
            f'<meta property="article:published_time" content="{now}" />',
            f'<meta property="article:modified_time" content="{now}" />',
            '<meta name="twitter:card" content="summary_large_image" />',
            f'<meta name="twitter:title" content="{mt}" />',
            f'<meta name="twitter:description" content="{md}" />',
            ld])
        doc = R.render(seo, a.title, now, article, prev=prev, lang=site["lang"][:2])
        os.makedirs(os.path.dirname(page_path(a.slug)), exist_ok=True)
        open(page_path(a.slug), "w", encoding="utf-8").write(doc)
        if prev and os.path.exists(page_path(prev["slug"])):
            p = open(page_path(prev["slug"]), encoding="utf-8").read()
            before = posts[-2] if len(posts) > 1 else None
            p = R.replace_nav(p, R.nav_html(before, {"url": url, "title": a.title}, site["lang"][:2]))
            open(page_path(prev["slug"]), "w", encoding="utf-8").write(p)
        finish(site, posts, a, url, now, article, n_faq, prev)
        return

    doc = open(os.path.join(TOOLS, "post_template.html"), encoding="utf-8").read()

    # ---- head: SEO tags (what Rank Math generated) ----
    doc = re.sub(r"<title>.*?</title>", f"<title>{mt}</title>", doc, count=1, flags=re.S)
    doc = re.sub(r'<meta name="description" content="[^"]*"\s*/?>', f'<meta name="description" content="{md}"/>', doc, count=1)
    doc = re.sub(r'<meta name="robots" content="[^"]*"\s*/?>',
                 '<meta name="robots" content="follow, index, max-snippet:-1, max-video-preview:-1, max-image-preview:large"/>', doc, count=1)
    doc = re.sub(r'<link rel="canonical" href="[^"]*"\s*/?>', f'<link rel="canonical" href="{url}" />', doc, count=1)
    for prop, val in (("og:title", mt), ("og:description", md), ("og:url", url), ("og:type", "article"),
                      ("og:updated_time", now), ("article:published_time", now), ("article:modified_time", now)):
        doc = set_meta(doc, "property", prop, val)
    for name, val in (("twitter:title", mt), ("twitter:description", md)):
        doc = set_meta(doc, "name", name, val)
    # template's own image would be wrong for this post
    doc = re.sub(r'<meta (?:property|name)="(?:og:image[^"]*|twitter:image)"[^>]*/?>\s*', "", doc)
    ld, n_faq = schema(site, url, a.title, a.meta_desc, now, article)
    doc, n = re.subn(r'<script type="application/ld\+json" class="rank-math-schema">.*?</script>', lambda m: ld, doc, count=1, flags=re.S)
    if not n:
        doc = doc.replace("</head>", ld + "</head>", 1)

    # ---- body ----
    if re.search(r"<h1\b", article):
        # the article brings its own styled H1 -> drop the theme's title H1 (avoid two H1s)
        doc = re.sub(r'<h1 class="entry-title"[^>]*>.*?</h1>', "", doc, count=1, flags=re.S)
    else:
        doc = re.sub(r'(<h1 class="entry-title"[^>]*>).*?(</h1>)', lambda m: m.group(1) + title + m.group(2), doc, count=1, flags=re.S)
    for itemprop in ("datePublished", "dateModified"):
        doc = re.sub(r'(<time[^>]*datetime=")[^"]*("[^>]*itemprop="%s"[^>]*>)[^<]*(</time>)' % itemprop,
                     lambda m: m.group(1) + now + m.group(2) + datetime.now(timezone.utc).strftime("%B %d, %Y") + m.group(3), doc)
    thumb = find_block(doc, r'<div class="post-thumb-img-content[^"]*"[^>]*>', "div")
    if thumb:
        doc = doc[: thumb[0]] + doc[thumb[3]:]
    body = find_block(doc, r'<div class="entry-content[^"]*"[^>]*>', "div")
    if not body:
        sys.exit("ERROR: template has no entry-content block")
    doc = doc[: body[1]] + "\n" + article + "\n" + doc[body[2]:]
    doc = replace_nav(doc, nav_html(prev=prev))

    os.makedirs(os.path.dirname(page_path(a.slug)), exist_ok=True)
    with open(page_path(a.slug), "w", encoding="utf-8") as f:
        f.write(doc)

    # ---- previous newest post now gets a "next" link to this one ----
    if prev and os.path.exists(page_path(prev["slug"])):
        p = open(page_path(prev["slug"]), encoding="utf-8").read()
        before = posts[-2] if len(posts) > 1 else None
        p2 = replace_nav(p, nav_html(prev=before, nxt={"url": url, "title": a.title}))
        if p2 == p:  # template had no nav block: append one after the article
            p2 = p.replace("</article>", "</article>" + nav_html(prev=before, nxt={"url": url, "title": a.title}), 1)
        open(page_path(prev["slug"]), "w", encoding="utf-8").write(p2)
    finish(site, posts, a, url, now, article, n_faq, prev)

def finish(site, posts, a, url, now, article, n_faq, prev):
    """sitemap + posts registry + report (shared by both layouts)"""
    sm_path = os.path.join(REPO, "sitemap.xml")
    sm = open(sm_path, encoding="utf-8").read()
    if url not in sm:
        sm = sm.replace("</urlset>", f"  <url><loc>{url}</loc><lastmod>{now[:10]}</lastmod></url>\n</urlset>")
        open(sm_path, "w", encoding="utf-8").write(sm)
    posts.append({"slug": a.slug, "url": url, "title": a.title, "keyword": a.keyword, "date": now[:10]})
    with open(os.path.join(TOOLS, "posts.json"), "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=1)

    words = len(re.sub(r"<[^>]+>", " ", article).split())
    print(f"PUBLISHED {url} | words={words} | faq_schema={n_faq} | prev={prev['slug'] if prev else None}")

if __name__ == "__main__":
    main()
