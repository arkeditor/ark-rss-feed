#!/usr/bin/env python3
"""
The Ark Newspaper Full RSS Feed Generator (Rebuilt)

This script enriches the RSS feed by:
- Pulling titles and descriptions from the blog feed.
- Filtering out items with titles starting with 'Public Notices'.
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
import logging
import re
import os
from datetime import datetime, timezone
import html
import sys
import time
import xml.etree.ElementTree as ET

OUTPUT_PATH = 'output/full_feed.xml'
HTTP_TIMEOUT = 20          # seconds per request; requests has no default timeout
MIN_ITEMS = 5              # fewer than this from the site feed means something broke upstream
HEADERS = {'User-Agent': 'ArkFullFeed/1.0 (+https://github.com/arkeditor/ark-rss-feed)'}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def http_get(url, tries=3):
    """GET with timeout, status check and backoff; raises after the last try."""
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if i == tries - 1:
                raise
            logging.warning(f"Retry {i + 1} for {url}: {e}")
            time.sleep(2 * (i + 1))


def load_previous_items():
    """Last good feed's items by guid, so one failed page fetch doesn't strip a story's body or photos."""
    prev = {}
    try:
        root = ET.parse(OUTPUT_PATH).getroot()
    except (OSError, ET.ParseError):
        return prev
    ns = {'content': 'http://purl.org/rss/1.0/modules/content/', 'media': 'http://search.yahoo.com/mrss/'}
    for item in root.iter('item'):
        guid = (item.findtext('guid') or '').strip()
        if not guid:
            continue
        media, last = [], None
        for el in item:
            if el.tag == '{%s}content' % ns['media']:
                last = {'url': el.get('url', ''), 'caption': '', 'type': el.get('medium', 'image')}
                media.append(last)
            elif el.tag == '{%s}description' % ns['media'] and last is not None:
                last['caption'] = el.text or ''
        prev[guid] = {'content_encoded': item.findtext('content:encoded', namespaces=ns), 'media_items': media}
    return prev

# --- Setup logging ---
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, f"scraper_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(filename=log_filename, level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# --- Load blog feed for processing ---
blog_feed_url = 'https://www.thearknewspaper.com/blog-feed.xml'
logging.info(f"Fetching blog feed: {blog_feed_url}")
try:
    blog_feed = feedparser.parse(http_get(blog_feed_url).content)
except requests.RequestException as e:
    logging.error(f"Blog feed fetch failed, keeping the last good feed: {e}")
    print(f"ERROR: blog feed fetch failed: {e}", file=sys.stderr)
    sys.exit(1)
if len(blog_feed.entries) < MIN_ITEMS:
    # An empty or truncated upstream feed must never overwrite the live one (MailerLite, Buffer, Social CMS read it).
    logging.error(f"Blog feed has {len(blog_feed.entries)} entries (bozo={blog_feed.get('bozo')}); keeping the last good feed")
    print(f"ERROR: blog feed returned only {len(blog_feed.entries)} entries", file=sys.stderr)
    sys.exit(1)
previous_items = load_previous_items()
# We'll use the blog feed entries directly as our primary source
feed = blog_feed

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
        r'high-impact community journalism',
        # The new site's newsletter box and support box on article pages (Kevin, Nov. 1, 2026: always filter out)
        r'delivered by email',
        r'named the nation',
        r'best small community weekly',
        r'accountability journalism with a mission',
        # Election gift box (aside.gift-box; excluded by selector, these are the fallback)
        r'Keep election coverage free',
        r'A gift keeps it that way'
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
    """Filter content to remove unwanted text and limit to 2500 characters."""
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
    
    # Limit to 2500 characters
    if len(filtered_html) > 2500:
        # Cut at the LAST paragraph break before the limit (re.search found the first one, which
        # either kept only the opening paragraph or fell through to a mid-word cut).
        # Skip breaks that follow a subhead (a paragraph that doesn't end a sentence), so the cut
        # never leaves a dangling heading.
        breaks = [m.end() for m in re.finditer(r'(?<=[.!?"\u201d\u2019)])</p>\s*(?=<p>)', filtered_html[:2500])]
        if breaks and breaks[-1] > 800:  # Only use if we found a decent amount of content
            filtered_html = filtered_html[:breaks[-1]].rstrip() + '\n<p>...</p>'
        else:
            # Otherwise just cut at 2500 and add ellipsis
            filtered_html = filtered_html[:2500] + '...</p>'
        # Never end on a dangling segment byline (one whose segment text was cut away).
        filtered_html = re.sub(r'(?:\n?<p>By [^<]*·[^<]*</p>)+(\n<p>\.\.\.</p>)$', r'\1', filtered_html)

    return filtered_html

# Segment byline lines built from the site's byline stacks: "By Kevin Hessel · Updated Nov. 13"
BYLINE_RE = re.compile(r'<p>By [^<]*·[^<]*</p>$')

# Site-inserted boxes inside or around the story whose text must not reach the feed
# (election gift box, Election Center rail, Recent Stories rail, newsletter form).
# The phrase list in is_boilerplate() is the fallback if the markup changes.
SITE_BOX_SELECTORS = ['aside.gift-box', 'section.ec', 'section.recent', 'form']

def is_site_box(el):
    for sel in SITE_BOX_SELECTORS:
        tag, cls = sel.split('.') if '.' in sel else (sel, None)
        for anc in [el] + list(el.parents):
            if anc.name == tag and (cls is None or cls in (anc.get('class') or [])):
                return True
    return False

def top_byline_div(soup):
    """The byline bar under the headline: the div holding the first /author/ link outside .seg-by and the story body."""
    for a in soup.select('article a[href^="/author/"]'):
        if a.find_parent('div', class_='seg-by') or a.find_parent('div', class_='ark-body'):
            continue
        if a.get_text().strip().startswith('By'):
            return a.parent
    return None

def nice_name(name, alt=''):
    """'KEVIN HESSEL' -> 'Kevin Hessel'; prefer the photo's alt text when it is the same name."""
    if alt and alt.strip().lower() == name.strip().lower():
        return alt.strip()
    def cap(w):
        w = w.capitalize()
        m = re.match(r"^(Mc|O')(\w)(.*)$", w)
        return m.group(1) + m.group(2).upper() + m.group(3) if m else w
    return ' '.join('-'.join(cap(p) for p in w.split('-')) for w in name.split())

def byline_line(div):
    """Turn a byline stack ('By KEVIN HESSEL' + 'Updated Nov. 13 · 5 min read') into 'By Kevin Hessel · Updated Nov. 13'."""
    parts = [s.strip() for s in div.stripped_strings]
    text = re.sub(r'\s+', ' ', ' '.join(parts))
    m = re.match(r'^By\s+(.+?)\s+((?:Updated\s+)?[A-Z][a-z]{2,4}\.?\s+\d.*)$', text)
    if not m:
        return ''
    name, date = m.group(1), m.group(2)
    date = re.sub(r'\s*·\s*\d+\s+min read.*$', '', date).strip()
    img = div.find('img') or (div.parent.find('img') if div.parent else None)
    return clean_text(f"By {nice_name(name, img.get('alt', '') if img else '')} · {date}")

def transform_media_url(url):
    """Transform media URLs to the specified format."""
    # Extract the media ID from the URL
    match = re.search(r'media/([^/]+)', url)
    if match:
        media_id = match.group(1)
        # Extract file extension if possible
        ext_match = re.search(r'\.(png|jpg|jpeg|gif|webp)', url.lower())
        ext = ext_match.group(1) if ext_match else 'png'
        
        # Create the new URL format
        return f"https://static.wixstatic.com/media/{media_id}/v1/fit/w_1000,h_999,al_c,q_80/file.{ext}"
    return url

NON_PERSON_CREDITS = {'reader submitted', 'staff', 'the ark staff', 'staff report', 'submitted'}


def caps_name(name):
    """House all-caps byline name: 'Ted McDonnell' -> 'TED McDONNELL' (Mc/Mac prefix stays mixed case)."""
    parts = re.split(r'(\b(?:Mc|Mac)(?=[A-Z]))', name)
    return ''.join(pt if re.fullmatch(r'Mc|Mac', pt) else pt.upper() for pt in parts)


def newsletter_byline(names):
    """dc:creator as MailerLite shows it: 'By KEVIN HESSEL', 'By A and B', 'By A, B and C'."""
    names = list(dict.fromkeys(names))
    if not names:
        return ''
    # Credits that aren't a person's name pass through as written (no 'By', no caps).
    if len(names) == 1 and names[0].lower() in NON_PERSON_CREDITS:
        return names[0]
    caps = [caps_name(n) for n in names]
    joined = caps[0] if len(caps) == 1 else ', '.join(caps[:-1]) + ' and ' + caps[-1]
    return 'By ' + joined


def xml_attr(text):
    """Escape a URL or other value for an XML attribute/element without double-escaping existing &amp;."""
    return html.escape(html.unescape(text or ''), quote=True)


def cdata(text):
    """Wrap in CDATA, splitting any ']]>' that would otherwise end the section early."""
    return '<![CDATA[' + (text or '').replace(']]>', ']]]]><![CDATA[>') + ']]>'


def safe_xml_text(text):
    """Safely escape text for XML, stripping invalid control chars and escaping entities."""
    if not text:
        return ""
    # Strip characters invalid in XML 1.0 (control chars except tab/LF/CR)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    # First convert &#38; to & to normalize
    text = text.replace("&#38;", "&")
    # Then escape all & to &amp;
    text = text.replace("&", "&amp;")
    # Escape other XML entities
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text

# For storing the feed entries before we create the final XML
all_entries = []

# --- Process each feed entry directly ---
for entry in feed.entries:
    post_url = entry.link
    # Use original title and description directly from the feed
    title = entry.title
    
    # Filter out entries with titles starting with 'Public Notices'
    if title.startswith('Public Notices'):
        logging.info(f"Skipping Public Notices entry: {title}")
        continue
    
    desc = entry.get('description', '')
    guid = entry.get('id', post_url)
    published = entry.get('published', datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000'))
    
    # Extract creator and categories from original feed if available
    names = [a.get('name', '').strip() for a in entry.get('authors', []) if a.get('name', '').strip()]
    if not names and entry.get('author'):
        names = [entry['author'].strip()]
    creator = newsletter_byline(names)
    categories = [tag.get('term', '') for tag in entry.get('tags', [])]
    
    logging.info(f"Processing {post_url}")
    
    # Create dictionary for this entry
    current_entry = {
        'title': title,
        'link': post_url,
        'description': desc,
        'guid': guid,
        'pubDate': published,
        'creator': creator,
        'categories': categories,
        'content_encoded': None,
        'media_items': []
    }
    
    # Now scrape the article page
    try:
        response = http_get(post_url)
        soup = BeautifulSoup(response.content, 'lxml')
        
        # First extract article content
        paragraphs = []
        
        # Primary content extraction target: <div class="tETUs"> with nested spans
        for div in soup.find_all('div', class_='tETUs'):
            for outer in div.select('span.BrKEk'):
                for inner in outer.select("span[style*='color:black'][style*='text-decoration:inherit']"):
                    txt = inner.get_text()
                    if len(txt) > 10 and not is_boilerplate(txt):
                        paragraphs.append(f"<p>{clean_text(txt)}</p>")
        
        # Fallback if the specific structure isn't found
        if not paragraphs:
            logging.warning(f"Could not find tETUs/BrKEk structure in {post_url}, falling back to p tags")
            # Stories that open with "UPDATE, <date>:" run-ins render as segments, each with a
            # byline stack (div.seg-by). Only then do the top byline bar and each stack become
            # "By Name · Date" lines; stories without segments come out exactly as before.
            has_segments = bool(soup.select('div.seg-by'))
            top_by = top_byline_div(soup) if has_segments else None
            for p in soup.find_all(['p', 'div']):
                if p.name == 'div':
                    if has_segments and ('seg-by' in (p.get('class') or []) or p is top_by):
                        line = byline_line(p)
                        if line:
                            paragraphs.append(f"<p>{line}</p>")
                    continue
                if is_site_box(p):
                    continue
                txt = p.get_text().strip()
                # Skip short texts and headers/section titles
                if len(txt) <= 20:
                    continue
                
                if not is_boilerplate(txt):
                    paragraphs.append(f"<p>{clean_text(txt)}</p>")
        
        # Dedupe & clean
        seen, unique = set(), []
        for p in paragraphs:
            norm = re.sub(r'\s+', ' ', BeautifulSoup(p, 'html.parser').get_text()).lower()
            if BYLINE_RE.match(p):
                unique.append(p)  # two segments can carry the same byline; keep both
            elif norm not in seen:
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
            # Ensure content is properly wrapped in paragraph tags
            if not content_html.startswith('<p>'):
                content_html = '<p>' + content_html
            if not content_html.endswith('</p>'):
                content_html = content_html + '</p>'
                
            # Store the properly formatted content
            current_entry['content_encoded'] = content_html
            logging.info(f"Added content ({len(content_html)} chars) to {post_url}")
        
        # Now extract media from THIS ARTICLE ONLY
        for fig in soup.find_all('figure'):
            img = fig.find('img')
            cap = fig.find('figcaption')
            
            if img and img.get('src'):
                img_url = img['src']
                # Transform to the requested URL format
                transformed_url = transform_media_url(img_url)
                
                img_caption = ""
                if cap:
                    # The new site shows the credit first in its own span (<span class="cr" data-orig="(via ...)">);
                    # put it back after the caption as typed in Wix: "Caption text. (via Name)" (Kevin, Nov. 1, 2026).
                    cr = cap.find('span', class_='cr')
                    if cr:
                        orig = cr.get('data-orig') or '(' + cr.get_text().strip() + ')'
                        cr.extract()
                        img_caption = clean_text(cap.get_text() + ' ' + orig)
                    else:
                        img_caption = clean_text(cap.get_text())
                
                # Add the media item
                media_item = {
                    'url': transformed_url,
                    'caption': img_caption,
                    'type': 'image'
                }
                
                # Add to this entry's media items
                current_entry['media_items'].append(media_item)
                logging.info(f"Added media to {post_url}: {transformed_url}")
        
    except Exception as e:
        logging.error(f"Error processing {post_url}: {e}")

    # A failed or empty page fetch keeps the body and photos from the last good build.
    old = previous_items.get(guid)
    if old:
        if not current_entry['content_encoded'] and old['content_encoded']:
            current_entry['content_encoded'] = old['content_encoded']
            logging.warning(f"Reused previous body for {post_url}")
        if not current_entry['media_items'] and old['media_items']:
            current_entry['media_items'] = old['media_items']
            logging.warning(f"Reused previous media for {post_url}")

    # Fallback: use Wix feed enclosure if scraping found no image
    if not current_entry['media_items'] and entry.get('enclosures'):
        for enclosure in entry.enclosures:
            href = enclosure.get('href', '')
            if href:
                transformed_url = transform_media_url(href)
                current_entry['media_items'].append({
                    'url': transformed_url,
                    'caption': '',
                    'type': 'image'
                })
                logging.info(f"Using feed enclosure image for {post_url}: {transformed_url}")
                break

    # Add the entry to our collection
    all_entries.append(current_entry)

# Create the XML output directly
output_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
output_xml += '<rss xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom" '
output_xml += 'xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">\n'
output_xml += ' <channel>\n'
output_xml += f'   <title>{safe_xml_text(feed.feed.get("title", "The Ark"))}</title>\n'
output_xml += f'   <link>https://www.thearknewspaper.com/blog-feed.xml</link>\n'
output_xml += f'   <description>{safe_xml_text(feed.feed.get("description", "The Ark is the weekly newspaper of Tiburon, Belvedere and Strawberry"))}</description>\n'
output_xml += '   <docs>http://www.rssboard.org/rss-specification</docs>\n'
output_xml += '   <generator>Ark RSS Feed Generator (Rebuilt)</generator>\n'
output_xml += '   <language>en</language>\n'
output_xml += '   <lastBuildDate>__LAST_BUILD_DATE__</lastBuildDate>\n'
# Fixed self-reference URL
output_xml += f'   <atom:link href="https://raw.githubusercontent.com/arkeditor/ark-rss-feed/main/output/full_feed.xml" rel="self" type="application/rss+xml" />\n'

# Add each entry
for entry in all_entries:
    output_xml += '   <item>\n'
    output_xml += f'     <title>{safe_xml_text(entry["title"])}</title>\n'
    output_xml += f'     <link>{xml_attr(entry["link"])}</link>\n'
    output_xml += f'     <description>{safe_xml_text(entry["description"])}</description>\n'
    
    # Add content:encoded if we have it
    if entry['content_encoded']:
        output_xml += f'     <content:encoded>{cdata(entry["content_encoded"])}</content:encoded>\n'
    
    # Add dc:creator if available
    if entry['creator']:
        output_xml += f'     <dc:creator>{safe_xml_text(entry["creator"])}</dc:creator>\n'
    
    # Add categories if available
    for category in entry['categories']:
        output_xml += f'     <category>{safe_xml_text(category)}</category>\n'
    
    output_xml += f'     <guid isPermaLink="false">{xml_attr(entry["guid"])}</guid>\n'
    output_xml += f'     <pubDate>{safe_xml_text(entry["pubDate"])}</pubDate>\n'
    
    # Output all media items (Media RSS spec allows multiple media:content per item)
    for media in entry['media_items']:
        output_xml += f'     <media:content url="{xml_attr(media["url"])}" medium="{xml_attr(media["type"])}"/>\n'
        if media['caption']:
            output_xml += f'     <media:description>{safe_xml_text(media["caption"])}</media:description>\n'
    
    output_xml += '   </item>\n'

# Close the channel and rss tags
output_xml += ' </channel>\n'
output_xml += '</rss>\n'

# Only rewrite the file when the stories changed: lastBuildDate alone shouldn't churn a commit every run.
LBD_RE = re.compile(r'<lastBuildDate>[^<]*</lastBuildDate>')
try:
    with open(OUTPUT_PATH, encoding='utf-8') as f:
        old_xml = f.read()
except OSError:
    old_xml = ''
if LBD_RE.sub('', old_xml) == LBD_RE.sub('', output_xml.replace('__LAST_BUILD_DATE__', '')):
    logging.info("No story changes; feed left as is")
    sys.exit(0)
output_xml = output_xml.replace('__LAST_BUILD_DATE__', datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000'))

# Refuse to publish XML that doesn't parse; the last good feed stays live.
try:
    ET.fromstring(output_xml.encode('utf-8'))
except ET.ParseError as e:
    logging.error(f"Generated feed is not well-formed XML ({e}); keeping the last good feed")
    print(f"ERROR: generated feed is not well-formed: {e}", file=sys.stderr)
    sys.exit(1)

# Write atomically so a crash mid-write can't leave a half file behind.
os.makedirs('output', exist_ok=True)
tmp_path = OUTPUT_PATH + '.tmp'
with open(tmp_path, 'w', encoding='utf-8') as f:
    f.write(output_xml)
os.replace(tmp_path, OUTPUT_PATH)

logging.info("Rebuilt feed written to output/full_feed.xml")
