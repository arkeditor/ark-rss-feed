#!/usr/bin/env python3
"""
The Ark Newspaper Full RSS Feed Generator (Rebuilt)

This script enriches the RSS feed by pulling in titles and descriptions directly
from the blog feed, then applies a revamped punctuation-cleaning and content-scraping pipeline.

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
logging.info(f"üì° Fetching blog feed: {blog_feed_url}")
blog_feed = feedparser.parse(blog_feed_url)
# Map URL to (title, description)
blog_map = {entry.link: (entry.title, entry.get('description','')) for entry in blog_feed.entries}

# --- Load live RSS feed ---
feed_url = 'https://raw.githubusercontent.com/arkeditor/ark-rss-feed/main/output/full_feed.xml'
logging.info(f"üì° Fetching live feed: {feed_url}")
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

# --- Punctuation-cleaning pipeline ---
def clean_text(text):
    """
    Normalize punctuation:
    - Convert smart quotes to ASCII straight quotes
    - Convert en/em dashes and ellipses to simple equivalents
    - Decode common HTML entities for quotes and apostrophes
    - Collapse multiple whitespace into single spaces
    """
    replacements = {
        '\u2018': "'", '\u2019': "'", '\u201C': '"', '\u201D': '"',
        '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00A0': ' '
    }
    for src, tgt in replacements.items():
        text = text.replace(src, tgt)
    entities = {
        '&rsquo;': "'", '&lsquo;': "'", '&ldquo;': '"', '&rdquo;': '"',
        '&apos;': "'", '&#39;': "'", '&quot;': '"',
        '&mdash;': '-', '&ndash;': '-'
    }
    for ent, ch in entities.items():
        text = text.replace(ent, ch)
    return re.sub(r'\s+', ' ', text).strip()

# --- Sentence dedupe for final content ---
def dedupe_sentences(html):
    """Deduplicate repeated sentences within each <p> block."""
    def repl(m):
        content = clean_text(m.group(1))
        sentences = re.split(r'(?<=[\.\?!])\s+', content)
        seen = set(); unique = []
        for s in sentences:
            key = re.sub(r'[^\w\s]', '', s).lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(s.strip())
        return "<p>" + " ".join(unique) + "</p>"
    return re.sub(r'<p>(.*?)</p>', repl, html, flags=re.DOTALL)

# --- Loop and scrape full article content ---
for entry in feed.entries:
    post_url = entry.link
    if post_url in blog_map:
        title, desc = blog_map[post_url]
    else:
        title, desc = entry.title, entry.get('description','')
    title = clean_text(title)
    desc = clean_text(desc)
    logging.info(f"Processing {post_url}")
    try:
        res = requests.get(post_url)
        soup = BeautifulSoup(res.content, 'lxml')
        paragraphs = []
        for div in soup.find_all('div', class_='tETUs'):
            for outer in div.find_all('span', class_='BrKEk'):
                for inner in outer.find_all('span', style=lambda s: s and 'color:black' in s):
                    txt = inner.get_text(strip=True)
                    if len(txt) > 10:
                        paragraphs.append(f"<p>{clean_text(txt)}</p>")
        if not paragraphs:
            for p in soup.find_all('p'):
                text = p.get_text(strip=True)
                if len(text) > 20:
                    paragraphs.append(f"<p>{clean_text(text)}</p>")
        seen = set(); unique = []
        for p in paragraphs:
            norm = re.sub(r'\s+', ' ', BeautifulSoup(p, 'html.parser').get_text()).lower()
            if norm not in seen:
                seen.add(norm)
                unique.append(p)
        html = "\n".join(unique)
        full_html = dedupe_sentences(html)
    except Exception as e:
        logging.error(f"Error scraping {post_url}: {e}")
        full_html = ''
    fe = fg.add_entry()
    fe.id(post_url)
    fe.title(title)
    fe.link(href=post_url)
    fe.description(desc)
    fe.pubDate(entry.get('published', datetime.now(timezone.utc)))
    if full_html:
        fe.content(content=full_html, type='CDATA')

os.makedirs('output', exist_ok=True)
fg.rss_file(os.path.join('output','full_feed.xml'))
logging.info("Rebuilt feed written to output/full_feed.xml")
