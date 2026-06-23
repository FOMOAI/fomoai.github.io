#!/usr/bin/env python3
"""
AI News Fetcher – Produces articles.json for the AI News Hub HTML.
Dependencies: pip install feedparser requests
Usage: python news_fetcher.py
"""

import json
import sys
import traceback
from datetime import datetime, timezone

import feedparser
import requests

# ── Configuration ──────────────────────────────────────────
SOURCES = [
    {"name": "OpenAI",         "type": "rss",   "url": "https://openai.com/news/rss.xml",                                                "cat": "official"},
    {"name": "Google AI Blog", "type": "rss",   "url": "https://blog.google/technology/ai/rss/",                                         "cat": "official"},
    {"name": "Hugging Face",   "type": "json",  "url": "https://huggingface.co/api/blog?limit=15",                                       "cat": "community"},
    {"name": "arXiv cs.AI",    "type": "arxiv", "url": "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=15", "cat": "research"},
    {"name": "MIT Tech Review","type": "rss",   "url": "https://www.technologyreview.com/feed/",                                         "cat": "media"},
    {"name": "The Verge AI",   "type": "rss",   "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",              "cat": "media"},
]

OUTPUT_FILE = "articles.json"
REQUEST_TIMEOUT = 15  # seconds

# ── Helpers ────────────────────────────────────────────────
def safe_get(d, *keys, default=""):
    """Safely traverse nested dicts."""
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key, {})
        else:
            return default
    return d if d else default

def clean_summary(text, max_len=500):
    """Strip HTML tags and truncate."""
    import re
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_len]

def extract_references(text, link):
    """Extract up to 4 unique URLs from text (ignoring social media)."""
    import re
    urls = re.findall(r'https?://[^\s<>"\']+', text)
    if link:
        urls.append(link)
    seen = set()
    refs = []
    for u in urls:
        u = u.rstrip('.,;:')
        if u in seen:
            continue
        if any(domain in u for domain in ['twitter.com', 'x.com', 'youtube.com', 'facebook.com']):
            continue
        seen.add(u)
        refs.append(u)
        if len(refs) >= 4:
            break
    return refs

def parse_date(date_str):
    """Try to parse date, fallback to now."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        from dateutil import parser
        dt = parser.parse(date_str)
    except ImportError:
        # If dateutil not installed, fallback to simple parse
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S%z')
        except:
            return datetime.now(timezone.utc).isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

# ── Fetchers ───────────────────────────────────────────────
def fetch_rss(source):
    feed = feedparser.parse(source["url"])
    if feed.bozo and not feed.entries:
        raise Exception(f"Feed error: {feed.bozo_exception}")
    articles = []
    for entry in feed.entries:
        title = entry.get("title", "Untitled")
        link = entry.get("link", "")
        # date: try published, updated, or fallback
        date = entry.get("published", entry.get("updated", ""))
        published = parse_date(date) if date else datetime.now(timezone.utc).isoformat()
        summary = clean_summary(entry.get("description", entry.get("summary", "")))
        author = entry.get("author", "")
        if isinstance(author, dict):
            author = author.get("name", "")
        refs = extract_references(entry.get("description", "") + entry.get("summary", ""), link)
        articles.append({
            "title": title,
            "link": link,
            "published": published,
            "summary": summary,
            "author": author,
            "source": source["name"],
            "category": source["cat"],
            "references": refs
        })
    return articles

def fetch_json(source):
    resp = requests.get(source["url"], timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    articles = []
    for post in data:
        title = post.get("title", "Untitled")
        link = post.get("url") or f"https://huggingface.co/blog/{post.get('slug', post.get('id', ''))}"
        date = post.get("publishedAt", post.get("date", ""))
        published = parse_date(date) if date else datetime.now(timezone.utc).isoformat()
        content = post.get("content", post.get("subtitle", ""))
        summary = clean_summary(content)
        author = safe_get(post, "author", "name", default="")
        refs = extract_references(content, link)
        articles.append({
            "title": title,
            "link": link,
            "published": published,
            "summary": summary,
            "author": author,
            "source": source["name"],
            "category": source["cat"],
            "references": refs
        })
    return articles

def fetch_arxiv(source):
    resp = requests.get(source["url"], timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    articles = []
    for entry in feed.entries:
        title = entry.get("title", "Untitled").replace("\n", " ").strip()
        link = entry.get("id", "")
        published = parse_date(entry.get("published", "")) if entry.get("published") else datetime.now(timezone.utc).isoformat()
        summary = clean_summary(entry.get("summary", ""))
        author = ", ".join(a.get("name", "") for a in entry.get("authors", []))
        refs = extract_references(entry.get("summary", ""), link)
        articles.append({
            "title": title,
            "link": link,
            "published": published,
            "summary": summary,
            "author": author,
            "source": source["name"],
            "category": source["cat"],
            "references": refs
        })
    return articles

FETCHERS = {
    "rss": fetch_rss,
    "json": fetch_json,
    "arxiv": fetch_arxiv,
}

# ── Main ───────────────────────────────────────────────────
def main():
    all_articles = []
    for src in SOURCES:
        try:
            fetcher = FETCHERS[src["type"]]
            articles = fetcher(src)
            print(f"✅ {src['name']}: {len(articles)} articles")
            all_articles.extend(articles)
        except Exception as e:
            print(f"❌ {src['name']} failed: {e}", file=sys.stderr)
            traceback.print_exc()

    # Deduplicate by link
    seen = set()
    unique = []
    for art in all_articles:
        clean = art["link"].split("?")[0].split("#")[0]  # remove query/fragment
        if clean not in seen:
            seen.add(clean)
            unique.append(art)
        else:
            print(f"⚠️ Duplicate removed: {art['link']}")

    # Sort newest first
    unique.sort(key=lambda x: x["published"], reverse=True)

    # Save JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)

    print(f"\n📦 {len(unique)} articles written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()