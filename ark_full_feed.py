#!/usr/bin/env python3
"""
The Ark Newspaper Full RSS Feed Generator (Rebuilt)

This script enriches the RSS feed by:
- Pulling titles and descriptions from the blog feed.
- Cleaning punctuation and merging paragraph fragments.
- Scraping full article content under <div class="tETUs"> for 
  <content:encoded> output.
- Embedding images from <figure>/<figcaption> as <media:content>
  and <media:description>.
- Outputting a prettified RSS with proper namespaces.
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import logging
import re
import os
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

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
blog_map = {entry.link: (entry.title, entry.get('description','')) for entry in blog_feed.entries}

# --- Load live RSS feed for enrichment ---
feed_url = 'https://raw.githubusercontent.com/arkeditor/ark-rss-feed/main/output/full_feed.xml'
logging.info(f"üì° Fetching live feed: {feed_url}")
feed = feedparser.parse(feed_url)

# --- Initialize output feed ---
fg = FeedGenerator()
fg.load_extension('media')
fg.id(feed.feed.get('id', feed_url))
fg.title(feed.feed.get('title', 'Ark Full Feed'))
fg.link(href=feed_url)
fg.description(feed.feed.get('description', ''))
fg.language(feed.feed.get('language', 'en'))
fg.lastBuildDate(datetime.now(timezone.utc))
fg.generator('Ark RSS Feed Generator (Rebuilt)')

# --- Text cleaning functions omitted for brevity ---
def clean_text(text):
    replacements = {
        '‚Äò': "'", '‚Äô': "'", '‚Äú': '"', '‚Äù': '"',
        '‚Äì': '-', '‚Äî': '-', '‚Ä¶': '...', '¬†': ' '
    }
    for src, tgt in replacements.items(): text = text.replace(src, tgt)
    entities = {
        '&rsquo;': "'", '&lsquo;': "'", '&ldquo;': '"', '&rdquo;': '"',
        '&apos;': "'", '&#39;': "'", '&quot;': '"',
        '&mdash;': '-', '&ndash;': '-'
    }
    for ent, ch in entities.items(): text = text.replace(ent, ch)
    return re.sub(r'\s+', ' ', text).strip()

def dedupe_sentences(html):
    def repl(m):
        content = clean_text(m.group(1))
        sentences = re.split(r'(?<=[\.?!])\s+', content)
        seen, unique = set(), []
        for s in sentences:
            key = re.sub(r'[^\w\s]', '', s).lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(s.strip())
        return f"<p>{' '.join(unique)}</p>"
    return re.sub(r'<p>(.*?)</p>', repl, html, flags=re.DOTALL)

def merge_broken_paragraphs(html):
    html = re.sub(r'</p>\s*<p>([a-z].*?)</p>', r' \1</p>', html, flags=re.DOTALL)
    html = re.sub(r'</p>\s*<p>([\.,;:][^<]+)</p>', r' \1</p>', html, flags=re.DOTALL)
    return html

def remove_footer(html):
    pattern = re.compile(r'<p>Read the complete story.*?Designed byKevin Hessel</p>', re.DOTALL)
    return re.sub(pattern, '', html)

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

    # Scrape full article
    try:
        res = requests.get(post_url)
        soup = BeautifulSoup(res.content, 'lxml')
        # Extract content paragraphs
        paragraphs = []
        for div in soup.find_all('div', class_='tETUs'):
            for outer in div.select('span.BrKEk'):
                for inner in outer.select("span[style*='color:black'][style*='text-decoration:inherit']"):
                    txt = inner.get_text(strip=True)
                    if len(txt) > 10:
                        paragraphs.append(f"<p>{clean_text(txt)}</p>")
        if not paragraphs:
            for p in soup.find_all('p'):
                txt = p.get_text(strip=True)
                if len(txt) > 20:
                    paragraphs.append(f"<p>{clean_text(txt)}</p>")
        # Dedupe & clean
        seen, unique = set(), []
        for p in paragraphs:
            norm = re.sub(r'\s+', ' ', BeautifulSoup(p, 'html.parser').get_text()).lower()
            if norm not in seen:
                seen.add(norm)
                unique.append(p)
        content_html = "\n".join(unique)
        content_html = dedupe_sentences(content_html)
        content_html = merge_broken_paragraphs(content_html)
        content_html = remove_footer(content_html)
        # Extract media
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

    # Build entry
    fe = fg.add_entry()
    fe.id(post_url)
    fe.title(title)
    fe.link(href=post_url)
    fe.description(desc)
    fe.pubDate(entry.get('published', datetime.now(timezone.utc)))

    # Add media items
    for m_url, m_caption in media_items:
        media_elem = ET.SubElement(fe.rss_entry, '{http://search.yahoo.com/mrss/}content')
        media_elem.set('url', m_url)
        media_elem.set('medium', 'image')
        if m_caption:
            desc_elem = ET.SubElement(fe.rss_entry, '{http://search.yahoo.com/mrss/}description')
            desc_elem.text = m_caption

    # Add full content
    if content_html:
        content_elem = ET.SubElement(fe.rss_entry, '{http://purl.org/rss/1.0/modules/content/}encoded')
        content_elem.text = f'<![CDATA[{content_html}]]>'

# --- Output feed ---
os.makedirs('output', exist_ok=True)
rss_bytes = fg.rss_str(pretty=True)
rss_str = rss_bytes.decode('utf-8')
# Insert namespaces
rss_str = re.sub(r'<rss version="2.0">', 
                 '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
                 rss_str)
with open('output/full_feed.xml', 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write(rss_str)
logging.info("Rebuilt feed written to output/full_feed.xml")
