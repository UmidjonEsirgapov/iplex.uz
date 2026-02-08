#!/usr/bin/env python3
"""
Advanced Static Site Generator (SSG) for SEO purposes
Multi-language support (English & Russian) with internal linking strategy.
Features: Progress tracking, Resume capability, Translation cache, News feed on landing page.
"""

import os
import json
import random
import time
import sys
import hashlib
import threading
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape
from deep_translator import GoogleTranslator
from tqdm import tqdm
try:
    import pandas as pd  # type: ignore
    HAS_PANDAS = True
except ImportError:
    import csv
    HAS_PANDAS = False
    # Increase CSV field size limit to handle large content fields
    csv.field_size_limit(sys.maxsize)


# Configuration
SITEMAP_URL = "https://infoedu.uz/sitemap.xml"
CSV_FILE = "posts_filtered_export.csv"
OUTPUT_DIR = "output"
TEMPLATES_DIR = "templates"
CACHE_DIR = ".cache"
PROGRESS_FILE = ".progress.json"
MAX_RETRIES = 5
RETRY_DELAY = 3  # seconds
TRANSLATION_DELAY = 1.0  # Delay between translations to avoid rate limiting (optimized for large batches)
REQUEST_TIMEOUT = 60  # seconds
PROGRESS_SAVE_INTERVAL = 10  # Save progress every N articles (to reduce I/O)
MAX_WORKERS = 10  # Number of parallel threads for processing

# Supported languages
LANGUAGES = {
    'en': {
        'name': 'English',
        'code': 'en',
        'anchors': ["Source", "Official Data", "Read on infoedu.uz", "Details here", "More information"]
    },
    'ru': {
        'name': 'Русский',
        'code': 'ru',
        'anchors': ["Источник", "Официальные данные", "Подробнее на infoedu.uz", "Читать оригинал", "Новости образования"]
    }
}

# Internal linking configuration
MIN_INTERNAL_LINKS = 5
MAX_INTERNAL_LINKS = 10

# News feed configuration
LATEST_ARTICLES_COUNT = 12  # Number of latest articles to show on landing page


def setup_directories():
    """Create necessary directories if they don't exist."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'en'), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'ru'), exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)


def get_cache_key(text: str, target_lang: str) -> str:
    """Generate cache key for translation."""
    content_hash = hashlib.md5(f"{text}_{target_lang}".encode('utf-8')).hexdigest()
    return os.path.join(CACHE_DIR, f"trans_{target_lang}_{content_hash}.json")


# Cache lock for thread-safe cache operations
cache_lock = threading.Lock()

def load_from_cache(text: str, target_lang: str) -> Optional[str]:
    """Load translation from cache if exists (thread-safe)."""
    cache_file = get_cache_key(text, target_lang)
    if os.path.exists(cache_file):
        try:
            with cache_lock:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('translated')
        except:
            return None
    return None


def save_to_cache(text: str, target_lang: str, translated: str):
    """Save translation to cache (thread-safe)."""
    cache_file = get_cache_key(text, target_lang)
    try:
        with cache_lock:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({'original': text[:100], 'translated': translated}, f, ensure_ascii=False)
    except:
        pass


def load_progress() -> Dict:
    """Load progress from file."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


# Thread-safe locks (defined before functions that use them)
progress_lock = threading.Lock()
file_write_lock = threading.Lock()
latest_articles_lock = threading.Lock()

def save_progress(progress: Dict):
    """Save progress to file (thread-safe)."""
    try:
        with progress_lock:
            with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARNING] Could not save progress: {e}")


def is_post_processed(post_index: int, lang_code: str, posts: List[Dict], progress: Dict) -> bool:
    """Check if post is already processed."""
    if lang_code not in progress:
        return False
    
    if str(post_index) not in progress[lang_code]:
        return False
    
    post_data = progress[lang_code][str(post_index)]
    slug = generate_slug(post_data.get('title', ''))
    filename = f"{slug}.html"
    filepath = os.path.join(OUTPUT_DIR, lang_code, filename)
    
    return os.path.exists(filepath)


def fetch_sitemap_urls(sitemap_url: str, cache_file: str = None) -> List[str]:
    """
    Fetch and parse sitemap.xml to extract URLs.
    Uses cache to avoid repeated requests.
    """
    cache_file = cache_file or os.path.join(CACHE_DIR, 'sitemap_urls.json')
    
    # Try to load from cache first
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                # Cache valid for 24 hours
                if time.time() - cached_data.get('timestamp', 0) < 86400:
                    print(f"[OK] Loaded {len(cached_data.get('urls', []))} URLs from cache")
                    return cached_data.get('urls', [])
        except:
            pass
    
    print(f"Fetching sitemap from {sitemap_url}...")
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(sitemap_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            # Parse XML
            soup = BeautifulSoup(response.content, 'xml')
            urls = []
            
            # Find all <loc> tags in the sitemap
            for loc in soup.find_all('loc'):
                url = loc.get_text(strip=True)
                if url:
                    urls.append(url)
            
            # Save to cache
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump({'urls': urls, 'timestamp': time.time()}, f)
            except:
                pass
            
            print(f"[OK] Found {len(urls)} URLs in sitemap")
            return urls
            
        except requests.exceptions.Timeout:
            print(f"[ERROR] Timeout (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
        except requests.exceptions.ConnectionError:
            print(f"[ERROR] Connection error (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print("[WARNING] Could not fetch sitemap. Using cached data if available.")
                # Try to return cached data even if old
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            cached_data = json.load(f)
                            return cached_data.get('urls', [])
                    except:
                        pass
                return []
    
    return []


def clean_content(content: str) -> str:
    """
    Remove all <a> tags from content but keep the text inside them.
    This sanitizes the content before translation.
    """
    if not content:
        return ""
    
    soup = BeautifulSoup(content, 'html.parser')
    
    # Find all <a> tags and unwrap them (removes tag but keeps text)
    for anchor in soup.find_all('a'):
        anchor.unwrap()
    
    return str(soup)


def translate_text(text: str, source_lang: str = 'uz', target_lang: str = 'en', use_cache: bool = True, recursion_depth: int = 0) -> str:
    """
    Translate text from Uzbek to target language using deep-translator.
    Uses cache to avoid re-translating same content.
    Handles timeouts and errors with retries.
    Prevents infinite recursion by limiting recursion depth.
    """
    # Prevent infinite recursion
    MAX_RECURSION_DEPTH = 10
    if recursion_depth > MAX_RECURSION_DEPTH:
        print(f"[WARNING] Maximum recursion depth reached. Returning original text.")
        return text
    
    if not text or not text.strip():
        return text
    
    # Check cache first
    if use_cache:
        cached = load_from_cache(text, target_lang)
        if cached:
            return cached
    
    # Clean text for translation
    text_clean = ' '.join(text.split())
    
    # If text is too long, split it into chunks (iterative approach to avoid deep recursion)
    max_chunk_length = 4000  # Google Translate limit
    if len(text_clean) > max_chunk_length:
        # Split by sentences first
        sentences = text_clean.split('. ')
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence_with_dot = sentence + ". "
            # If adding this sentence would exceed limit, save current chunk and start new
            if len(current_chunk) + len(sentence_with_dot) > max_chunk_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # If single sentence is too long, split by words
                if len(sentence) > max_chunk_length:
                    # Split long sentence by words
                    words = sentence.split()
                    word_chunk = ""
                    for word in words:
                        if len(word_chunk) + len(word) + 1 > max_chunk_length:
                            if word_chunk:
                                chunks.append(word_chunk.strip())
                            word_chunk = word + " "
                        else:
                            word_chunk += word + " "
                    if word_chunk:
                        current_chunk = word_chunk
                else:
                    current_chunk = sentence_with_dot
            else:
                current_chunk += sentence_with_dot
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # If still no chunks (very edge case), force split by character
        if not chunks:
            chunks = [text_clean[i:i+max_chunk_length] for i in range(0, len(text_clean), max_chunk_length)]
        
        # Translate each chunk iteratively (not recursively to avoid stack overflow)
        translated_chunks = []
        for chunk in chunks:
            # Use iterative translation for chunks (no recursion)
            chunk_result = translate_text_single(chunk, source_lang, target_lang, use_cache)
            translated_chunks.append(chunk_result)
            time.sleep(TRANSLATION_DELAY)  # Delay between chunks
        
        result = " ".join(translated_chunks)
        if use_cache:
            save_to_cache(text, target_lang, result)
        return result
    
    # For short texts, translate directly
    return translate_text_single(text_clean, source_lang, target_lang, use_cache)


def translate_text_single(text: str, source_lang: str, target_lang: str, use_cache: bool = True) -> str:
    """
    Translate a single chunk of text (non-recursive helper function).
    """
    if not text or not text.strip():
        return text
    
    # Check cache first
    if use_cache:
        cached = load_from_cache(text, target_lang)
        if cached:
            return cached
    
    for attempt in range(MAX_RETRIES):
        try:
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            translated = translator.translate(text)
            
            if translated and translated != text:
                if use_cache:
                    save_to_cache(text, target_lang, translated)
                time.sleep(TRANSLATION_DELAY)  # Rate limiting
                return translated
            else:
                if attempt < MAX_RETRIES - 1:
                    print(f"[WARNING] Translation returned same/empty. Attempt {attempt + 1}/{MAX_RETRIES}")
                
        except Exception as e:
            error_msg = str(e).lower()
            if 'timeout' in error_msg or 'timed out' in error_msg:
                if attempt < MAX_RETRIES - 1:
                    print(f"[WARNING] Translation timeout (attempt {attempt + 1}/{MAX_RETRIES})")
            elif 'connection' in error_msg or 'network' in error_msg:
                if attempt < MAX_RETRIES - 1:
                    print(f"[WARNING] Network error (attempt {attempt + 1}/{MAX_RETRIES})")
            else:
                if attempt < MAX_RETRIES - 1:
                    print(f"[WARNING] Translation error (attempt {attempt + 1}/{MAX_RETRIES}): {str(e)[:100]}")
            
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (attempt + 1)
                time.sleep(wait_time)
            else:
                print(f"[ERROR] Failed to translate after {MAX_RETRIES} attempts. Using original text.")
                return text
    
    return text


def inject_backlink(content: str, target_url: str, anchor_text: str, lang: str) -> str:
    """
    Inject a strategic backlink into the content.
    Places it at the end of the last paragraph or appends a "Source" line.
    """
    if not content or not target_url:
        return content
    
    soup = BeautifulSoup(content, 'html.parser')
    
    # Create the backlink
    backlink = soup.new_tag('a', href=target_url, rel='dofollow')
    backlink.string = anchor_text
    
    # Try to find the last paragraph
    paragraphs = soup.find_all('p')
    if paragraphs:
        # Append to last paragraph
        last_p = paragraphs[-1]
        last_p.append(" — ")
        last_p.append(backlink)
    else:
        # If no paragraphs, append as a new paragraph at the end
        new_p = soup.new_tag('p')
        if lang == 'ru':
            new_p.append("Источник: ")
        else:
            new_p.append("Source: ")
        new_p.append(backlink)
        soup.append(new_p)
    
    return str(soup)


def extract_meta_description(content: str, max_length: int = 160) -> str:
    """
    Extract or generate a meta description from content.
    """
    if not content:
        return ""
    
    soup = BeautifulSoup(content, 'html.parser')
    text = soup.get_text(strip=True)
    
    # Take first max_length characters
    if len(text) > max_length:
        # Try to cut at sentence boundary
        truncated = text[:max_length]
        last_period = truncated.rfind('.')
        if last_period > max_length * 0.7:  # If period is not too early
            return truncated[:last_period + 1]
        return truncated + "..."
    
    return text


def read_posts_csv(csv_file: str) -> List[Dict]:
    """
    Read posts from CSV file.
    Handles different column name variations.
    """
    print(f"Reading posts from {csv_file}...")
    
    if not os.path.exists(csv_file):
        print(f"[ERROR] {csv_file} not found!")
        sys.exit(1)
    
    posts = []
    
    try:
        if HAS_PANDAS:
            # Try using pandas first for better CSV handling
            df = pd.read_csv(csv_file)
            
            # Map column names (handle variations)
            title_col = None
            content_col = None
            
            for col in df.columns:
                col_lower = col.lower()
                if 'title' in col_lower and not title_col:
                    title_col = col
                if 'content' in col_lower and not content_col:
                    content_col = col
            
            if not title_col or not content_col:
                print(f"[ERROR] Could not find 'title' and 'content' columns in CSV")
                print(f"Available columns: {list(df.columns)}")
                sys.exit(1)
            
            for _, row in df.iterrows():
                title = str(row[title_col]) if pd.notna(row[title_col]) else ""
                content = str(row[content_col]) if pd.notna(row[content_col]) else ""
                
                if title and content:
                    posts.append({
                        'title': title,
                        'content': content
                    })
        else:
            # Use standard csv module
            # Increase field size limit to handle large content
            max_int = sys.maxsize
            while True:
                try:
                    csv.field_size_limit(max_int)
                    break
                except OverflowError:
                    max_int = int(max_int / 10)
            
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
                if not rows:
                    print("[ERROR] CSV file is empty")
                    sys.exit(1)
                
                # Map column names (handle variations)
                title_col = None
                content_col = None
                
                for col in rows[0].keys():
                    col_lower = col.lower()
                    if 'title' in col_lower and not title_col:
                        title_col = col
                    if 'content' in col_lower and not content_col:
                        content_col = col
                
                if not title_col or not content_col:
                    print(f"[ERROR] Could not find 'title' and 'content' columns in CSV")
                    print(f"Available columns: {list(rows[0].keys())}")
                    sys.exit(1)
                
                for row in rows:
                    title = str(row.get(title_col, '')).strip()
                    content = str(row.get(content_col, '')).strip()
                    
                    if title and content:
                        posts.append({
                            'title': title,
                            'content': content
                        })
        
        print(f"[OK] Loaded {len(posts)} posts from CSV")
        return posts
        
    except Exception as e:
        print(f"[ERROR] Error reading CSV: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def generate_slug(title: str) -> str:
    """
    Generate a URL-friendly slug from title.
    """
    import re
    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug[:100]  # Limit length


def generate_sitemap(all_processed_posts: Dict, base_url: str = "https://yoursite.com") -> str:
    """
    Generate sitemap.xml file with all articles and index pages.
    Returns the XML content as a string.
    """
    from datetime import datetime
    
    urls = []
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # Add landing page
    urls.append({
        'loc': base_url,
        'lastmod': current_date,
        'changefreq': 'daily',
        'priority': '1.0'
    })
    
    # Add language index pages and articles
    for lang_code, lang_config in LANGUAGES.items():
        # Add language index page
        urls.append({
            'loc': f"{base_url}/{lang_code}/",
            'lastmod': current_date,
            'changefreq': 'daily',
            'priority': '0.9'
        })
        
        # Add all articles for this language
        if lang_code in all_processed_posts:
            for post in all_processed_posts[lang_code]:
                urls.append({
                    'loc': f"{base_url}/{lang_code}/{post.get('url_path', post['filename'].replace('.html', ''))}",
                    'lastmod': current_date,
                    'changefreq': 'weekly',
                    'priority': '0.8'
                })
    
    # Generate XML
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    
    for url_data in urls:
        xml_lines.append('  <url>')
        xml_lines.append(f"    <loc>{url_data['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{url_data['lastmod']}</lastmod>")
        xml_lines.append(f"    <changefreq>{url_data['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{url_data['priority']}</priority>")
        xml_lines.append('  </url>')
    
    xml_lines.append('</urlset>')
    
    return '\n'.join(xml_lines)


def assign_internal_links(current_index: int, total_posts: int, num_links: int) -> List[int]:
    """
    Randomly select indices for internal linking.
    Excludes the current article index.
    """
    available_indices = [i for i in range(total_posts) if i != current_index]
    if len(available_indices) < num_links:
        return available_indices
    return random.sample(available_indices, num_links)


def process_single_article(args: Tuple) -> Optional[Dict]:
    """
    Process a single article (thread-safe function for parallel processing).
    Returns processed article data or None if failed.
    """
    post_index, post, lang_code, lang_config, sitemap_urls, progress = args
    
    try:
        # Check if already processed (thread-safe check)
        with progress_lock:
            if is_post_processed(post_index, lang_code, [post], progress):
                post_data = progress[lang_code][str(post_index)]
                return {
                    'title': post_data['title'],
                    'filename': post_data['filename'],
                    'slug': post_data['slug'],
                    'index': post_index,
                    'skipped': True
                }
        
        # Step 1: Clean content (remove external links)
        cleaned_content = clean_content(post['content'])
        
        # Step 2: Translate title and content (with cache)
        translated_title = translate_text(post['title'], 'uz', lang_code, use_cache=True)
        translated_content = translate_text(cleaned_content, 'uz', lang_code, use_cache=True)
        
        # Step 3: Inject backlink
        if sitemap_urls:
            target_url = random.choice(sitemap_urls)
            anchor_text = random.choice(lang_config['anchors'])
            translated_content = inject_backlink(
                translated_content, target_url, anchor_text, lang_code
            )
        
                # Step 4: Generate metadata
                meta_description = extract_meta_description(translated_content)
                slug = generate_slug(translated_title)
                # Create filename without .html extension (clean URLs)
                filename = f"{slug}.html"  # File still has .html but URL won't show it
                url_path = slug  # Clean URL without .html
        
        # Thread-safe progress update
        with progress_lock:
            progress[lang_code][str(post_index)] = {
                'title': translated_title,
                'filename': filename,
                'slug': slug,
                'meta_description': meta_description
            }
        
        return {
            'title': translated_title,
            'content': translated_content,
            'filename': filename,
            'url_path': url_path,  # Clean URL without .html
            'slug': slug,
            'index': post_index,
            'meta_description': meta_description,
            'skipped': False
        }
        
    except Exception as e:
        # Log error but don't stop the process
        print(f"[ERROR] Article {post_index} failed: {str(e)[:100]}")
        return None


def create_default_templates():
    """Create default Jinja2 templates if they don't exist."""
    
    article_template = """<!DOCTYPE html>
<html lang="{{ lang_code }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{{ meta_description }}">
    <title>{{ title }}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
    <style>
        nav.container-fluid {
            margin-bottom: 2rem;
        }
        .breadcrumbs {
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
        }
        .breadcrumbs a {
            text-decoration: none;
        }
        .related-articles {
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid var(--pico-muted-border-color);
        }
        .related-articles h3 {
            margin-bottom: 1rem;
        }
        .related-articles ul {
            list-style: none;
            padding-left: 0;
        }
        .related-articles li {
            margin-bottom: 0.75rem;
        }
        .related-articles a {
            text-decoration: none;
        }
        footer {
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid var(--pico-muted-border-color);
            text-align: center;
            color: var(--pico-muted-color);
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <nav class="container-fluid">
        <ul>
            <li><strong><a href="../index.html">Home</a></strong></li>
        </ul>
        <ul>
            <li><a href="../en/index.html">English</a></li>
            <li><a href="../ru/index.html">Русский</a></li>
        </ul>
    </nav>
    
    <main class="container">
        <div class="breadcrumbs">
            <a href="../index.html">Home</a> &gt; 
            <a href="index.html">{{ lang_name }}</a> &gt; 
            <strong>{{ title }}</strong>
        </div>
        
        <article>
            <header>
                <h1>{{ title }}</h1>
            </header>
            
            <div class="content">
                {{ content | safe }}
            </div>
            
            {% if related_articles %}
            <aside class="related-articles">
                <h3>{{ related_section_title }}</h3>
                <ul>
                    {% for article in related_articles %}
                    <li>
                        <a href="{{ article.filename }}">{{ article.title }}</a>
                    </li>
                    {% endfor %}
                </ul>
            </aside>
            {% endif %}
        </article>
        
        <footer>
            <p>Generated for Educational Purposes. Source: <a href="https://infoedu.uz" rel="dofollow">infoedu.uz</a></p>
        </footer>
    </main>
</body>
</html>"""
    
    index_template = """<!DOCTYPE html>
<html lang="{{ lang_code }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{{ meta_description }}">
    <title>{{ page_title }}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
    <style>
        nav.container-fluid {
            margin-bottom: 2rem;
        }
        .breadcrumbs {
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
        }
        .articles-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-top: 2rem;
        }
        .article-card {
            padding: 1.5rem;
            border: 1px solid var(--pico-muted-border-color);
            border-radius: var(--pico-border-radius);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .article-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .article-card a {
            text-decoration: none;
            color: inherit;
        }
        .article-card h3 {
            margin-top: 0;
            margin-bottom: 0.5rem;
        }
        footer {
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid var(--pico-muted-border-color);
            text-align: center;
            color: var(--pico-muted-color);
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <nav class="container-fluid">
        <ul>
            <li><strong><a href="../index.html">Home</a></strong></li>
        </ul>
        <ul>
            <li><a href="../en/index.html">English</a></li>
            <li><a href="../ru/index.html">Русский</a></li>
        </ul>
    </nav>
    
    <main class="container">
        <div class="breadcrumbs">
            <a href="../index.html">Home</a> &gt; 
            <strong>{{ lang_name }}</strong>
        </div>
        
        <header>
            <h1>{{ page_title }}</h1>
            <p>{{ page_description }}</p>
        </header>
        
        <div class="articles-grid">
            {% for post in posts %}
            <div class="article-card">
                <a href="{{ post.filename }}">
                    <h3>{{ post.title }}</h3>
                </a>
            </div>
            {% endfor %}
        </div>
        
        <footer>
            <p>Generated for Educational Purposes. Source: <a href="https://infoedu.uz" rel="dofollow">infoedu.uz</a></p>
        </footer>
    </main>
</body>
</html>"""
    
    landing_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Educational articles and news from Uzbekistan">
    <title>Educational Articles - InfoEdu</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
    <style>
        .hero {
            text-align: center;
            padding: 3rem 2rem 2rem;
            margin-bottom: 2rem;
        }
        .hero h1 {
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }
        .hero p {
            font-size: 1.1rem;
            color: var(--pico-muted-color);
            margin-bottom: 2rem;
        }
        .language-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 2rem;
            margin-bottom: 4rem;
        }
        .language-card {
            padding: 2rem;
            border: 2px solid var(--pico-muted-border-color);
            border-radius: var(--pico-border-radius);
            text-align: center;
            transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
            text-decoration: none;
            color: inherit;
            display: block;
        }
        .language-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.15);
            border-color: var(--pico-primary-color);
        }
        .language-card h2 {
            margin-top: 0;
            margin-bottom: 0.5rem;
        }
        .language-card p {
            margin-bottom: 0;
            color: var(--pico-muted-color);
        }
        .news-section {
            margin-top: 4rem;
            padding-top: 3rem;
            border-top: 2px solid var(--pico-muted-border-color);
        }
        .news-section h2 {
            margin-bottom: 2rem;
            text-align: center;
        }
        .news-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
        }
        .news-card {
            padding: 1.5rem;
            border: 1px solid var(--pico-muted-border-color);
            border-radius: var(--pico-border-radius);
            transition: transform 0.2s, box-shadow 0.2s;
            background: var(--pico-card-background-color);
        }
        .news-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .news-card a {
            text-decoration: none;
            color: inherit;
        }
        .news-card h3 {
            margin-top: 0;
            margin-bottom: 0.5rem;
            font-size: 1.1rem;
        }
        .news-card .lang-badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            background: var(--pico-primary-background);
            color: var(--pico-primary-inverse);
            border-radius: var(--pico-border-radius);
            font-size: 0.75rem;
            margin-bottom: 0.5rem;
        }
        footer {
            margin-top: 4rem;
            padding-top: 2rem;
            border-top: 1px solid var(--pico-muted-border-color);
            text-align: center;
            color: var(--pico-muted-color);
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <main class="container">
        <div class="hero">
            <h1>Educational Articles</h1>
            <p>Choose your preferred language to browse articles and news from Uzbekistan</p>
        </div>
        
        <div class="language-cards">
            <a href="en/index.html" class="language-card">
                <h2>🇬🇧 English</h2>
                <p>Browse articles in English</p>
            </a>
            
            <a href="ru/index.html" class="language-card">
                <h2>🇷🇺 Русский</h2>
                <p>Просмотреть статьи на русском языке</p>
            </a>
        </div>
        
        {% if latest_articles %}
        <section class="news-section">
            <h2>Latest Articles</h2>
            <div class="news-grid">
                {% for article in latest_articles %}
                <div class="news-card">
                    <span class="lang-badge">{{ article.lang_name }}</span>
                    <a href="{{ article.url }}">
                        <h3>{{ article.title }}</h3>
                    </a>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}
        
        <footer>
            <p>Generated for Educational Purposes. Source: <a href="https://infoedu.uz" rel="dofollow">infoedu.uz</a></p>
        </footer>
    </main>
</body>
</html>"""
    
    # Write templates
    with open(os.path.join(TEMPLATES_DIR, 'article.html'), 'w', encoding='utf-8') as f:
        f.write(article_template)
    
    with open(os.path.join(TEMPLATES_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_template)
    
    with open(os.path.join(TEMPLATES_DIR, 'landing.html'), 'w', encoding='utf-8') as f:
        f.write(landing_template)
    
        print("[OK] Created default templates")


def main():
    """Main execution function."""
    print("=" * 60)
    print("Advanced Static Site Generator (SSG) - Multi-language Build")
    print("Features: Progress Tracking | Resume | Cache | News Feed")
    print("=" * 60)
    
    # Setup directories
    setup_directories()
    
    # Load progress
    progress = load_progress()
    print(f"\n[INFO] Progress loaded: {len(progress.get('en', {}))} EN, {len(progress.get('ru', {}))} RU articles processed")
    
    # Fetch sitemap URLs (with cache)
    sitemap_urls = fetch_sitemap_urls(SITEMAP_URL)
    
    # Read posts from CSV
    posts = read_posts_csv(CSV_FILE)
    
    if not posts:
        print("[ERROR] No posts found. Exiting.")
        sys.exit(1)
    
    # Setup Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(['html', 'xml'])
    )
    
    # Check if templates exist, create them if not
    if not os.path.exists(os.path.join(TEMPLATES_DIR, 'article.html')):
        create_default_templates()
    
    # Load templates
    try:
        article_template = env.get_template('article.html')
        index_template = env.get_template('index.html')
        landing_template = env.get_template('landing.html')
    except Exception as e:
        print(f"[ERROR] Error loading templates: {e}")
        sys.exit(1)
    
    # Process each language
    all_processed_posts = {}
    latest_articles = []  # For landing page news feed
    
    for lang_code, lang_config in LANGUAGES.items():
        print(f"\n{'='*60}")
        print(f"Processing {lang_config['name']} ({lang_code})...")
        print(f"{'='*60}")
        
        if lang_code not in progress:
            progress[lang_code] = {}
        
        processed_posts = []
        lang_dir = os.path.join(OUTPUT_DIR, lang_code)
        skipped_count = 0
        processed_count = 0
        error_count = 0
        start_time = time.time()
        
        # Prepare tasks for parallel processing
        tasks = []
        for idx, post in enumerate(posts):
            # Quick check if already processed (before adding to tasks)
            if is_post_processed(idx, lang_code, posts, progress):
                post_data = progress[lang_code][str(idx)]
                processed_posts.append({
                    'title': post_data['title'],
                    'filename': post_data['filename'],
                    'slug': post_data['slug'],
                    'index': idx,
                    'skipped': True
                })
                skipped_count += 1
            else:
                tasks.append((idx, post, lang_code, lang_config, sitemap_urls, progress))
        
        if skipped_count > 0:
            print(f"[INFO] Skipping {skipped_count} already processed articles...")
        
        # Process articles in parallel using ThreadPoolExecutor
        print(f"[INFO] Processing {len(tasks)} articles with {MAX_WORKERS} parallel workers...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all tasks
            future_to_index = {
                executor.submit(process_single_article, task): task[0] 
                for task in tasks
            }
            
            # Process completed tasks with progress bar
            with tqdm(total=len(tasks), desc=f"Translating {lang_config['name']}", unit="article") as pbar:
                for future in as_completed(future_to_index):
                    result = future.result()
                    if result:
                        if result.get('skipped'):
                            skipped_count += 1
                        else:
                            processed_posts.append(result)
                            processed_count += 1
                            
                            # Thread-safe update to latest articles
                            with latest_articles_lock:
                                latest_articles.append({
                                    'title': result['title'],
                                    'url': f"{lang_code}/{result['filename']}",
                                    'lang_name': lang_config['name']
                                })
                    else:
                        error_count += 1
                    
                    pbar.update(1)
                    
                    # Save progress periodically
                    if (processed_count + skipped_count) % PROGRESS_SAVE_INTERVAL == 0:
                        save_progress(progress)
        
        # Sort processed_posts by index to maintain order
        processed_posts.sort(key=lambda x: x['index'])
        
        # Final progress save
        save_progress(progress)
        
        elapsed_total = time.time() - start_time
        print(f"\n[OK] Completed {lang_config['name']}: {processed_count} processed, {skipped_count} skipped, {error_count} errors in {int(elapsed_total/60)} min")
        
        # Step 5: Assign internal links (spiderweb strategy)
        print(f"\n{'─'*60}")
        print("Assigning internal links (Spiderweb Strategy)...")
        print(f"{'─'*60}")
        
        print(f"Assigning internal links to {len(processed_posts)} articles...")
        with tqdm(total=len(processed_posts), desc="Linking articles", unit="article") as pbar:
            for post in processed_posts:
                current_idx = post['index']
                num_links = random.randint(MIN_INTERNAL_LINKS, min(MAX_INTERNAL_LINKS, len(processed_posts) - 1))
                related_indices = assign_internal_links(current_idx, len(processed_posts), num_links)
                
                post['related_articles'] = [
                    {
                        'title': processed_posts[i]['title'],
                        'filename': processed_posts[i].get('url_path', processed_posts[i]['filename'].replace('.html', ''))
                    }
                    for i in related_indices
                ]
                pbar.update(1)
        
        # Step 6: Generate HTML files for this language
        print(f"\n{'─'*60}")
        print(f"Generating HTML files for {lang_config['name']}...")
        print(f"{'─'*60}")
        
        # Determine related section title based on language
        if lang_code == 'ru':
            related_title = "Читайте также"
        else:
            related_title = "Read Also"
        
        def generate_html_file(post):
            """Generate HTML file for a single post (thread-safe)."""
            try:
                # Render HTML with stored translated content
                html_content = article_template.render(
                    title=post['title'],
                    content=post.get('content', ''),
                    meta_description=post.get('meta_description', ''),
                    lang_code=lang_code,
                    lang_name=lang_config['name'],
                    related_articles=post.get('related_articles', []),
                    related_section_title=related_title
                )
                
                article_path = os.path.join(lang_dir, post['filename'])
                with file_write_lock:
                    with open(article_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                return True
            except Exception as e:
                print(f"  [ERROR] Error generating HTML for {post['title'][:40]}: {e}")
                return False
        
        print(f"Generating HTML files for {len(processed_posts)} articles...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            with tqdm(total=len(processed_posts), desc="Generating HTML", unit="file") as pbar:
                futures = {executor.submit(generate_html_file, post): post for post in processed_posts}
                for future in as_completed(futures):
                    future.result()  # Wait for completion
                    pbar.update(1)
        
        # Step 7: Generate index.html for this language
        print(f"\nGenerating index.html for {lang_config['name']}...")
        
        if lang_code == 'ru':
            page_title = "Образовательные статьи"
            page_description = "Статьи и новости об образовании в Узбекистане"
            meta_desc = "Образовательные статьи и новости из Узбекистана"
        else:
            page_title = "Educational Articles"
            page_description = "Articles and news about education in Uzbekistan"
            meta_desc = "Educational articles and news from Uzbekistan"
        
        index_html = index_template.render(
            posts=[{'title': p['title'], 'filename': p.get('url_path', p['filename'].replace('.html', ''))} for p in processed_posts],
            lang_code=lang_code,
            lang_name=lang_config['name'],
            page_title=page_title,
            page_description=page_description,
            meta_description=meta_desc
        )
        
        index_path = os.path.join(lang_dir, 'index.html')
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(index_html)
        
        print(f"[OK] Saved: {lang_code}/index.html")
        
        all_processed_posts[lang_code] = processed_posts
    
    # Step 8: Generate landing page with news feed
    print(f"\n{'='*60}")
    print("Generating landing page with news feed...")
    print(f"{'='*60}")
    
    # Sort latest articles and take most recent
    latest_articles_sorted = sorted(latest_articles, key=lambda x: x['title'], reverse=True)[:LATEST_ARTICLES_COUNT]
    
    landing_html = landing_template.render(latest_articles=latest_articles_sorted)
    landing_path = os.path.join(OUTPUT_DIR, 'index.html')
    with open(landing_path, 'w', encoding='utf-8') as f:
        f.write(landing_html)
    
    print(f"[OK] Saved: index.html (landing page with {len(latest_articles_sorted)} latest articles)")
    
    # Step 9: Generate sitemap.xml
    print(f"\n{'='*60}")
    print("Generating sitemap.xml...")
    print(f"{'='*60}")
    
    # Base URL for sitemap
    base_url = "https://iplex.uz"
    
    sitemap_xml = generate_sitemap(all_processed_posts, base_url)
    sitemap_path = os.path.join(OUTPUT_DIR, 'sitemap.xml')
    with open(sitemap_path, 'w', encoding='utf-8') as f:
        f.write(sitemap_xml)
    
    print(f"[OK] Saved: sitemap.xml ({len(sitemap_xml.split('<url>')) - 1} URLs)")
    print(f"[INFO] Don't forget to update the base_url in the code to your actual domain!")
    
    print("\n" + "=" * 60)
    print("Build complete!")
    print(f"Generated {len(posts)} articles in {len(LANGUAGES)} languages")
    print(f"Output directory: {OUTPUT_DIR}/")
    print(f"Progress saved to: {PROGRESS_FILE}")
    print(f"Cache directory: {CACHE_DIR}/")
    print(f"Sitemap: {OUTPUT_DIR}/sitemap.xml")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[WARNING] Script interrupted. Progress has been saved.")
        print("You can resume by running the script again - it will skip already processed articles.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
