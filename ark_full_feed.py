#!/usr/bin/env python3
"""
The Ark Newspaper Full RSS Feed Generator

This script enriches the RSS feed from The Ark Newspaper by fetching the full article
content from each page and creating a new RSS feed that includes complete articles.

Dependencies:
- feedparser
- requests
- beautifulsoup4
- feedgen
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import logging
import re
import os
from datetime import datetime

# --- Set up logging ---
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, f"scraper_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logging.info("🚀 Starting RSS feed enrichment script...")

# --- Parse the existing RSS feed ---
rss_url = "https://www.thearknewspaper.com/blog-feed.xml"
try:
    feed = feedparser.parse(rss_url)
    logging.info(f"✅ Fetched RSS feed from {rss_url}")
except Exception as e:
    logging.error(f"❌ Failed to parse RSS feed: {e}")
    raise

# --- Set up a new enriched feed ---
fg = FeedGenerator()
fg.title('The Ark Newspaper (Full Text)')
fg.link(href='https://www.thearknewspaper.com/news')
fg.description('Full-content RSS feed generated from The Ark Newspaper blog.')

# --- Add required atom namespace and self link ---
fg.id('https://raw.githubusercontent.com/arkeditor/ark-rss-feed/main/output/full_feed.xml')
fg.author({'name': 'The Ark Newspaper', 'email': 'info@thearknewspaper.com'})
fg.language('en')

# Add self-referential link
feed_url = 'https://raw.githubusercontent.com/arkeditor/ark-rss-feed/main/output/full_feed.xml'
fg.link(href=feed_url, rel='self')


def clean_garbled_text(text):
    """
    Clean up common garbled character encodings found in the feed.
    
    Args:
        text (str): Text to clean
        
    Returns:
        str: Cleaned text
    """
    garbled_map = {
        "‚Äôt": "'",
        "‚Äò": "'",
        "‚Äô": "'",
        "‚Äú": '"',
        "‚Äù": '"',
        "‚Äôs": "'s",
        "¬†": " ",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "â€˜": "'",
    }
    skip_content = "HE ARK HAS THE STORY IN THIS WEEK'S ARK • Click the link in our bio for digital-edition access"
    if skip_content in text:
        return text
    for garbled, correct in garbled_map.items():
        text = text.replace(garbled, correct)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text


# --- Loop through each post and scrape full content ---
for entry in feed.entries:
    post_url = entry.link
    post_title = clean_garbled_text(entry.title)
    post_description = clean_garbled_text(entry.get("description", ""))
    pub_date = entry.get("published", "")

    logging.info(f"🔍 Processing: {post_title} - {post_url}")

    try:
        response = requests.get(post_url)
        soup = BeautifulSoup(response.content, 'html.parser')

        paragraphs = []
        for p in soup.find_all("p"):
            style = p.get("style", "")
            if "Georgia" in style and ("18px" in style or "1.5em" in style):
                cleaned_paragraph = clean_garbled_text(str(p))
                paragraphs.append(cleaned_paragraph)

        full_content_html = "\n".join(paragraphs) if paragraphs else ""
        if full_content_html:
            logging.info(f"✅ Extracted and cleaned styled paragraphs for: {post_title}")
        else:
            logging.warning(f"⚠️ No matching styled paragraphs for: {post_title}")

    except Exception as e:
        full_content_html = ""
        logging.error(f"❌ Error scraping {post_url}: {e}")

    fe = fg.add_entry()
    fe.title(post_title)
    fe.link(href=post_url)
    
    # Add a GUID to each entry (using the post URL as the unique identifier)
    fe.guid(post_url, permalink=True)
    
    fe.description(post_description)
    
    # Add publication date
    if pub_date:
        fe.pubDate(pub_date)
    
    # Add content
    fe.content(content=full_content_html, type='CDATA')

# --- Create the .htaccess file to set proper media type ---
htaccess_content = """
# Set correct MIME type for RSS feed
<Files "full_feed.xml">
    ForceType application/rss+xml
</Files>
"""

# --- Output the final RSS feed ---
output_dir = "output"
os.makedirs(output_dir, exist_ok=True)
output_file = os.path.join(output_dir, "full_feed.xml")

try:
    with open(output_file, "wb") as f:
        f.write(fg.rss_str(pretty=True))
    logging.info(f"📦 Full-content RSS feed written to {output_file}")
    
    # Create .htaccess file (note: this won't work on GitHub Pages, but included for completeness)
    htaccess_file = os.path.join(output_dir, ".htaccess")
    with open(htaccess_file, "w") as f:
        f.write(htaccess_content)
    logging.info(f"📦 Created .htaccess file for proper MIME type")
    
except Exception as e:
    logging.error(f"❌ Failed to write feed file: {e}")

logging.info("✅ Script completed.")
