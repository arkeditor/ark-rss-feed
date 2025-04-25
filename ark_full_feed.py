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
from datetime import datetime, timezone

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
fg.load_extension('podcast')
fg.podcast.itunes_category('News')

# --- Feed metadata ---
fg.title('The Ark Newspaper (Full Text)')
fg.link(href='https://www.thearknewspaper.com/news')
fg.description('Full-content RSS feed generated from The Ark Newspaper blog.')

# --- Add required atom namespace and self link ---
feed_url = 'https://raw.githubusercontent.com/arkeditor/ark-rss-feed/main/output/full_feed.xml'
fg.id(feed_url)
fg.author({'name': 'The Ark Newspaper', 'email': 'info@thearknewspaper.com'})
fg.language('en')

# Explicitly add atom:link with rel="self" (ensuring this works)
fg.link(href=feed_url, rel='self')

# Add additional required elements with timezone-aware datetime
fg.lastBuildDate(datetime.now(timezone.utc))
fg.generator('Ark RSS Feed Generator')


def fix_garbled_encodings(text):
    """
    Fix only known garbled character encodings without removing legitimate punctuation.
    
    Args:
        text (str): Text to clean
        
    Returns:
        str: Cleaned text with legitimate punctuation preserved
    """
    # Only fix specific known garbled encodings
    garbled_map = {
        "‚Äôt": "'t",  # won't
        "‚Äò": "'",    # apostrophe
        "‚Äô": "'",    # apostrophe
        "‚Äú": '"',    # opening double quote
        "‚Äù": '"',    # closing double quote
        "‚Äôs": "'s",  # possessive
        "¬†": " ",     # space
        "â€™": "'",    # apostrophe
        "â€œ": '"',    # opening double quote
        "â€": '"',     # closing double quote
        "â€˜": "'",    # apostrophe
    }
    
    skip_content = "HE ARK HAS THE STORY IN THIS WEEK'S ARK • Click the link in our bio for digital-edition access"
    if skip_content in text:
        return text
        
    for garbled, correct in garbled_map.items():
        text = text.replace(garbled, correct)
    
    # Don't strip regular apostrophes and quotes - only remove truly non-ASCII characters
    # This regex keeps ASCII, apostrophes, and quotes
    text = re.sub(r'[^\x00-\x7F\'\"\`]', '', text)
    
    return text


def clean_garbled_html(html_text):
    """
    More aggressive cleaning for HTML content, used for the article body.
    
    Args:
        html_text (str): HTML text to clean
        
    Returns:
        str: Cleaned HTML
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
    
    for garbled, correct in garbled_map.items():
        html_text = html_text.replace(garbled, correct)
    
    # More aggressive cleaning for HTML content is fine
    html_text = re.sub(r'[^\x00-\x7F]+', '', html_text)
    
    return html_text


def extract_text_from_element(element):
    """
    Extract text from an element, handling the nested span structure.
    
    Args:
        element: BeautifulSoup element
        
    Returns:
        str: Extracted text
    """
    text = ""
    if element.name == 'span':
        # Get text directly from span
        text = element.get_text(strip=True)
    else:
        # For other elements, collect text from all child spans
        spans = element.find_all('span', recursive=True)
        if spans:
            for span in spans:
                span_text = span.get_text(strip=True)
                if span_text:
                    text += span_text + " "
        else:
            # If no spans, get all text
            text = element.get_text(strip=True)
    
    return text.strip()


# --- Loop through each post and scrape full content ---
for entry in feed.entries:
    post_url = entry.link
    
    # Use gentler cleaning for titles and descriptions
    post_title = fix_garbled_encodings(entry.title)
    post_description = fix_garbled_encodings(entry.get("description", ""))
    pub_date = entry.get("published", "")

    logging.info(f"🔍 Processing: {post_title} - {post_url}")

    try:
        response = requests.get(post_url)
        soup = BeautifulSoup(response.content, 'html.parser')

        # Try multiple selectors to handle potential HTML structure changes
        paragraphs = []
        
        # Method 1: Look for the new structure with class selectors
        content_divs = soup.find_all('div', class_='tETUs')
        if content_divs:
            logging.info(f"✅ Found content using tETUs class selector for: {post_title}")
            for div in content_divs:
                # Find all paragraphs in the content div
                p_elements = div.find_all('p', class_=lambda c: c and ('_01XM8' in c))
                for p in p_elements:
                    text = extract_text_from_element(p)
                    if text:
                        paragraphs.append(f"<p>{text}</p>")
        
        # Method 2: Try the older selector as a fallback
        if not paragraphs:
            for p in soup.find_all("p"):
                style = p.get("style", "")
                if "Georgia" in style and ("18px" in style or "1.5em" in style):
                    cleaned_paragraph = clean_garbled_html(str(p))
                    paragraphs.append(cleaned_paragraph)
            if paragraphs:
                logging.info(f"✅ Found content using style-based selector for: {post_title}")
        
        # Method 3: Try a more generic approach if both specific methods fail
        if not paragraphs:
            # Look for any div that might contain the main article content
            article_divs = soup.find_all('div', class_=lambda c: c and (
                'article' in c.lower() or 'content' in c.lower() or 'post' in c.lower()
            ))
            for div in article_divs:
                p_elements = div.find_all('p')
                for p in p_elements:
                    # Filter out very short paragraphs that might be captions or metadata
                    text = p.get_text(strip=True)
                    if len(text) > 100:  # Only include substantial paragraphs
                        paragraphs.append(f"<p>{text}</p>")
            if paragraphs:
                logging.info(f"✅ Found content using generic article selector for: {post_title}")

        full_content_html = "\n".join(paragraphs) if paragraphs else ""
        if full_content_html:
            logging.info(f"✅ Extracted content: {len(paragraphs)} paragraphs for: {post_title}")
        else:
            logging.warning(f"⚠️ No content found for: {post_title}")
            
            # Log the first 1000 characters of HTML for debugging
            logging.info(f"Debug HTML sample: {str(soup)[:1000]}")

    except Exception as e:
        full_content_html = ""
        logging.error(f"❌ Error scraping {post_url}: {str(e)}")

    # Create feed entry
    fe = fg.add_entry()
    fe.title(post_title)
    fe.link(href=post_url)
    
    # Ensure GUID is present - use URL as permalink GUID
    guid_value = post_url
    fe.guid(guid_value, permalink=True)
    
    # Add description
    fe.description(post_description)
    
    # Add publication date with timezone info
    if pub_date:
        try:
            # Try to use the original date
            fe.pubDate(pub_date)
        except:
            # If there's an error with the original date, use current time with timezone
            fe.pubDate(datetime.now(timezone.utc))
    else:
        # If no publication date is available, use current time with timezone
        fe.pubDate(datetime.now(timezone.utc))
    
    # Add full content
    if full_content_html:
        fe.content(content=full_content_html, type='CDATA')

# --- Output files for different hosting scenarios ---
output_dir = "output"
os.makedirs(output_dir, exist_ok=True)

# Standard XML output
output_file = os.path.join(output_dir, "full_feed.xml")
try:
    # Generate RSS feed with pretty formatting
    rss_feed = fg.rss_str(pretty=True)
    
    # Extra validation: Ensure required elements are present
    if b'<atom:link' not in rss_feed or b'rel="self"' not in rss_feed:
        logging.warning("⚠️ atom:link with rel='self' might be missing from the feed")
        
    if b'<guid' not in rss_feed:
        logging.warning("⚠️ guid elements might be missing from items")
    
    # Write the feed file
    with open(output_file, "wb") as f:
        f.write(rss_feed)
    logging.info(f"📦 Full-content RSS feed written to {output_file}")
    
    # Create .htaccess file (note: this won't work on GitHub Pages, but included for completeness)
    htaccess_file = os.path.join(output_dir, ".htaccess")
    htaccess_content = """
# Set correct MIME type for RSS feed
<Files "full_feed.xml">
    ForceType application/rss+xml
</Files>
"""
    with open(htaccess_file, "w") as f:
        f.write(htaccess_content)
    logging.info(f"📦 Created .htaccess file for proper MIME type")
    
    # Create a PHP wrapper for hosting on servers that support PHP
    # This will force the correct Content-Type
    php_wrapper = os.path.join(output_dir, "feed.php")
    php_content = """<?php
header('Content-Type: application/rss+xml');
readfile('full_feed.xml');
?>
"""
    with open(php_wrapper, "w") as f:
        f.write(php_content)
    logging.info(f"📦 Created PHP wrapper for proper MIME type")
    
except Exception as e:
    logging.error(f"❌ Failed to write feed file: {e}")

logging.info("✅ Script completed.")
