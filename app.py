"""
KK Stories - Kindle Edition Web App
Real-time scraper for kkstories.com with global search & multi-part support
"""

from flask import Flask, render_template_string, request, redirect
import requests
import re
import base64
import html as html_module
import os
import urllib.parse
import time

app = Flask(__name__)

BASE_URL = "https://kkstories.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
REQUEST_TIMEOUT = 20       # seconds per HTTP request
MAX_CHAPTER_PAGES = 50     # safety cap — no chapter should exceed 50 pages

# ============ SCRAPER FUNCTIONS ============

def decode_protected_content(page_html):
    """Decode Base64-protected story content.
    Real site uses double-quoted data-protected-payload attribute.
    """
    match = re.search(
        r"""data-protected-payload=["']([^"']+)["']""",
        page_html
    )
    if not match:
        match = re.search(r'data-protected-payload=([A-Za-z0-9+/=]+)', page_html)
    if match:
        try:
            return base64.b64decode(match.group(1)).decode('utf-8')
        except Exception:
            return None
    return None

def parse_story_cards(page_html):
    """Extract story data from HTML story cards"""
    stories = []
    story_cards = re.findall(r'<article class="story-card[^"]*"[^>]*>(.*?)</article>', page_html, re.DOTALL)

    for card in story_cards:
        title_match = re.search(
            r'<h3>.*?<a[^>]+href=["\'](/story/[^/]+/)["\'][^>]*>(.*?)</a>.*?</h3>',
            card, re.DOTALL
        )
        if not title_match:
            continue

        url = title_match.group(1)
        title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()

        if url == '/story/new/':
            continue

        author = "Unknown"
        bracket_match = re.search(r'\[([^\]]+)\]', title)
        if bracket_match:
            author = bracket_match.group(1).strip()

        meta_match = re.search(r'<p class="story-row-meta">(.*?)</p>', card, re.DOTALL)
        if meta_match:
            by_match = re.search(r'by\s*([^<]+)', meta_match.group(1))
            if by_match:
                author = by_match.group(1).strip()

        status_match = re.search(r'(Ongoing|Completed)', card)
        status = status_match.group(1) if status_match else ""

        views_match = re.search(r'👁\s*([\d,]+)', card)
        views = views_match.group(1) if views_match else ""

        ch_match = re.search(r'📚\s*(\d+)', card)
        chapters = ch_match.group(1) if ch_match else ""

        comm_match = re.search(r'💬\s*(\d+)', card)
        comments = comm_match.group(1) if comm_match else ""

        cat_matches = re.findall(
            r'<a[^>]+href=["\']/library/\?category=[^"\']+["\'][^>]*>([^<]+)</a>',
            card
        )
        categories = ', '.join(cat_matches) if cat_matches else ""

        stories.append({
            "url": url,
            "title": title,
            "author": author,
            "status": status,
            "views": views,
            "chapters": chapters,
            "comments": comments,
            "categories": categories
        })

    return stories

def get_homepage_stories():
    """Scrape homepage for all stories"""
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    return parse_story_cards(resp.text)

def search_stories(query, page=1):
    """Search stories across the entire site"""
    if not query:
        return [], 0, False

    encoded_query = urllib.parse.quote(query)
    url = f"{BASE_URL}/library/?q={encoded_query}"
    if page > 1:
        url += f"&page={page}"

    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    stories = parse_story_cards(resp.text)

    total_match = re.search(r'(\d+)\s+results?', resp.text, re.IGNORECASE)
    total = int(total_match.group(1)) if total_match else len(stories)

    has_more = f'page={page + 1}' in resp.text

    return stories, total, has_more

def get_story_info(story_url):
    """Get story metadata, chapters, AND part links"""
    resp = requests.get(story_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    page_html = resp.text

    title_match = re.search(r'<title>([^<]+)</title>', page_html)
    title = title_match.group(1).split('·')[0].strip() if title_match else "Unknown"

    # Real site: <a class="story-author-name" href="/author/username/">username</a>
    author_match = re.search(
        r"""href=["']/author/[^/]+/["'][^>]*>([^<]+)</a>""",
        page_html
    )
    author = author_match.group(1).strip() if author_match else "Unknown"

    # Collect ALL chapter links across all paginated pages
    # (Site paginates at 24 chapters per page using ?page=N)
    all_chapter_links = set()
    ch_page = 1
    ch_html = page_html  # first page already fetched
    while True:
        found = re.findall(
            r'href="(/story/[^/]+/chapter/\d+/)"',
            ch_html
        )
        all_chapter_links.update(found)
        # Check if there is a next page in the pagination nav
        next_page_num = ch_page + 1
        if f'?page={next_page_num}' not in ch_html and f'page={next_page_num}' not in ch_html:
            break  # no more pages
        # Fetch the next page
        ch_page = next_page_num
        try:
            pg_resp = requests.get(f'{story_url}?page={ch_page}', headers=HEADERS, timeout=REQUEST_TIMEOUT)
            ch_html = pg_resp.text
        except Exception:
            break
    unique_chapters = sorted(
        all_chapter_links,
        key=lambda x: int(re.search(r'chapter/(\d+)', x).group(1))
    )

    # NEW: Detect multi-part stories (separate pages like "Part 2", "Part 3")
    part_links = []

    # Look for "Previous Post" / "Next Post" navigation
    prev_match = re.search(
        r'←\s*Previous.*?href=["\'](/story/[^"\']+)["\']',
        page_html, re.DOTALL | re.IGNORECASE
    )
    next_match = re.search(
        r'Next\s*→.*?href=["\'](/story/[^"\']+)["\']',
        page_html, re.DOTALL | re.IGNORECASE
    )

    if prev_match:
        part_links.append(prev_match.group(1))
    if next_match:
        part_links.append(next_match.group(1))

    # Look for "Part X" links in content
    part_pattern = re.findall(
        r'href=["\'](/story/[^"\']*(?:part[-_]?\d+|പാർട്ട്)[^"\']*/?)["\']',
        page_html, re.IGNORECASE
    )
    part_links.extend(part_pattern)

    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        page_html
    )
    description = desc_match.group(1) if desc_match else ""

    return {
        "title": title,
        "author": author,
        "description": description,
        "chapters": unique_chapters,
        "parts": list(set(part_links))
    }

def get_chapter_content(chapter_url):
    """Fetch and decode a single chapter, following all content pages.
    
    IMPORTANT: Each chapter can be split into multiple pages (e.g. ?page=2).
    We must collect content from ALL pages and concatenate them.
    
    Real site structure:
    <article class="reader">
      <header class="reader-header"><h1>Title</h1></header>
      <div class="chapter-body protected-reader-content"
           data-protected-payload="BASE64...">
      </div>
    </article>
    """
    resp = requests.get(chapter_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    page_html = resp.text

    # Extract chapter title from <h1> inside reader-header (first page only)
    header_match = re.search(r'<header[^>]*class="reader-header"[^>]*>(.*?)</header>', page_html, re.DOTALL)
    title = ""
    if header_match:
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', header_match.group(1))
        title = h1_match.group(1).strip() if h1_match else ""
    if not title:
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', page_html)
        title = h1_match.group(1).strip() if h1_match else ""

    # Collect content from ALL pages of this chapter
    all_paragraphs = []
    pg_num = 1
    pg_html = page_html  # first page already fetched

    while pg_num <= MAX_CHAPTER_PAGES:
        # Decode protected content
        content = decode_protected_content(pg_html)

        if content:
            paras = re.findall(r'<p[^>]*>(.*?)</p>', content, re.DOTALL)
            for p in paras:
                text = re.sub(r'<[^>]+>', '', p).strip()
                text = html_module.unescape(text)  # convert &quot; &amp; etc.
                if text:
                    all_paragraphs.append(text)
        else:
            # Fallback: extract from chapter-body div to avoid header/nav junk
            body_match = re.search(r'<div[^>]*class="[^"]*chapter-body[^"]*"[^>]*>(.*?)</div>', pg_html, re.DOTALL)
            source = body_match.group(1) if body_match else pg_html
            paras = re.findall(r'<p[^>]*>(.*?)</p>', source, re.DOTALL)
            for p in paras:
                text = re.sub(r'<[^>]+>', '', p).strip()
                text = html_module.unescape(text)  # convert &quot; &amp; etc.
                if text:
                    all_paragraphs.append(text)

        # Check if there is a next page for this chapter content
        next_pg = pg_num + 1
        if f'?page={next_pg}' not in pg_html and f'page={next_pg}' not in pg_html:
            break  # No more pages

        # Fetch next page
        pg_num = next_pg
        try:
            sep = "&" if "?" in chapter_url else "?"
            pg_resp = requests.get(f"{chapter_url}{sep}page={pg_num}", headers=HEADERS, timeout=REQUEST_TIMEOUT)
            pg_html = pg_resp.text
        except Exception:
            break

    return {"title": title, "paragraphs": all_paragraphs}

def get_all_story_content(story_url):
    """Get all content from a story, including chapters and parts"""
    info = get_story_info(story_url)
    all_content = []
    chapter_num = 1

    # Fetch chapters from main story
    if info["chapters"]:
        for ch_path in info["chapters"]:
            ch_url = BASE_URL + ch_path
            ch_data = get_chapter_content(ch_url)
            all_content.append({
                "number": chapter_num,
                "title": ch_data["title"],
                "paragraphs": ch_data["paragraphs"]
            })
            chapter_num += 1
            time.sleep(0.3)  # Be nice to the server
    else:
        # If no chapters, try to get content from story page itself
        resp = requests.get(story_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        content = decode_protected_content(resp.text)
        if content:
            paras = re.findall(r'<p[^>]*>(.*?)</p>', content, re.DOTALL)
            clean_paras = []
            for p in paras:
                text = re.sub(r'<[^>]+>', '', p).strip()
                if text and len(text) > 5:
                    clean_paras.append(text)
            all_content.append({
                "number": 1,
                "title": info["title"],
                "paragraphs": clean_paras
            })

    # NEW: Fetch content from linked parts (multi-part stories)
    for part_url_path in info.get("parts", []):
        part_url = BASE_URL + part_url_path
        part_info = get_story_info(part_url)

        if part_info["chapters"]:
            for ch_path in part_info["chapters"]:
                ch_url = BASE_URL + ch_path
                ch_data = get_chapter_content(ch_url)
                all_content.append({
                    "number": chapter_num,
                    "title": ch_data["title"] or part_info["title"],
                    "paragraphs": ch_data["paragraphs"]
                })
                chapter_num += 1
                time.sleep(0.3)
        else:
            # Single-page part
            resp = requests.get(part_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            content = decode_protected_content(resp.text)
            if content:
                paras = re.findall(r'<p[^>]*>(.*?)</p>', content, re.DOTALL)
                clean_paras = []
                for p in paras:
                    text = re.sub(r'<[^>]+>', '', p).strip()
                    if text and len(text) > 5:
                        clean_paras.append(text)
                all_content.append({
                    "number": chapter_num,
                    "title": part_info["title"],
                    "paragraphs": clean_paras
                })
                chapter_num += 1

        time.sleep(0.5)

    return info, all_content

# ============ HTML TEMPLATES ============

BASE_STYLE = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: Georgia, 'Times New Roman', serif;
        background: #fff; color: #000;
        line-height: 1.6; font-size: 16px;
    }
    .header {
        background: #1a1a1a; color: #fff;
        padding: 15px; text-align: center;
        border-bottom: 3px solid #c0392b;
    }
    .header h1 { font-size: 24px; margin-bottom: 5px; }
    .header p { font-size: 13px; color: #aaa; }
    .search-box {
        padding: 15px; background: #f5f5f5;
        border-bottom: 1px solid #ddd;
    }
    .search-box form {
        display: flex; gap: 10px;
    }
    .search-box input[type="text"] {
        flex: 1; padding: 12px; font-size: 16px;
        border: 2px solid #ccc; border-radius: 4px;
        font-family: inherit;
    }
    .search-box input:focus {
        outline: none; border-color: #c0392b;
    }
    .search-box button {
        padding: 12px 20px; font-size: 16px;
        background: #c0392b; color: #fff;
        border: none; border-radius: 4px;
        cursor: pointer; font-family: inherit;
    }
    .search-box button:hover { background: #a93226; }
    .nav {
        display: flex; background: #eee;
        border-bottom: 1px solid #ddd;
    }
    .nav a {
        flex: 1; padding: 12px; text-align: center;
        text-decoration: none; color: #333;
        font-weight: bold; font-size: 14px;
        border-right: 1px solid #ddd;
    }
    .nav a:last-child { border-right: none; }
    .nav a:hover { background: #ddd; }
    .section {
        padding: 15px; border-bottom: 2px solid #eee;
    }
    .section h2 {
        font-size: 18px; margin-bottom: 12px;
        color: #c0392b; border-bottom: 1px solid #eee;
        padding-bottom: 8px;
    }
    .story-list { list-style: none; }
    .story-item {
        padding: 12px 0; border-bottom: 1px solid #f0f0f0;
    }
    .story-item:last-child { border-bottom: none; }
    .story-item a {
        text-decoration: none; color: #1a1a1a;
        display: block;
    }
    .story-item a:hover { color: #c0392b; }
    .story-title {
        font-size: 16px; font-weight: bold;
        margin-bottom: 4px;
    }
    .story-meta { font-size: 12px; color: #666; }
    .story-meta span { margin-right: 12px; }
    .status-ongoing { color: #27ae60; }
    .status-completed { color: #2980b9; }
    .footer {
        text-align: center; padding: 20px;
        font-size: 12px; color: #999; background: #f9f9f9;
    }
    .no-results {
        text-align: center; padding: 40px;
        color: #999;
    }
    .pagination {
        text-align: center; padding: 20px;
    }
    .pagination a, .pagination span {
        display: inline-block; padding: 8px 14px;
        margin: 0 4px; text-decoration: none;
        border: 1px solid #ddd; border-radius: 4px;
        color: #333;
    }
    .pagination a:hover { background: #f5f5f5; }
    .pagination .current {
        background: #c0392b; color: #fff;
        border-color: #c0392b;
    }
    .search-info {
        background: #f0f0f0; padding: 10px 15px;
        font-size: 14px; color: #555;
        border-bottom: 1px solid #ddd;
    }
    .warning {
        background: #fff3cd; color: #856404;
        padding: 12px 15px; border-left: 3px solid #ffc107;
        margin: 15px; font-size: 14px;
    }
    @media (max-width: 480px) {
        body { font-size: 15px; }
        .header h1 { font-size: 20px; }
        .story-title { font-size: 15px; }
        .search-box form { flex-direction: column; }
    }
"""

HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="ml">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KK Stories - Kindle Edition</title>
    <style>""" + BASE_STYLE + """
    </style>
</head>
<body>
    <div class="header">
        <h1>KK Stories</h1>
        <p>Kindle Edition - Real-time Scraper</p>
    </div>

    <div class="search-box">
        <form action="/search" method="get">
            <input type="text" name="q" placeholder="Search all stories by title, author, category..." value="" required>
            <button type="submit">Search</button>
        </form>
    </div>

    <div class="nav">
        <a href="/">Home</a>
        <a href="/#latest">Latest</a>
        <a href="/#ongoing">Ongoing</a>
        <a href="/#completed">Completed</a>
    </div>

    <div class="section" id="latest">
        <h2>Latest Stories ({{ stories|length }})</h2>
        <ul class="story-list" id="storyList">
        {% for story in stories %}
            <li class="story-item">
                <a href="/read{{ story.url }}">
                    <div class="story-title">{{ story.title }}</div>
                    <div class="story-meta">
                        {% if story.author and story.author != 'Unknown' %}by {{ story.author }} | {% endif %}
                        {% if story.status %}<span class="status-{{ story.status|lower }}">{{ story.status }}</span> | {% endif %}
                        {% if story.chapters %}ch {{ story.chapters }} | {% endif %}
                        {% if story.views %}views {{ story.views }} | {% endif %}
                        {% if story.comments %}comments {{ story.comments }}{% endif %}
                        {% if story.categories %}| {{ story.categories }}{% endif %}
                    </div>
                </a>
            </li>
        {% endfor %}
        </ul>
    </div>

    {% if ongoing %}
    <div class="section" id="ongoing">
        <h2>Ongoing Stories ({{ ongoing|length }})</h2>
        <ul class="story-list">
        {% for story in ongoing %}
            <li class="story-item">
                <a href="/read{{ story.url }}">
                    <div class="story-title">{{ story.title }}</div>
                    <div class="story-meta">
                        by {{ story.author }}
                        {% if story.chapters %} | ch {{ story.chapters }}{% endif %}
                        {% if story.views %} | views {{ story.views }}{% endif %}
                    </div>
                </a>
            </li>
        {% endfor %}
        </ul>
    </div>
    {% endif %}

    {% if completed %}
    <div class="section" id="completed">
        <h2>Completed Stories ({{ completed|length }})</h2>
        <ul class="story-list">
        {% for story in completed %}
            <li class="story-item">
                <a href="/read{{ story.url }}">
                    <div class="story-title">{{ story.title }}</div>
                    <div class="story-meta">
                        by {{ story.author }}
                        {% if story.chapters %} | ch {{ story.chapters }}{% endif %}
                        {% if story.views %} | views {{ story.views }}{% endif %}
                    </div>
                </a>
            </li>
        {% endfor %}
        </ul>
    </div>
    {% endif %}

    <div class="footer">
        <p>KK Stories Kindle Edition - Real-time Scraper</p>
        <p>Minimal design for e-readers and low-end devices</p>
        <p>{{ stories|length }} stories loaded from kkstories.com</p>
    </div>
</body>
</html>
"""

SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html lang="ml">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search: {{ query }} - KK Stories</title>
    <style>""" + BASE_STYLE + """
    </style>
</head>
<body>
    <div class="header">
        <h1>KK Stories</h1>
        <p>Kindle Edition - Global Search</p>
    </div>

    <div class="search-box">
        <form action="/search" method="get">
            <input type="text" name="q" placeholder="Search all stories..." value="{{ query }}" required>
            <button type="submit">Search</button>
        </form>
    </div>

    <div class="nav">
        <a href="/">Home</a>
        <a href="/search?q={{ query|urlencode }}&page=1">Results</a>
    </div>

    <div class="search-info">
        {% if total > 0 %}
            Found {{ total }} result(s) for "{{ query }}"
            {% if page > 1 %} | Page {{ page }}{% endif %}
        {% else %}
            No results found for "{{ query }}"
        {% endif %}
    </div>

    <div class="section">
        <h2>Search Results</h2>
        {% if stories %}
        <ul class="story-list">
        {% for story in stories %}
            <li class="story-item">
                <a href="/read{{ story.url }}">
                    <div class="story-title">{{ story.title }}</div>
                    <div class="story-meta">
                        {% if story.author and story.author != 'Unknown' %}by {{ story.author }} | {% endif %}
                        {% if story.status %}<span class="status-{{ story.status|lower }}">{{ story.status }}</span> | {% endif %}
                        {% if story.chapters %}ch {{ story.chapters }} | {% endif %}
                        {% if story.views %}views {{ story.views }} | {% endif %}
                        {% if story.comments %}comments {{ story.comments }}{% endif %}
                        {% if story.categories %}| {{ story.categories }}{% endif %}
                    </div>
                </a>
            </li>
        {% endfor %}
        </ul>

        {% if has_more or page > 1 %}
        <div class="pagination">
            {% if page > 1 %}
                <a href="/search?q={{ query|urlencode }}&page={{ page - 1 }}">&larr; Prev</a>
            {% endif %}
            <span class="current">Page {{ page }}</span>
            {% if has_more %}
                <a href="/search?q={{ query|urlencode }}&page={{ page + 1 }}">Next &rarr;</a>
            {% endif %}
        </div>
        {% endif %}

        {% else %}
        <div class="no-results">
            <p>No stories found matching "{{ query }}"</p>
            <p><a href="/">Back to Home</a></p>
        </div>
        {% endif %}
    </div>

    <div class="footer">
        <p>KK Stories Kindle Edition - Global Search</p>
        <p>Searched kkstories.com library in real-time</p>
    </div>
</body>
</html>
"""

READER_TEMPLATE = """
<!DOCTYPE html>
<html lang="ml">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ info.title }} - Full Story</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Georgia, 'Times New Roman', serif;
            background: #fff; color: #000;
            line-height: 1.8; font-size: 18px;
            max-width: 700px; margin: 0 auto; padding: 20px;
        }
        .nav {
            background: #f5f5f5; padding: 10px;
            margin-bottom: 20px; border-radius: 4px;
            font-size: 14px; display: flex; justify-content: space-between;
        }
        .nav a { color: #c0392b; text-decoration: none; }
        .nav a:hover { text-decoration: underline; }
        h1 {
            font-size: 24px; margin-bottom: 8px;
            color: #1a1a1a; border-bottom: 2px solid #c0392b;
            padding-bottom: 10px;
        }
        .author {
            font-size: 14px; color: #666;
            margin-bottom: 20px; font-style: italic;
        }
        .description {
            font-size: 14px; color: #555; background: #f9f9f9;
            padding: 15px; border-left: 3px solid #c0392b;
            margin-bottom: 30px; line-height: 1.6;
        }
        h2 {
            font-size: 20px; margin-top: 40px; margin-bottom: 15px;
            color: #333; border-bottom: 1px solid #eee;
            padding-bottom: 8px;
        }
        .chapter-num {
            color: #c0392b; font-size: 0.8em; margin-right: 8px;
        }
        p { margin-bottom: 1.3em; text-align: justify; }
        hr { border: none; border-top: 1px dashed #ccc; margin: 40px 0; }
        .toc {
            background: #f9f9f9; padding: 15px;
            margin-bottom: 30px; border-radius: 4px;
        }
        .toc h3 { font-size: 16px; margin-bottom: 10px; color: #333; }
        .toc ul { list-style: none; padding-left: 0; }
        .toc li { padding: 4px 0; font-size: 14px; }
        .toc a { color: #333; text-decoration: none; }
        .toc a:hover { color: #c0392b; }
        .footer {
            margin-top: 50px; padding-top: 20px;
            border-top: 1px solid #eee; text-align: center;
            font-size: 12px; color: #999;
        }
        .warning {
            background: #fff3cd; color: #856404;
            padding: 12px; border-left: 3px solid #ffc107;
            margin-bottom: 20px; font-size: 14px;
        }
        @media (max-width: 480px) {
            body { font-size: 16px; padding: 15px; }
            h1 { font-size: 20px; }
            h2 { font-size: 18px; }
        }
    </style>
</head>
<body>
    <div class="nav">
        <a href="/">Back to Library</a>
        <span>{{ chapters|length }} chapters</span>
    </div>

    <h1>{{ info.title }}</h1>
    <div class="author">by {{ info.author }}</div>

    {% if info.parts %}
    <div class="warning">
        This story has {{ info.parts|length }} linked part(s). All content combined.
    </div>
    {% endif %}

    {% if info.description %}
    <div class="description">{{ info.description }}</div>
    {% endif %}

    <div class="toc">
        <h3>Table of Contents</h3>
        <ul>
        {% for ch in chapters %}
            <li><a href="#ch{{ ch.number }}">Chapter {{ ch.number }}: {{ ch.title or "Untitled" }}</a></li>
        {% endfor %}
        </ul>
    </div>

    {% for ch in chapters %}
    <h2 id="ch{{ ch.number }}">
        <span class="chapter-num">Chapter {{ ch.number }}</span>
        {{ ch.title or "" }}
    </h2>
    {% for para in ch.paragraphs %}
    <p>{{ para }}</p>
    {% endfor %}
    {% if not loop.last %}<hr>{% endif %}
    {% endfor %}

    <div class="footer">
        <p>End of {{ info.title }}</p>
        <p>{{ chapters|length }} chapters | KK Stories Kindle Edition</p>
    </div>
</body>
</html>
"""

# ============ ROUTES ============

@app.route("/")
def home():
    """Homepage - scrape and display latest stories"""
    try:
        stories = get_homepage_stories()
        ongoing = [s for s in stories if s.get('status') == 'Ongoing']
        completed = [s for s in stories if s.get('status') == 'Completed']

        return render_template_string(
            HOME_TEMPLATE,
            stories=stories,
            ongoing=ongoing,
            completed=completed
        )
    except Exception as e:
        return f"<h1>Error loading stories</h1><p>{html_module.escape(str(e))}</p><a href='/'>Retry</a>", 500

@app.route("/search")
def search():
    """Global search across all stories"""
    query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    if not query:
        return redirect('/')

    try:
        stories, total, has_more = search_stories(query, page)

        return render_template_string(
            SEARCH_TEMPLATE,
            query=query,
            stories=stories,
            total=total,
            page=page,
            has_more=has_more
        )
    except Exception as e:
        return f"<h1>Search Error</h1><p>{html_module.escape(str(e))}</p><a href='/'>Back</a>", 500

@app.route("/read/story/<path:slug>/")
def read_story(slug):
    """Reader page - scrape all chapters and parts, combine into one"""
    try:
        story_url = f"{BASE_URL}/story/{slug}/"
        info, chapters = get_all_story_content(story_url)

        if not chapters:
            return f"<h1>No content found</h1><p>This story may not have any readable content.</p><a href='/'>Back</a>", 404

        return render_template_string(
            READER_TEMPLATE,
            info=info,
            chapters=chapters
        )
    except Exception as e:
        return f"<h1>Error reading story</h1><p>{html_module.escape(str(e))}</p><a href='/'>Back</a>", 500

@app.route("/read/story/<path:slug>/chapter/<int:ch_num>/")
def read_chapter(slug, ch_num):
    """Redirect chapter URLs to full reader"""
    return redirect(f"/read/story/{slug}/")

# ============ RUN ============

if __name__ == "__main__":
    print("=" * 50)
    print("KK Stories - Kindle Edition Web App")
    print("Global Search + Multi-Part Support")
    print("=" * 50)
    print("Open: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
