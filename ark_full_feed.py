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
import html

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
# We'll use the blog feed entries directly as our primary source
feed = blog_feed

# --- Initialize output feed ---
fg = FeedGenerator()
fg.load_extension('media')
fg.load_extension('base')

# Use original blog feed as a base
feed_id = feed.feed.get('id', blog_feed_url)
fg.id(feed_id)
fg.title(feed.feed.get('title', 'The Ark'))
fg.link(href=blog_feed_url)
fg.description(feed.feed.get('description', 'The Ark is the weekly newspaper of Tiburon, Belvedere and Strawberry'))
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
    
    # Fix specific word spacing issues while avoiding breaking normal words
    text = re.sub(r'(\w)to(subscribing|making)\b', r'\1 to \2', text)
    text = re.sub(r'(\w)for(weekly)\b', r'\1 for \2', text)
    text = re.sub(r'\bconsider(making)\b', r'consider \1', text)
    text = re.sub(r'\b(hcorn)at(thearknewspaper)\b', r'\1 at \2', text)
    
    return re.sub(r'\s+', ' ', text).strip()

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

# For storing the feed entries before we create the final XML
all_entries = []

# --- Process each feed entry directly ---
for entry in feed.entries:
    post_url = entry.link
    # Use original title and description directly from the feed
    title = entry.title
    desc = entry.get('description', '')
    guid = entry.get('id', post_url)
    published = entry.get('published', datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000'))
    logging.info(f"Processing {post_url}")
    
    # Create dictionary for this entry
    current_entry = {
        'title': title,
        'link': post_url,
        'description': desc,
        'guid': guid,
        'pubDate': published,
        'content_encoded': None,
        'media_groups': []
    }
    
    # Now scrape the article page
    try:
        response = requests.get(post_url)
        soup = BeautifulSoup(response.content, 'lxml')
        
        # First extract article content
        paragraphs = []
        
        # Primary content extraction target: <div class="tETUs"> with nested spans
        for div in soup.find_all('div', class_='tETUs'):
            for outer in div.select('span.BrKEk'):
                for inner in outer.select("span[style*='color:black'][style*='text-decoration:inherit']"):
                    txt = inner.get_text(strip=True)
                    if len(txt) > 10 and not is_boilerplate(txt):
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
        
        # Add content:encoded if we have valid content
        if content_html and len(content_html) > 100:
            # Fix HTML formatting
            # Step 1: First convert escaped HTML to actual HTML
            content_html = content_html.replace('&lt;p&gt;', '<p>')
            content_html = content_html.replace('&lt;/p&gt;', '</p>')
            
            # Step 2: Apply html.unescape for any other entities
            content_html = html.unescape(content_html)
            
            # Step 3: Check for specific patterns to clean up
            # Strip <p> at the beginning of content if needed
            if content_html.startswith('<p>'):
                content_html = content_html[3:]
                
            # Strip </p> at the end of content if needed
            if content_html.endswith('</p>'):
                content_html = content_html[:-4]
                
            # Store the properly formatted content
            current_entry['content_encoded'] = content_html
            logging.info(f"Added content ({len(content_html)} chars) to {post_url}")
        
        # Now extract media from THIS ARTICLE ONLY
        for fig in soup.find_all('figure'):
            img = fig.find('img')
            cap = fig.find('figcaption')
            
            if img and img.get('src'):
                img_url = img['src']
                img_caption = ""
                
                if cap:
                    img_caption = clean_text(cap.get_text(strip=True))
                
                # Create a media entry
                media_item = {
                    'url': img_url,
                    'caption': img_caption
                }
                
                # Add to this entry's media groups
                current_entry['media_groups'].append(media_item)
                logging.info(f"Added media to {post_url}: {img_url}")
        
    except Exception as e:
        logging.error(f"Error processing {post_url}: {e}")
    
    # Add the entry to our collection
    all_entries.append(current_entry)

# Create the XML output directly
output_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
output_xml += '<rss xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">\n'
output_xml += '  <channel>\n'
output_xml += f'    <title>{feed.feed.get("title", "The Ark")}</title>\n'
output_xml += f'    <link>{blog_feed_url}</link>\n'
output_xml += f'    <description>{feed.feed.get("description", "The Ark is the weekly newspaper of Tiburon, Belvedere and Strawberry")}</description>\n'
output_xml += '    <docs>http://www.rssboard.org/rss-specification</docs>\n'
output_xml += '    <generator>Ark RSS Feed Generator (Rebuilt)</generator>\n'
output_xml += '    <language>en</language>\n'
output_xml += f'    <lastBuildDate>{datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>\n'

# Add each entry
for entry in all_entries:
    # Ensure XML-safe text by escaping special characters
    safe_title = entry["title"].replace("&", "&amp;")
    safe_description = entry["description"].replace("&", "&amp;")
    
    output_xml += '    <item>\n'
    output_xml += f'      <title>{safe_title}</title>\n'
    output_xml += f'      <link>{entry["link"]}</link>\n'
    output_xml += f'      <description>{safe_description}</description>\n'
    
    # Add content:encoded if we have it
    if entry['content_encoded']:
        # Ensure content is properly wrapped in paragraph tags 
        content = entry["content_encoded"]
        if not content.startswith('<p>'):
            content = '<p>' + content
        if not content.endswith('</p>'):
            content = content + '</p>'
            
        output_xml += f'      <content:encoded><![CDATA[{content}]]></content:encoded>\n'
    
    output_xml += f'      <guid isPermaLink="false">{entry["guid"]}</guid>\n'
    output_xml += f'      <pubDate>{entry["pubDate"]}</pubDate>\n'
    
    # Add each media item without grouping
    for media in entry['media_groups']:
        # Use media:content directly without media:group
        output_xml += f'      <media:content url="{media["url"]}" medium="image"/>\n'
        if media['caption']:
            # Escape & in captions
            safe_caption = media['caption'].replace("&", "&amp;")
            output_xml += f'      <media:description>{safe_caption}</media:description>\n'
    
    output_xml += '    </item>\n'

# Close the channel and rss tags
output_xml += '  </channel>\n'
output_xml += '</rss>\n'

# Write the final RSS feed to file
os.makedirs('output', exist_ok=True)
with open('output/full_feed.xml', 'w', encoding='utf-8') as f:
    f.write(output_xml)

logging.info("Rebuilt feed written to output/full_feed.xml")
