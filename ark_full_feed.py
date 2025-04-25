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
    # Check for common patterns that need fixing
    if " wont " in text:
        text = text.replace(" wont ", " won't ")
    if "wont " in text:
        text = text.replace("wont ", "won't ")
    if " wont" in text:
        text = text.replace(" wont", " won't")
    
    # Fix O'Connor and similar possessives 
    text = re.sub(r'(\w+)s\s+([^\s])', r"\1's \2", text)
    
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


def create_content_signature(text):
    """
    Create a unique signature for a paragraph to use in deduplication.
    Uses the entire content after normalization, not just the first 50 chars.
    
    Args:
        text (str): Paragraph text
        
    Returns:
        str: Signature for deduplication
    """
    # Remove all whitespace
    text = re.sub(r'\s+', '', text).lower()
    # Remove all punctuation
    text = re.sub(r'[^\w]', '', text)
    # Return the full text for exact matching
    return text


# Dictionary to store captions for each URL
url_to_captions = {}

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

        # --- Extract captions for media:description tags ---
        image_captions = []
        
        # Method 1: Look for figcaptions with class JlS9j (as in the example)
        figcaptions = soup.find_all('figcaption', class_='JlS9j')
        if figcaptions:
            for figcaption in figcaptions:
                spans = figcaption.find_all('span')
                for span in spans:
                    caption_text = span.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = fix_garbled_encodings(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"📸 Found image caption (class method): {caption_text[:50]}...")
        
        # Method 2: Generic figcaption search if the class-based search finds nothing
        if not image_captions:
            figcaptions = soup.find_all('figcaption')
            for figcaption in figcaptions:
                # Try to get text from span within figcaption
                spans = figcaption.find_all('span')
                if spans:
                    for span in spans:
                        caption_text = span.get_text(strip=True)
                        if caption_text and len(caption_text) > 20:  # Filter out very short captions
                            caption_text = fix_garbled_encodings(caption_text)
                            image_captions.append(caption_text)
                            logging.info(f"📸 Found image caption (generic method): {caption_text[:50]}...")
                else:
                    # Get text directly from figcaption
                    caption_text = figcaption.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = fix_garbled_encodings(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"📸 Found image caption (direct method): {caption_text[:50]}...")
        
        # Method 3: Look for div with class _3mtS- that contains figcaption (as in the example)
        img_containers = soup.find_all('div', class_='_3mtS-')
        for container in img_containers:
            figcaption = container.find('figcaption')
            if figcaption:
                spans = figcaption.find_all('span')
                for span in spans:
                    caption_text = span.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = fix_garbled_encodings(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"📸 Found image caption (container method): {caption_text[:50]}...")
        
        # Method 4: Look for div with class bYXDH that contains figcaption (as in the example)
        img_containers = soup.find_all('div', class_='bYXDH')
        for container in img_containers:
            figcaption = container.find('figcaption')
            if figcaption:
                spans = figcaption.find_all('span')
                for span in spans:
                    caption_text = span.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = fix_garbled_encodings(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"📸 Found image caption (bYXDH method): {caption_text[:50]}...")

        # Method 5: Look for quoted text in paragraphs that might be exhibit names
        paragraphs = soup.find_all('p')
        for paragraph in paragraphs:
            # Check if paragraph contains both quotes and relevant keywords
            text = paragraph.get_text(strip=True)
            
            # General case for quoted content that might be captions
            if ('"' in text or "'" in text) and any(keyword in text.lower() for keyword in 
                                                ['exhibit', 'display', 'shown', 'pictured', 'photo']):
                # Try to extract the quoted part if it's an exhibit name
                matches = re.findall(r'["\'](.*?)["\']', text)
                for match in matches:
                    if len(match) > 20:  # Only include substantial quotes
                        caption_text = fix_garbled_encodings(match)
                        image_captions.append(caption_text)
                        logging.info(f"📸 Found image caption (quote extraction): {caption_text[:50]}...")
        
        # De-duplicate captions
        if image_captions:
            # Use a set to remove duplicates while preserving order
            unique_captions = []
            seen = set()
            for caption in image_captions:
                if caption not in seen:
                    unique_captions.append(caption)
                    seen.add(caption)
            image_captions = unique_captions
        
        # Store captions for this URL
        if image_captions:
            url_to_captions[post_url] = image_captions

        # --- First-step content extraction: Get raw text and remove direct duplicates ---
        # This helps with the website's tendency to duplicate paragraphs
        raw_paragraphs = [] 
        seen_paragraphs = set()
        
        # Split paragraphs directly from HTML content to catch duplication
        html_str = str(soup)
        # Remove all <script> and <style> tags first
        html_str = re.sub(r'<script.*?</script>', '', html_str, flags=re.DOTALL)
        html_str = re.sub(r'<style.*?</style>', '', html_str, flags=re.DOTALL)
        
        # Split by paragraph tags
        paragraph_parts = html_str.split("<p")
        for part in paragraph_parts[1:]:  # Skip first part (before first <p>)
            # Find where paragraph ends
            end_idx = part.find("</p>")
            if end_idx > 0:
                # Extract text within paragraph
                para_html = "<p" + part[:end_idx + 4]
                para_soup = BeautifulSoup(para_html, 'html.parser')
                text = para_soup.get_text(strip=True)
                
                # Only include substantial paragraphs
                if len(text) > 100:
                    # Create a signature for this paragraph
                    sig = create_content_signature(text)
                    if sig not in seen_paragraphs:
                        seen_paragraphs.add(sig)
                        raw_paragraphs.append((text, para_html))
        
        # --- Secondary content extraction for backup methods ---
        if not raw_paragraphs:
            # Method 1: Look for the new structure with class selectors
            content_divs = soup.find_all('div', class_='tETUs')
            if content_divs:
                logging.info(f"✅ Found content using tETUs class selector for: {post_title}")
                for div in content_divs:
                    # Find all paragraphs in the content div
                    p_elements = div.find_all('p', class_=lambda c: c and ('_01XM8' in c))
                    for p in p_elements:
                        text = extract_text_from_element(p)
                        if text and len(text) > 100:
                            sig = create_content_signature(text)
                            if sig not in seen_paragraphs:
                                seen_paragraphs.add(sig)
                                raw_paragraphs.append((text, f"<p>{text}</p>"))

            # Method 2: Try the older selector as a fallback
            if not raw_paragraphs:
                for p in soup.find_all("p"):
                    style = p.get("style", "")
                    if "Georgia" in style and ("18px" in style or "1.5em" in style):
                        text = p.get_text(strip=True)
                        if len(text) > 100:
                            sig = create_content_signature(text)
                            if sig not in seen_paragraphs:
                                seen_paragraphs.add(sig)
                                html = clean_garbled_html(str(p))
                                raw_paragraphs.append((text, html))
                if raw_paragraphs:
                    logging.info(f"✅ Found content using style-based selector for: {post_title}")

            # Method 3: Try a more generic approach if both specific methods fail
            if not raw_paragraphs:
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
                            sig = create_content_signature(text)
                            if sig not in seen_paragraphs:
                                seen_paragraphs.add(sig)
                                raw_paragraphs.append((text, f"<p>{text}</p>"))
                if raw_paragraphs:
                    logging.info(f"✅ Found content using generic article selector for: {post_title}")
        
        # Filter out subscription/comment paragraphs
        final_paragraphs = []
        for text, html in raw_paragraphs:
            if not any(phrase in text for phrase in [
                "Read the complete story", 
                "SUBSCRIBE NOW", 
                "Comment on this article",
                "on Nextdoor",
                "e-edition"
            ]):
                final_paragraphs.append(html)

        full_content_html = "\n".join(final_paragraphs) if final_paragraphs else ""
        
        if full_content_html:
            logging.info(f"✅ Extracted content: {len(final_paragraphs)} paragraphs for: {post_title}")
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
    # Generate the feed XML
    rss_feed = fg.rss_str(pretty=True).decode('utf-8')
    
    # Use direct XML string manipulation to add the media namespace with the correct prefix
    # This avoids the prefix being changed when parsed by XML libraries
    if '<rss ' in rss_feed and ' xmlns:media=' not in rss_feed:
        rss_feed = rss_feed.replace(
            '<rss ', 
            '<rss xmlns:media="http://search.yahoo.com/mrss/" ', 
            1
        )
    
    # Fix any remaining "wont" → "won't" issues in titles
    rss_feed = re.sub(r'<title>(.*?)wont(.*?)</title>', r'<title>\1won\'t\2</title>', rss_feed)
    
    # Create the XML document manually to ensure correct prefixes
    output_lines = []
    in_item = False
    current_url = None
    
    # Start with XML declaration and opening tags
    lines = rss_feed.splitlines()
    for line in lines:
        if "<item>" in line:
            in_item = True
            current_url = None
            output_lines.append(line)
        elif "</item>" in line:
            in_item = False
            # Add media:description tags before closing the item
            if current_url and current_url in url_to_captions:
                for caption in url_to_captions[current_url]:
                    output_lines.append(f"    <media:description>{caption}</media:description>")
            output_lines.append(line)
        elif in_item and "<link>" in line and "</link>" in line:
            # Extract URL to identify the current item
            url_match = re.search(r"<link>(.*?)</link>", line)
            if url_match:
                current_url = url_match.group(1)
            output_lines.append(line)
        else:
            output_lines.append(line)
    
    # Join all lines to create the final XML
    final_xml = "\n".join(output_lines)
    
    # Write the feed file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_xml)
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
    logging.error(f"❌ Failed to write feed file: {str(e)}")
    logging.exception("Stack trace:")

logging.info("✅ Script completed.")
