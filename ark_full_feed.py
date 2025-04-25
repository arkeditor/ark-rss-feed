#!/usr/bin/env python3
"""
The Ark Newspaper Full RSS Feed Generator (Rebuilt)

This script enriches the RSS feed by pulling in titles and descriptions directly
from the blog feed, applies robust punctuation-cleaning, full-article scraping,
and embeds media content from <figure>/<figcaption> as media:content descriptors.
It also merges paragraphs broken by embedded links or mid-sentence splits, and
outputs a prettified XML with proper declaration and indentation.

Dependencies:
- feedparser
- requests
- beautifulsoup4
- feedgen
- lxml
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import logging
import re
import os
from datetime import datetime, timezone

# --- Setup logging ---
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, f"scraper_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(filename=log_filename, level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# --- Load blog feed for original titles/descriptions ---
blog_feed_url = 'https://www.thearknewspaper.com/blog-feed.xml'
logging.info(f"📡 Fetching blog feed: {blog_feed_url}")
blog_feed = feedparser.parse(blog_feed_url)
# Map each post URL to its original title/description
blog_map = {entry.link: (entry.title, entry.get('description','')) for entry in blog_feed.entries}

# --- Load live RSS feed for enrichment ---
feed_url = 'https://raw.githubusercontent.com/arkeditor/ark-rss-feed/main/output/full_feed.xml'
logging.info(f"📡 Fetching live feed: {feed_url}")
feed = feedparser.parse(feed_url)

# --- Initialize output feed ---
fg = FeedGenerator()
fg.id(feed.feed.get('id', feed_url))
fg.title(feed.feed.get('title', 'Ark Full Feed'))
fg.link(href=feed_url)
fg.description(feed.feed.get('description', ''))
fg.language(feed.feed.get('language', 'en'))
fg.lastBuildDate(datetime.now(timezone.utc))
fg.generator('Ark RSS Feed Generator (Rebuilt)')

# --- Register media namespace for proper xml output ---
fg.namespace('media', 'http://search.yahoo.com/mrss/')

# --- Punctuation-cleaning pipeline ---
def clean_text(text):
    """
    Normalize punctuation:
    - Straighten smart quotes & apostrophes
    - Normalize dashes and ellipses
    - Decode HTML entities for quotes/apostrophes
    - Collapse excess whitespace
    """
    replacements = {
        '\u2018': "'", '\u2019': "'", '\u201C': '"', '\u201D': '"',
        '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00A0': ' '
    }
    for src, tgt in replacements.items(): text = text.replace(src, tgt)
    entities = {
        '&rsquo;': "'", '&lsquo;': "'", '&ldquo;': '"', '&rdquo;': '"',
        '&apos;': "'", '&#39;': "'", '&quot;': '"',
        '&mdash;': '-', '&ndash;': '-'
    }
    for ent, ch in entities.items(): text = text.replace(ent, ch)
    return re.sub(r'\s+', ' ', text).strip()

# --- Sentence-level dedupe within paragraphs ---
def dedupe_sentences(html):
    """Deduplicate repeated sentences within each <p> block."""
    def repl(m):
        content = clean_text(m.group(1))
        sentences = re.split(r'(?<=[\.\?!])\s+', content)
        seen, unique = set(), []
        for s in sentences:
            key = re.sub(r'[^\w\s]', '', s).lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(s.strip())
        return f"<p>{' '.join(unique)}</p>"
    return re.sub(r'<p>(.*?)</p>', repl, html, flags=re.DOTALL)

# --- Merge paragraphs broken mid-sentence or by links ---
def merge_broken_paragraphs(html):
    """Merge <p> tags that were split mid-sentence or around links."""
    html = re.sub(r'</p>\s*<p>([a-z].*?)</p>', r' \1</p>', html, flags=re.DOTALL)
    html = re.sub(r'</p>\s*<p>([\.,;:][^<]+)</p>', r' \1</p>', html, flags=re.DOTALL)
    return html

# --- Process each feed entry ---
for entry in feed.entries:
    post_url = entry.link
    # Preserve original title/description
    if post_url in blog_map:
        title, desc = blog_map[post_url]
    else:
        title, desc = entry.title, entry.get('description','')
    title, desc = clean_text(title), clean_text(desc)
    logging.info(f"Processing {post_url}")

    # Scrape the full article
    try:
        res = requests.get(post_url)
        soup = BeautifulSoup(res.content, 'lxml')

        # Extract main content paragraphs
        paragraphs = []
        for div in soup.find_all('div', class_='tETUs'):
            for outer in div.select('span.BrKEk'):
                for inner in outer.select("span[style*='color:black'][style*='text-decoration:inherit']"):\

                    txt = inner.get_text(strip=True)
                    if len(txt) > 10:
                        paragraphs.append(f"<p>{clean_text(txt)}</p>")
        if not paragraphs:
            for p in soup.find_all('p'):
                txt = p.get_text(strip=True)
                if len(txt) > 20:
                    paragraphs.append(f"<p>{clean_text(txt)}</p>")

        # Deduplicate paragraphs
        seen, unique = set(), []
        for p in paragraphs:
            norm = re.sub(r'\s+', ' ', BeautifulSoup(p, 'html.parser').get_text()).lower()
            if norm not in seen:
                seen.add(norm)
                unique.append(p)
        content_html = "\n".join(unique)

        # Sentence-level dedupe
        content_html = dedupe_sentences(content_html)

        # Merge broken paragraphs
        content_html = merge_broken_paragraphs(content_html)

        # Extract media content
        media_items = []
        for fig in soup.find_all('figure'):
            img = fig.find('img')
            cap = fig.find('figcaption')
            if img and img.get('src'):
                url = img['src']
                caption = clean_text(cap.get_text(strip=True)) if cap else ''
                media_items.append((url, caption))

    except Exception as e:
        logging.error(f"Error scraping {post_url}: {e}")
        content_html, media_items = '', []

    # Build and attach entry
    fe = fg.add_entry()
    fe.id(post_url)
    fe.title(title)
    fe.link(href=post_url)
    fe.description(desc)
    fe.pubDate(entry.get('published', datetime.now(timezone.utc)))
    for m_url, m_caption in media_items:
        fe.media_content({'url': m_url, 'medium': 'image'})
        if m_caption:
            fe.media_description(m_caption)
    if content_html:
        fe.content(content=content_html, type='CDATA')

# --- Output feed (prettified) ---
os.makedirs('output', exist_ok=True)
rss_str = fg.rss_str(pretty=True).decode('utf-8')
output_path = os.path.join('output', 'full_feed.xml')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write(rss_str)
logging.info(f"Rebuilt feed written to {output_path}")
