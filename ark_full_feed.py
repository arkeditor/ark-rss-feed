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

# --- Load blog feed for processing ---
blog_feed_url = 'https://www.thearknewspaper.com/blog-feed.xml'
logging.info(f"Fetching blog feed: {blog_feed_url}")
blog_feed = feedparser.parse(blog_feed_url)
# We'll use the blog feed entries directly, not just as a mapping
feed = blog_feed  # Use the blog feed as our primary source

# --- Initialize output feed ---
fg = FeedGenerator()
fg.load_extension('media')
# Load content extension for the content:encoded elements
fg.load_extension('base')  # Required extension for other core elements

# Use original blog feed as a base
feed_id = feed.feed.get('id', blog_feed_url)
fg.id(feed_id)
fg.title(feed.feed.get('title', 'The Ark Full RSS Feed'))
fg.link(href=blog_feed_url)
fg.description(feed.feed.get('description', 'Full content feed for The Ark Newspaper'))
fg.language(feed.feed.get('language', 'en'))
fg.lastBuildDate(datetime.now(timezone.utc))
fg.generator('Ark RSS Feed Generator (Rebuilt)')

# --- Text cleaning functions ---
def clean_text(text):
    if not text:
        return ""
        
    replacements = {
        '‚Äò': "'", '‚Äô': "'", '‚Äú': '"', '‚Äù': '"',
        '‚Äì': '-', '‚Äî': '-', '‚Ä¶': '...', '¬†': ' '
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
    
    # Fix word spacing issues (like "tosubscribing")
    text = re.sub(r'(\w)to(\w)', r'\1 to \2', text)
    text = re.sub(r'(\w)for(\w)', r'\1 for \2', text)
    text = re.sub(r'consider(\w)', r'consider \1', text)
    text = re.sub(r'(\w)at(\w)', r'\1 at \2', text)
    text = re.sub(r'(\w)and(\w)', r'\1 and \2', text)
    
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

def is_boilerplate(text):
    """Check if text matches known boilerplate patterns."""
    boilerplate_patterns = [
        r'Public Notices/Legals',
        r'The Ark, twice named',
        r'support makes this possible',
        r'In addition to subscribing',
        r'© \d+ The Ark',
        r'Designed by Kevin Hessel',
        r'SUBSCRIBE NOW',
        r'Support The Ark',
        r'hcorn@thearknewspaper\.com',
        r'Read the complete story',
        r'Comment on this article',
        r'independent local journalism',
        r'high-impact community journalism'
    ]
    
    for pattern in boilerplate_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def filter_content(html):
    """Filter content to remove unwanted text and limit to 1100 characters."""
    if not html:
        return ""
        
    # Split into paragraphs to filter individually
    paragraphs = re.findall(r'<p>(.*?)</p>', html, re.DOTALL)
    filtered_paragraphs = []
    
    for p in paragraphs:
        if not is_boilerplate(p):
            filtered_paragraphs.append(f"<p>{p}</p>")
    
    if not filtered_paragraphs:
        return ""
        
    filtered_html = "\n".join(filtered_paragraphs)
    
    # Limit to 1100 characters
    if len(filtered_html) > 1100:
        # First try to find a paragraph break near 1100 chars
        match = re.search(r'</p>\s*(?=<p>)', filtered_html[:1200])
        if match and match.end() > 800:  # Only use if we found a decent amount of content
            filtered_html = filtered_html[:match.end()] + '...'
        else:
            # Otherwise just cut at 1100 and add ellipsis
            filtered_html = filtered_html[:1100] + '...</p>'
    
    return filtered_html

# --- Process each feed entry ---
for entry in feed.entries:
    post_url = entry.link
    # Get title and description directly from entry
    title = clean_text(entry.title)
    desc = clean_text(entry.get('description', ''))
    logging.info(f"Processing {post_url}")
    
    # Create entry first
    fe = fg.add_entry()
    fe.id(post_url)
    fe.title(title)
    fe.link(href=post_url)
    fe.description(desc)
    fe.pubDate(entry.get('published', datetime.now(timezone.utc)))
    
    # Scrape full article and extract media content within the same context
    try:
        res = requests.get(post_url)
        soup = BeautifulSoup(res.content, 'lxml')
        
        # Extract content paragraphs - focus on the specific structure mentioned
        paragraphs = []
        
        # Primary content extraction target: <div class="tETUs"> with nested spans
        for div in soup.find_all('div', class_='tETUs'):
            for outer in div.select('span.BrKEk'):
                for inner in outer.select("span[style*='color:black'][style*='text-decoration:inherit']"):
                    txt = inner.get_text(strip=True)
                    if len(txt) > 10 and not is_boilerplate(txt):  # Only include substantial text
                        paragraphs.append(f"<p>{clean_text(txt)}</p>")
        
        # Fallback if the specific structure isn't found
        if not paragraphs:
            logging.warning(f"Could not find tETUs/BrKEk structure in {post_url}, falling back to p tags")
            for p in soup.find_all('p'):
                txt = p.get_text(strip=True)
                # Skip short texts and headers/section titles
                if len(txt) <= 20:
                    continue
                    
                if not is_boilerplate(txt):
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
        content_html = filter_content(content_html)
        
        # Check if there's meaningful content after all filtering
        # If we have less than 100 characters or no paragraphs, consider it empty
        if not content_html or len(content_html) < 100:
            content_html = ""
            logging.info(f"No meaningful content found for {post_url}")
        else:
            # Only add content if we have actual content
            xml_content = ET.Element('content:encoded')
            xml_content.text = f'<![CDATA[{content_html}]]>'
            fe._FeedEntry__rss_entry().append(xml_content)
            logging.info(f"Added content ({len(content_html)} chars) to {post_url}")
        
        # Extract media from THIS article only
        for fig in soup.find_all('figure'):
            img = fig.find('img')
            # Specifically look for figcaption elements
            cap = fig.find('figcaption')
            
            if img and img.get('src'):
                url = img['src']
                caption = ""
                
                if cap:
                    # Extract caption text
                    caption_text = cap.get_text(strip=True)
                    caption = clean_text(caption_text)
                
                # Create a media:group element
                media_group = ET.Element('media:group')
                
                # Add media:content element
                media_content = ET.Element('media:content')
                media_content.set('url', url)
                media_content.set('medium', 'image')
                media_group.append(media_content)
                
                # Add media:description if we have a caption
                if caption:
                    media_desc = ET.Element('media:description')
                    media_desc.text = caption
                    media_group.append(media_desc)
                
                # Add to feed entry
                fe._FeedEntry__rss_entry().append(media_group)
                logging.info(f"Added media: {url} with caption: {caption[:30]}...")
    
    except Exception as e:
        logging.error(f"Error scraping {post_url}: {e}")

# --- Output feed ---
os.makedirs('output', exist_ok=True)

# Generate the RSS XML string
rss_bytes = fg.rss_str(pretty=True)
rss_str = rss_bytes.decode('utf-8')

# Add proper namespaces to the root element
rss_str = re.sub(r'<rss version="2.0">', 
                 '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:content="http://purl.org/rss/1.0/modules/content/">', 
                 rss_str)

# Remove any empty content:encoded tags
rss_str = re.sub(r'<content:encoded>\s*<!\[CDATA\[\s*\]\]>\s*</content:encoded>', '', rss_str)
rss_str = re.sub(r'<content:encoded>\s*</content:encoded>', '', rss_str)

# Write the final RSS feed to file
with open('output/full_feed.xml', 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write(rss_str)

logging.info("Rebuilt feed written to output/full_feed.xml")
