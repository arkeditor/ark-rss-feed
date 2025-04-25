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

logging.info("üöÄ Starting RSS feed enrichment script...")

# --- Parse the existing RSS feed ---
rss_url = "https://www.thearknewspaper.com/blog-feed.xml"
try:
    feed = feedparser.parse(rss_url)
    logging.info(f"‚úÖ Fetched RSS feed from {rss_url}")
except Exception as e:
    logging.error(f"‚ùå Failed to parse RSS feed: {e}")
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


def fix_titles_and_descriptions(text):
    """
    Fix common issues in titles and descriptions.
    """
    # Normalize curly quotes to straight
    text = text.replace("‚Äô", "'").replace("‚Äò", "'").replace("‚Äú", '"').replace("‚Äù", '"')
    # Fix common apostrophe issues
    text = re.sub(r"\bwont\b", "won't", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthi's\b", "this", text, flags=re.IGNORECASE)
    text = re.sub(r"\bwa's\b", "was", text, flags=re.IGNORECASE)
    # Fix missing apostrophes in names and possessives
    text = re.sub(r'(\w+)s\s+([^\s])', r"\1's \2", text)
    # Fix other common issues
    text = text.replace("&amp;#38;", "&")
    return text


def clean_text(text):
    """
    Normalize text by fixing garbled encodings and common apostrophe issues.
    """
    # Convert curly quotes to straight
    text = text.replace("‚Äô", "'").replace("‚Äò", "'").replace("‚Äú", '"').replace("‚Äù", '"')
    # Fix garbled encodings
    garbled_map = {
        "‚Äö√Ñ√¥t": "'t",
        "‚Äö√Ñ√≤": "'",
        "‚Äö√Ñ√¥": "'",
        "‚Äö√Ñ√∫": '"',
        "‚Äö√Ñ√π": '"',
        "√¢‚Ç¨‚Äù": "‚Äî",
        "√¢‚Ç¨‚Äú": "‚Äì",
        "√Ç": "",
    }
    for bad, good in garbled_map.items():
        text = text.replace(bad, good)
    # Fix common apostrophe issues
    text = re.sub(r"\bwont\b", "won't", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthi's\b", "this", text, flags=re.IGNORECASE)
    text = re.sub(r"\bwa's\b", "was", text, flags=re.IGNORECASE)
    return text

def dedupe_sentences(html):
    """Deduplicate repeated sentences within each <p> block."""
    def repl(m):
        content = m.group(1)
        # Split on sentence boundaries
        sentences = re.split(r'(?<=[\.\?!])\s+', content)
        seen = set()
        unique = []
        for s in sentences:
            s_str = s.strip()
            key = s_str.lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(s_str)
        return "<p>" + " ".join(unique) + "</p>"

    return re.sub(r'<p>(.*?)</p>', repl, html, flags=re.DOTALL)

    
    for garbled, correct in garbled_map.items():
        text = text.replace(garbled, correct)
    
    # Don't strip regular apostrophes and quotes - only remove truly non-ASCII characters
    # This regex keeps ASCII, apostrophes, and quotes
    text = re.sub(r'[^\x00-\x7F\'\"\`]', '', text)
    
    return text


def extract_text_from_element(element):
    """
    Extract text from an element, handling the nested span structure.
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


# Dictionary to store captions for each URL
url_to_captions = {}

# --- Loop through each post and scrape full content ---
for entry in feed.entries:
    post_url = entry.link
    
    # Fix titles and descriptions
    post_title = clean_text(fix_titles_and_descriptions(entry.title))
    post_description = clean_text(fix_titles_and_descriptions(entry.get("description", "")))
    pub_date = entry.get("published", "")

    logging.info(f"üîç Processing: {post_title} - {post_url}")

    try:
        response = requests.get(post_url)
        soup = BeautifulSoup(response.content, 'html.parser')

        # --- Extract captions for media:description tags ---
        image_captions = []
        
        # Method 1: Look for figcaptions with class JlS9j
        figcaptions = soup.find_all('figcaption', class_='JlS9j')
        if figcaptions:
            for figcaption in figcaptions:
                spans = figcaption.find_all('span')
                for span in spans:
                    caption_text = span.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = clean_text(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"üì∏ Found image caption (class method): {caption_text[:50]}...")
        
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
                            caption_text = clean_text(caption_text)
                            image_captions.append(caption_text)
                            logging.info(f"üì∏ Found image caption (generic method): {caption_text[:50]}...")
                else:
                    # Get text directly from figcaption
                    caption_text = figcaption.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = clean_text(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"üì∏ Found image caption (direct method): {caption_text[:50]}...")
        
        # Method 3: Look for div with class _3mtS- that contains figcaption
        img_containers = soup.find_all('div', class_='_3mtS-')
        for container in img_containers:
            figcaption = container.find('figcaption')
            if figcaption:
                spans = figcaption.find_all('span')
                for span in spans:
                    caption_text = span.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = clean_text(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"üì∏ Found image caption (container method): {caption_text[:50]}...")
        
        # Method 4: Look for div with class bYXDH that contains figcaption
        img_containers = soup.find_all('div', class_='bYXDH')
        for container in img_containers:
            figcaption = container.find('figcaption')
            if figcaption:
                spans = figcaption.find_all('span')
                for span in spans:
                    caption_text = span.get_text(strip=True)
                    if caption_text and len(caption_text) > 20:  # Filter out very short captions
                        caption_text = clean_text(caption_text)
                        image_captions.append(caption_text)
                        logging.info(f"üì∏ Found image caption (bYXDH method): {caption_text[:50]}...")
        
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

        # --- Simple and robust content extraction ---
        # For each article, we'll first check if we have previous content in the feed
        paragraphs = []
        
        # Check if this entry already has content in the original feed
        original_content = entry.get("content", [{}])[0].get("value", "")
        
        # If original content exists, use it
        if original_content and len(original_content) > 100:
            full_content_html = original_content
            logging.info(f"‚úÖ Using original content from feed for: {post_title}")
        else:
            # Try to extract content from the article page using the most reliable method
            # Method 1: Look for the content div with class tETUs
            content_divs = soup.find_all('div', class_='tETUs')
            if content_divs:
                logging.info(f"‚úÖ Found content using tETUs class selector for: {post_title}")
                for div in content_divs:
                    # Find all paragraphs in the content div
                    p_elements = div.find_all('p', class_=lambda c: c and ('_01XM8' in c))
                    for p in p_elements:
                        text = extract_text_from_element(p)
                        # Only include non-empty, substantial paragraphs
                        if text and len(text) > 10:
                            # Clean up the text and assemble the HTML paragraph
                            text = clean_text(text)
                            paragraphs.append(f"<p>{text}</p>")
            
            # Method 2: If no content found, try the original style-based selector
            if not paragraphs:
                for p in soup.find_all("p"):
                    style = p.get("style", "")
                    if "Georgia" in style and ("18px" in style or "1.5em" in style):
                        text = p.get_text(strip=True)
                        # Only include non-empty, substantial paragraphs
                        if text and len(text) > 10:
                            text = clean_text(text)
                            paragraphs.append(f"<p>{text}</p>")
                
                if paragraphs:
                    logging.info(f"‚úÖ Found content using style-based selector for: {post_title}")
            
            # Filter out paragraphs about subscribing or commenting
            filtered_paragraphs = []
            for p in paragraphs:
                text = BeautifulSoup(p, 'html.parser').get_text()
                if not any(phrase in text for phrase in [
                    "Read the complete story", 
                    "SUBSCRIBE NOW", 
                    "Comment on this article",
                    "e-edition", 
                    "on Nextdoor",
                    "Your support makes this possible"
                ]):
                    filtered_paragraphs.append(p)
            
            # Deduplicate paragraphs by comparing normalized text
            unique_paragraphs = []
            seen_texts = set()
            
            for p in filtered_paragraphs:
                text = BeautifulSoup(p, 'html.parser').get_text()
                # Normalize by removing whitespace and converting to lowercase
                normalized = re.sub(r'\s+', ' ', text).strip().lower()
                if normalized not in seen_texts:
                    seen_texts.add(normalized)
                    unique_paragraphs.append(p)
            
            full_content_html = "\n".join(unique_paragraphs) if unique_paragraphs else ""
            
            if full_content_html:
                logging.info(f"‚úÖ Extracted content: {len(unique_paragraphs)} paragraphs for: {post_title}")
            else:
                logging.warning(f"‚ö†Ô∏è No content found for: {post_title}")

    except Exception as e:
        full_content_html = ""
        logging.error(f"‚ùå Error scraping {post_url}: {str(e)}")

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
        # Deduplicate sentences within each paragraph
        full_content_html = dedupe_sentences(full_content_html)
        # Deduplicate repeated paragraphs
        full_content_html = re.sub(r'(<p>.*?</p>)(?:\s*\1)+', r'\1', full_content_html, flags=re.DOTALL)
        # Normalize and fix text
        full_content_html = clean_text(full_content_html)
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
    
    # Fix any remaining "wont" ‚Üí "won't" issues in titles
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
    logging.info(f"üì¶ Full-content RSS feed written to {output_file}")
    
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
    logging.info(f"üì¶ Created .htaccess file for proper MIME type")
    
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
    logging.info(f"üì¶ Created PHP wrapper for proper MIME type")
    
except Exception as e:
    logging.error(f"‚ùå Failed to write feed file: {str(e)}")
    logging.exception("Stack trace:")

logging.info("‚úÖ Script completed.")
