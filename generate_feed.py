#!/usr/bin/env python3
"""
Scrapes an Invidious search page and outputs a valid RSS feed XML file.
Usage: python generate_feed.py
Output: feed.rss (in the same directory)

Configure the variables below to change the search term, instance, or output file.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

# ── Configuration ────────────────────────────────────────────────────────────
INVIDIOUS_INSTANCE = "https://inv.nadeko.net"
SEARCH_QUERY       = "sketchbook tour"
DATE_FILTER        = "year"   # options: hour, today, week, month, year
SORT               = "recent" # options: relevance, rating, upload_date, view_count
TYPE               = "video"  # options: video, playlist, channel, all
MAX_RESULTS        = 20       # how many items to include in the feed
OUTPUT_FILE        = "feed.rss"
# ─────────────────────────────────────────────────────────────────────────────


class InvidiousParser(HTMLParser):
    """Parses Invidious search results HTML into a list of video dicts."""

    def __init__(self):
        super().__init__()
        self.videos = []
        self._current = None
        self._capture = None
        self._depth = 0
        self._in_result = False
        self._result_depth = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._depth += 1

        # Each result is a <div class="video-card-row"> or wrapped in a cell
        # Invidious search results use <div class="h-box"> inside <div class="pure-u-*">
        classes = attrs.get("class", "")

        # Detect start of a video result block
        if tag == "div" and "video-card-row" in classes:
            self._in_result = True
            self._result_depth = self._depth
            self._current = {"title": "", "url": "", "author": "", "thumb": "", "views": "", "published": ""}

        if not self._in_result or self._current is None:
            return

        # Thumbnail
        if tag == "img" and "thumbnail" in attrs.get("class", ""):
            src = attrs.get("src", "")
            if src:
                self._current["thumb"] = src if src.startswith("http") else INVIDIOUS_INSTANCE + src

        # Link + title (the <a> wrapping the card)
        if tag == "a" and attrs.get("href", "").startswith("/watch"):
            href = attrs.get("href", "")
            if href and not self._current["url"]:
                self._current["url"] = INVIDIOUS_INSTANCE + href

        # Author link
        if tag == "a" and "/channel/" in attrs.get("href", ""):
            self._capture = "author"

        # p tags carry metadata
        if tag == "p":
            p_class = attrs.get("class", "")
            if "video-data" in p_class:
                self._capture = "meta"

    def handle_endtag(self, tag):
        if self._in_result and tag == "div" and self._depth == self._result_depth:
            if self._current and self._current["url"]:
                self.videos.append(self._current)
            self._current = None
            self._in_result = False
            self._result_depth = None
        self._depth -= 1
        if tag in ("a", "p"):
            self._capture = None

    def handle_data(self, data):
        data = data.strip()
        if not data or not self._current:
            return
        if self._capture == "author" and not self._current["author"]:
            self._current["author"] = data
        elif self._capture == "meta":
            # meta p tags contain things like "24K views" or "1 month ago"
            if "view" in data.lower():
                self._current["views"] = data
            elif "ago" in data.lower() or any(m in data.lower() for m in ["second", "minute", "hour", "day", "week", "month", "year"]):
                self._current["published"] = data
        elif self._capture is None and self._in_result and not self._current["title"] and len(data) > 3:
            # First substantial text inside a result is usually the title
            self._current["title"] = data


def build_search_url(page=1):
    params = urllib.parse.urlencode({
        "q": SEARCH_QUERY,
        "page": page,
        "date": DATE_FILTER,
        "type": TYPE,
        "duration": "none",
        "sort": SORT,
    })
    return f"{INVIDIOUS_INSTANCE}/search?{params}"


def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RSS-generator/1.0)"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def extract_video_id(url):
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    return qs.get("v", [""])[0]


def build_rss(videos):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    search_url = build_search_url()
    q_encoded = urllib.parse.quote_plus(SEARCH_QUERY)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:dc="http://purl.org/dc/elements/1.1/">',
        '  <channel>',
        f'    <title>{SEARCH_QUERY} - Invidious</title>',
        f'    <description>Latest YouTube videos matching "{SEARCH_QUERY}"</description>',
        f'    <pubDate>{now}</pubDate>',
        f'    <link>{search_url}</link>',
    ]

    for v in videos:
        vid_id = extract_video_id(v["url"])
        thumb = v["thumb"] or (f"{INVIDIOUS_INSTANCE}/vi/{vid_id}/mqdefault.jpg" if vid_id else "")
        title = v["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        author = v["author"].replace("&", "&amp;")
        yt_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else v["url"]

        lines += [
            '    <item>',
            f'      <title>{title}</title>',
            f'      <link>{v["url"]}</link>',
            f'      <guid isPermaLink="false">{v["url"]}</guid>',
            f'      <dc:creator>{author}</dc:creator>',
            f'      <pubDate>{now}</pubDate>',
            f'      <description><![CDATA[',
            f'        <a href="{yt_url}"><img src="{thumb}" /></a><br/>',
            f'        <p>{v["views"]}</p>',
            f'        <p>{v["published"]}</p>',
            f'      ]]></description>',
        ]
        if thumb:
            lines.append(f'      <media:content url="{thumb}" medium="image" />')
        lines.append('    </item>')

    lines += ['  </channel>', '</rss>']
    return "\n".join(lines)


def main():
    print(f"Fetching search results for: {SEARCH_QUERY!r}")
    videos = []
    page = 1

    while len(videos) < MAX_RESULTS:
        url = build_search_url(page)
        print(f"  Page {page}: {url}")
        try:
            html = fetch_page(url)
        except Exception as e:
            print(f"  Failed to fetch page {page}: {e}")
            break

        parser = InvidiousParser()
        parser.feed(html)
        new = parser.videos

        if not new:
            print(f"  No results on page {page}, stopping.")
            break

        videos.extend(new)
        print(f"  Found {len(new)} videos (total: {len(videos)})")
        page += 1

    videos = videos[:MAX_RESULTS]

    if not videos:
        print("No videos found. The instance may be down or the HTML structure changed.")
        print("Try a different INVIDIOUS_INSTANCE at the top of the script.")
        return

    rss = build_rss(videos)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(rss)

    print(f"\nDone! Feed written to: {OUTPUT_FILE}")
    print(f"Contains {len(videos)} items.")


if __name__ == "__main__":
    main()
