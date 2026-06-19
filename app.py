"""
KK Stories - Kindle Edition Web App
Real-time scraper for kkstories.com
Compatible with Vercel, Render, and other serverless platforms
"""

from flask import Flask, render_template_string, request, redirect
import requests
import re
import base64
import html
import os

app = Flask(__name__)

BASE_URL = "https://kkstories.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ============ SCRAPER FUNCTIONS ============

def decode_protected_content(page_html):
    """Decode Base64-protected story content"""
    match = re.search(r"""data-protected-payload=["']([^"']+)["']""", page_html)
    if match:
        try:
            return base64.b64decode(match.group(1)).decode('utf-8')
        except:
            return None
    return None

def get_homepage_stories():
    """Scrape homepage for all stories"""
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=15)
    page_html = resp.text

    stories = []
    story_cards = re.findall(r'<article class="story-card[^"]*"[^>]*>(.*?)</article>', page_html, re.DOTALL)

    for card in story_cards:
        title_match = re.search(
            r"""<h3>.*?<a[^>]+href=["'](/story/[^/]+/)["'][^>]*>(.*?)</a>.*?</h3>""",
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
            r"""<a[^>]+href=["']/library/\?category=[^"']+["'][^>]*>([^<]+)</a>""",
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

def get_story_info(story_url):
    """Get story metadata and chapter list"""
    resp = requests.get(story_url, headers=HEADERS, timeout=15)
    page_html = resp.text

    title_match = re.search(r'<title>([^<]+)</title>', page_html)
    title = title_match.group(1).split('·')[0].strip() if title_match else "Unknown"

    author_match = re.search(
        r"""<a[^>]+href=["']/author/([^/]+)/["'][^>]*>([^<]+)</a>""",
        page_html
    )
    author = author_match.group(2) if author_match else "Unknown"

    chapter_links = re.findall(
        r"""href=["'](/story/[^/]+/chapter/\d+/)["']""",
        page_html
    )
    unique_chapters = sorted(
        set(chapter_links),
        key=lambda x: int(re.search(r'chapter/(\d+)', x).group(1))
    )

    desc_match = re.search(
        r"""<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']""",
        page_html
    )
    description = desc_match.group(1) if desc_match else ""

    return {
        "title": title,
        "author": author,
        "description": description,
        "chapters": unique_chapters
    }

def get_chapter_content(chapter_url):
    """Fetch and decode a single chapter"""
    resp = requests.get(chapter_url, headers=HEADERS, timeout=15)
    page_html = resp.text

    title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', page_html)
    title = title_match.group(1).strip() if title_match else ""

    content = decode_protected_content(page_html)

    if content:
        paras = re.findall(r'<p[^>]*>(.*?)</p>', content, re.DOTALL)
        clean_paras = []
        for p in paras:
            text = re.sub(r'<[^>]+>', '', p).strip()
            if text and len(text) > 5:
                clean_paras.append(text)
        return {"title": title, "paragraphs": clean_paras}

    return {"title": title, "paragraphs": []}

# ============ HTML TEMPLATES ============

HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="ml">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KK Stories - Kindle Edition</title>
    <style>
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
        .search-box input {
            width: 100%; padding: 12px; font-size: 16px;
            border: 2px solid #ccc; border-radius: 4px;
            font-family: inherit;
        }
        .search-box input:focus {
            outline: none; border-color: #c0392b;
        }
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
            color: #999; display: none;
        }
        .loading {
            text-align: center; padding: 60px;
            color: #666; font-style: italic;
        }
        @media (max-width: 480px) {
            body { font-size: 15px; }
            .header h1 { font-size: 20px; }
            .story-title { font-size: 15px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>KK Stories</h1>
        <p>Kindle Edition - Real-time Scraper</p>
    </div>

    <div class="search-box">
        <input type="text" id="searchInput" placeholder="Search stories by title or author..." onkeyup="searchStories()">
    </div>

    <div class="nav">
        <a href="#latest">Latest</a>
        <a href="#ongoing">Ongoing</a>
        <a href="#completed">Completed</a>
    </div>

    <div class="section" id="latest">
        <h2>Latest Stories ({{ stories|length }})</h2>
        <ul class="story-list" id="storyList">
        {% for story in stories %}
            <li class="story-item" data-title="{{ story.title|lower }}" data-author="{{ story.author|lower }}">
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
        <div class="no-results" id="noResults">No stories found matching your search.</div>
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
        <p>Kindle Edition - Real-time Scraper</p>
        <p>Minimal design for e-readers and low-end devices</p>
        <p>{{ stories|length }} stories loaded from </p>
    </div>

    <script>
        function searchStories() {
            const input = document.getElementById('searchInput').value.toLowerCase();
            const items = document.querySelectorAll('.story-item');
            const noResults = document.getElementById('noResults');
            let visible = 0;

            items.forEach(item => {
                const title = item.getAttribute('data-title') || '';
                const author = item.getAttribute('data-author') || '';
                if (title.includes(input) || author.includes(input)) {
                    item.style.display = 'block';
                    visible++;
                } else {
                    item.style.display = 'none';
                }
            });

            noResults.style.display = visible === 0 ? 'block' : 'none';
        }
    </script>
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
        .loading {
            text-align: center; padding: 40px;
            color: #666; font-style: italic;
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
    """Homepage - scrape and display all stories"""
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
        return f"<h1>Error loading stories</h1><p>{html.escape(str(e))}</p><a href='/'>Retry</a>", 500

@app.route("/read/story/<path:slug>/")
def read_story(slug):
    """Reader page - scrape all chapters and combine"""
    try:
        story_url = f"{BASE_URL}/story/{slug}/"
        info = get_story_info(story_url)

        if not info["chapters"]:
            return f"<h1>No chapters found</h1><p>This story may not have any chapters.</p><a href='/'>Back</a>", 404

        chapters = []
        for ch_path in info["chapters"]:
            ch_data = get_chapter_content(BASE_URL + ch_path)
            chapters.append({
                "number": len(chapters) + 1,
                "title": ch_data["title"],
                "paragraphs": ch_data["paragraphs"]
            })

        return render_template_string(
            READER_TEMPLATE,
            info=info,
            chapters=chapters
        )
    except Exception as e:
        return f"<h1>Error reading story</h1><p>{html.escape(str(e))}</p><a href='/'>Back</a>", 500

@app.route("/read/story/<path:slug>/chapter/<int:ch_num>/")
def read_chapter(slug, ch_num):
    """Redirect chapter URLs to full reader"""
    return redirect(f"/read/story/{slug}/")

# ============ WSGI ENTRY POINT ============
# For Vercel serverless compatibility

# Vercel expects 'app' to be the WSGI callable
# This is already defined above

# For local development
if __name__ == "__main__":
    print("=" * 50)
    print("KK Stories - Kindle Edition Web App")
    print("=" * 50)
    print("Open: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
