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
logging.info(f"üì° Fetching blog feed: {blog_feed_url}")
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

def filter_content(html):
    """Filter content to remove unwanted text and limit to 1100 characters."""
    # Remove unwanted text patterns
    patterns_to_remove = [
        r'<p>\*\*Read the complete story in our e-edition, or SUBSCRIBE NOW for home delivery and access to the digital replica\.\*\*</p>',
        r'<p>\*Comment on this article on Nextdoor\.\*</p>',
        r'Read the complete story.*?Nextdoor\.',
        r'Read the complete story.*?digital replica\.',
        r'Comment on this article on Nextdoor\.',
        r'Support The Ark\'s commitment to high-impact community journalism\..*?makes this possible\.',
        r'In addition to subscribing to The Ark.*?hcorn@thearknewspaper\.com or \d+-\d+-\d+\.',
        r'© \d+ The Ark, AMMI Publishing Co\. Inc\..*?Designed by Kevin Hessel',
        r'<p>Support The Ark.*?</p>',
        r'<p>In addition to subscribing.*?</p>',
        r'<p>© \d+.*?</p>'
    ]
    
    for pattern in patterns_to_remove:
        html = re.sub(pattern, '', html, flags=re.DOTALL|re.IGNORECASE)
    
    # Limit to 1100 characters (try to break at a paragraph end if possible)
    if len(html) > 1100:
        # First try to find a paragraph break near 1100 chars
        match = re.search(r'</p>\s*(?=<p>)', html[:1200])
        if match and match.end() > 800:  # Only use if we found a decent amount of content
            html = html[:match.end()] + '...'
        else:
            # Otherwise just cut at 1100 and add ellipsis
            html = html[:1100] + '...</p>'
    
    return html

# Store media items for each entry ID for post-processing
entry_media_map = {}

# --- Process each feed entry ---
for entry in feed.entries:
    post_url = entry.link
    # Get title and description directly from entry
    title = clean_text(entry.title)
    desc = clean_text(entry.get('description', ''))
    logging.info(f"Processing {post_url}")

    # Scrape full article
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
                    if len(txt) > 10:  # Only include substantial text
                        paragraphs.append(f"<p>{clean_text(txt)}</p>")
        
        # Fallback if the specific structure isn't found
        if not paragraphs:
            logging.warning(f"Could not find tETUs/BrKEk structure in {post_url}, falling back to p tags")
            for p in soup.find_all('p'):
                txt = p.get_text(strip=True)
                # Skip short texts and headers/section titles
                if len(txt) <= 20:
                    continue
                    
                # Explicitly filter out known section headers and boilerplate
                skip_patterns = [
                    r'^Public Notices/Legals
        
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
        # If we have less than 100 characters or just 1 paragraph of boilerplate, consider it empty
        if len(content_html) < 100 or len(paragraphs) <= 1:
            content_html = ""
            logging.info(f"No meaningful content found for {post_url}")

        
        # Extract media - specifically looking for figures with figcaptions
        media_items = []
        for fig in soup.find_all('figure'):
            img = fig.find('img')
            # Specifically look for figcaption elements with any class
            cap = fig.find('figcaption')
            
            if img and img.get('src'):
                url = img['src']
                caption = ""
                
                if cap:
                    # Log the figcaption and its classes for debugging
                    caption_classes = cap.get('class', [])
                    caption_text = cap.get_text(strip=True)
                    logging.info(f"Found figcaption with classes: {caption_classes}, text: {caption_text[:30]}...")
                    caption = clean_text(caption_text)
                
                media_items.append((url, caption))
                logging.info(f"Added media: {url} with caption: {caption[:30]}...")
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

    # Store entry ID and media items for post-processing
    entry_id = post_url  # Use URL as unique identifier
    if media_items:
        entry_media_map[entry_id] = media_items
        
    # Only store content if we have meaningful content
    if content_html:
        fe.content(content_html)
    # Even if no content, we keep the description
    fe.description(desc)

# --- Output feed ---
os.makedirs('output', exist_ok=True)

# Generate the RSS XML string
rss_bytes = fg.rss_str(pretty=True)
rss_str = rss_bytes.decode('utf-8')

# Add proper namespaces to the root element
rss_str = re.sub(r'<rss version="2.0">', 
                 '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:content="http://purl.org/rss/1.0/modules/content/">', 
                 rss_str)

# Replace content tags with content:encoded tags containing CDATA
# First, find all content tags
content_pattern = re.compile(r'<content>(.*?)</content>', re.DOTALL)
for match in content_pattern.finditer(rss_str):
    content = match.group(1)
    
    # Skip empty content
    if not content.strip():
        # Replace with empty content:encoded tag
        old_tag = match.group(0)
        new_tag = '<content:encoded></content:encoded>'
        rss_str = rss_str.replace(old_tag, new_tag)
        continue
    
    # Handle unescaping of HTML entities properly
    try:
        # First convert to an actual DOM to handle entities
        soup = BeautifulSoup(f"<div>{content}</div>", 'lxml')
        # Extract the raw HTML (with entities converted to actual tags)
        content = ''.join(str(c) for c in soup.div.contents)
    except Exception as e:
        logging.error(f"Error unescaping HTML: {e}")
        # Fallback to basic replacement if parsing fails
        content = content.replace('&lt;', '<').replace('&gt;', '>')
    
    # Replace the content tag with content:encoded containing raw HTML in CDATA
    old_tag = match.group(0)
    new_tag = f'<content:encoded><![CDATA[{content}]]></content:encoded>'
    rss_str = rss_str.replace(old_tag, new_tag)

# Add media items with proper media:group and media:description tags
# This uses the entry URLs as identifiers to match with our stored media items
item_pattern = re.compile(r'<item>\s*<title>(.*?)</title>.*?<link>(.*?)</link>', re.DOTALL)
for match in item_pattern.finditer(rss_str):
    title = match.group(1)
    link = match.group(2)
    
    # Check if we have media items for this entry
    if link in entry_media_map and entry_media_map[link]:
        # Find the position to insert media group
        item_end_pos = rss_str.find('</item>', match.start())
        if item_end_pos > 0:
            # Create media group XML
            media_group = []
            media_group.append('  <media:group>')
            
            for img_url, caption in entry_media_map[link]:
                media_group.append(f'    <media:content url="{img_url}" medium="image"/>')
                if caption:
                    media_group.append(f'    <media:description>{caption}</media:description>')
            
            media_group.append('  </media:group>')
            media_xml = '\n'.join(media_group)
            
            # Insert media group before item closing tag
            rss_str = rss_str[:item_end_pos] + '\n' + media_xml + '\n' + rss_str[item_end_pos:]

# Write the final RSS feed to file
with open('output/full_feed.xml', 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write(rss_str)

logging.info("Rebuilt feed written to output/full_feed.xml")
,
                    r'^The Ark, twice named',
                    r'support makes this possible',
                    r'In addition to subscribing',
                    r'© \d+ The Ark',
                    r'Designed by Kevin Hessel',
                    r'^Email campaign was',
                    r'^SUBSCRIBE NOW',
                ]
                
                should_skip = False
                for pattern in skip_patterns:
                    if re.search(pattern, txt, re.IGNORECASE):
                        should_skip = True
                        break
                        
                if not should_skip:
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
        # If we have less than 100 characters or just 1 paragraph of boilerplate, consider it empty
        if len(content_html) < 100 or len(paragraphs) <= 1:
            content_html = ""
            logging.info(f"No meaningful content found for {post_url}")

        
        # Extract media - specifically looking for figures with figcaptions
        media_items = []
        for fig in soup.find_all('figure'):
            img = fig.find('img')
            # Specifically look for figcaption elements with any class
            cap = fig.find('figcaption')
            
            if img and img.get('src'):
                url = img['src']
                caption = ""
                
                if cap:
                    # Log the figcaption and its classes for debugging
                    caption_classes = cap.get('class', [])
                    caption_text = cap.get_text(strip=True)
                    logging.info(f"Found figcaption with classes: {caption_classes}, text: {caption_text[:30]}...")
                    caption = clean_text(caption_text)
                
                media_items.append((url, caption))
                logging.info(f"Added media: {url} with caption: {caption[:30]}...")
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

    # Store entry ID and media items for post-processing
    entry_id = post_url  # Use URL as unique identifier
    if media_items:
        entry_media_map[entry_id] = media_items
        
    # Only store content if we have meaningful content
    if content_html:
        fe.content(content_html)
    # Even if no content, we keep the description
    fe.description(desc)

# --- Output feed ---
os.makedirs('output', exist_ok=True)

# Generate the RSS XML string
rss_bytes = fg.rss_str(pretty=True)
rss_str = rss_bytes.decode('utf-8')

# Add proper namespaces to the root element
rss_str = re.sub(r'<rss version="2.0">', 
                 '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:content="http://purl.org/rss/1.0/modules/content/">', 
                 rss_str)

# Replace content tags with content:encoded tags containing CDATA
# First, find all content tags
content_pattern = re.compile(r'<content>(.*?)</content>', re.DOTALL)
for match in content_pattern.finditer(rss_str):
    content = match.group(1)
    
    # Skip empty content
    if not content.strip():
        # Replace with empty content:encoded tag
        old_tag = match.group(0)
        new_tag = '<content:encoded></content:encoded>'
        rss_str = rss_str.replace(old_tag, new_tag)
        continue
    
    # Handle unescaping of HTML entities properly
    try:
        # First convert to an actual DOM to handle entities
        soup = BeautifulSoup(f"<div>{content}</div>", 'lxml')
        # Extract the raw HTML (with entities converted to actual tags)
        content = ''.join(str(c) for c in soup.div.contents)
    except Exception as e:
        logging.error(f"Error unescaping HTML: {e}")
        # Fallback to basic replacement if parsing fails
        content = content.replace('&lt;', '<').replace('&gt;', '>')
    
    # Replace the content tag with content:encoded containing raw HTML in CDATA
    old_tag = match.group(0)
    new_tag = f'<content:encoded><![CDATA[{content}]]></content:encoded>'
    rss_str = rss_str.replace(old_tag, new_tag)

# Add media items with proper media:group and media:description tags
# This uses the entry URLs as identifiers to match with our stored media items
item_pattern = re.compile(r'<item>\s*<title>(.*?)</title>.*?<link>(.*?)</link>', re.DOTALL)
for match in item_pattern.finditer(rss_str):
    title = match.group(1)
    link = match.group(2)
    
    # Check if we have media items for this entry
    if link in entry_media_map and entry_media_map[link]:
        # Find the position to insert media group
        item_end_pos = rss_str.find('</item>', match.start())
        if item_end_pos > 0:
            # Create media group XML
            media_group = []
            media_group.append('  <media:group>')
            
            for img_url, caption in entry_media_map[link]:
                media_group.append(f'    <media:content url="{img_url}" medium="image"/>')
                if caption:
                    media_group.append(f'    <media:description>{caption}</media:description>')
            
            media_group.append('  </media:group>')
            media_xml = '\n'.join(media_group)
            
            # Insert media group before item closing tag
            rss_str = rss_str[:item_end_pos] + '\n' + media_xml + '\n' + rss_str[item_end_pos:]

# Write the final RSS feed to file
with open('output/full_feed.xml', 'w', encoding='utf-8') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write(rss_str)

logging.info("Rebuilt feed written to output/full_feed.xml")
