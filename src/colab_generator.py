# ============================================================================
# Google Colab Static SEO Website Generator
# Single-cell script for generating multi-language static HTML website
# ============================================================================

# Step 1: Install required packages
!pip install deep-translator jinja2 beautifulsoup4 tqdm requests -q

# Step 2: Import libraries
import os
import json
import random
import re
import zipfile
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.colab import files
from bs4 import BeautifulSoup
from jinja2 import Environment, BaseLoader
from deep_translator import GoogleTranslator
from tqdm import tqdm
import requests
import csv
import sys

# Increase CSV field size limit
max_int = sys.maxsize
while True:
    try:
        csv.field_size_limit(max_int)
        break
    except OverflowError:
        max_int = int(max_int / 10)

# ============================================================================
# Configuration
# ============================================================================
OUTPUT_DIR = "output"
MAX_WORKERS = 10
SITEMAP_URL = "https://infoedu.uz/sitemap.xml"
BACKLINK_DOMAIN = "https://infoedu.uz"

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

# ============================================================================
# Helper Functions
# ============================================================================

def setup_directories():
    """Create output directories."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'en'), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'ru'), exist_ok=True)

def clean_content(content: str) -> str:
    """Remove all <a> tags from content but keep the text inside them."""
    if not content:
        return ""
    soup = BeautifulSoup(content, 'html.parser')
    for anchor in soup.find_all('a'):
        anchor.unwrap()
    return str(soup)

def translate_text(text: str, source_lang: str = 'uz', target_lang: str = 'en') -> str:
    """Translate text using deep-translator."""
    if not text or not text.strip():
        return text
    
    text_clean = ' '.join(text.split())
    max_chunk_length = 4000
    
    if len(text_clean) > max_chunk_length:
        sentences = text_clean.split('. ')
        chunks = []
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < max_chunk_length:
                current_chunk += sentence + ". "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + ". "
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        translated_chunks = []
        for chunk in chunks:
            try:
                translator = GoogleTranslator(source=source_lang, target=target_lang)
                translated = translator.translate(chunk)
                translated_chunks.append(translated)
            except:
                translated_chunks.append(chunk)
        return " ".join(translated_chunks)
    
    try:
        translator = GoogleTranslator(source=source_lang, target=target_lang)
        translated = translator.translate(text_clean)
        return translated if translated else text_clean
    except Exception as e:
        print(f"Translation error: {e}")
        return text_clean

def inject_backlink(content: str, target_url: str, anchor_text: str) -> str:
    """Inject a dofollow backlink into the content."""
    if not content or not target_url:
        return content
    
    soup = BeautifulSoup(content, 'html.parser')
    backlink = soup.new_tag('a', href=target_url, rel='dofollow')
    backlink.string = anchor_text
    
    paragraphs = soup.find_all('p')
    if paragraphs:
        last_p = paragraphs[-1]
        last_p.append(" — ")
        last_p.append(backlink)
    else:
        new_p = soup.new_tag('p')
        new_p.append("Source: ")
        new_p.append(backlink)
        soup.append(new_p)
    
    return str(soup)

def generate_slug(title: str) -> str:
    """Generate a URL-friendly slug from title."""
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug[:100]

def extract_meta_description(content: str, max_length: int = 160) -> str:
    """Extract or generate a meta description from content."""
    if not content:
        return ""
    soup = BeautifulSoup(content, 'html.parser')
    text = soup.get_text(strip=True)
    if len(text) > max_length:
        truncated = text[:max_length]
        last_period = truncated.rfind('.')
        if last_period > max_length * 0.7:
            return truncated[:last_period + 1]
        return truncated + "..."
    return text

def read_posts_csv(csv_file: str) -> list:
    """Read posts from CSV file."""
    posts = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
        if not rows:
            print("[ERROR] CSV file is empty")
            return []
        
        # Find title and content columns
        title_col = None
        content_col = None
        for col in rows[0].keys():
            col_lower = col.lower()
            if 'title' in col_lower and not title_col:
                title_col = col
            if 'content' in col_lower and not content_col:
                content_col = col
        
        if not title_col or not content_col:
            print(f"[ERROR] Could not find 'title' and 'content' columns")
            print(f"Available columns: {list(rows[0].keys())}")
            return []
        
        for row in rows:
            title = str(row.get(title_col, '')).strip()
            content = str(row.get(content_col, '')).strip()
            if title and content:
                posts.append({'title': title, 'content': content})
    
    return posts

def fetch_sitemap_urls(sitemap_url: str) -> list:
    """Fetch URLs from sitemap.xml."""
    try:
        response = requests.get(sitemap_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'xml')
        urls = [loc.get_text(strip=True) for loc in soup.find_all('loc') if loc.get_text(strip=True)]
        return urls
    except:
        # Fallback to main domain and some common paths
        return [
            "https://infoedu.uz",
            "https://infoedu.uz/news",
            "https://infoedu.uz/articles",
            "https://infoedu.uz/about"
        ]

# ============================================================================
# HTML Templates (embedded in code)
# ============================================================================

ARTICLE_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ lang_code }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{{ meta_description }}">
    <title>{{ title }}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
    <style>
        nav.container-fluid { margin-bottom: 2rem; }
        .breadcrumbs { margin-bottom: 1.5rem; font-size: 0.9rem; }
        .breadcrumbs a { text-decoration: none; }
        .related-articles { margin-top: 3rem; padding-top: 2rem; border-top: 1px solid var(--pico-muted-border-color); }
        .related-articles h3 { margin-bottom: 1rem; }
        .related-articles ul { list-style: none; padding-left: 0; }
        .related-articles li { margin-bottom: 0.75rem; }
        .related-articles a { text-decoration: none; }
        footer { margin-top: 3rem; padding-top: 2rem; border-top: 1px solid var(--pico-muted-border-color); text-align: center; color: var(--pico-muted-color); font-size: 0.9rem; }
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
            <header><h1>{{ title }}</h1></header>
            <div class="content">{{ content | safe }}</div>
            {% if related_articles %}
            <aside class="related-articles">
                <h3>{{ related_section_title }}</h3>
                <ul>
                    {% for article in related_articles %}
                    <li><a href="{{ article.filename }}">{{ article.title }}</a></li>
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

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ lang_code }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{{ meta_description }}">
    <title>{{ page_title }}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
    <style>
        nav.container-fluid { margin-bottom: 2rem; }
        .breadcrumbs { margin-bottom: 1.5rem; font-size: 0.9rem; }
        .articles-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.5rem; margin-top: 2rem; }
        .article-card { padding: 1.5rem; border: 1px solid var(--pico-muted-border-color); border-radius: var(--pico-border-radius); transition: transform 0.2s, box-shadow 0.2s; }
        .article-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .article-card a { text-decoration: none; color: inherit; }
        .article-card h3 { margin-top: 0; margin-bottom: 0.5rem; }
        footer { margin-top: 3rem; padding-top: 2rem; border-top: 1px solid var(--pico-muted-border-color); text-align: center; color: var(--pico-muted-color); font-size: 0.9rem; }
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
            <a href="../index.html">Home</a> &gt; <strong>{{ lang_name }}</strong>
        </div>
        <header>
            <h1>{{ page_title }}</h1>
            <p>{{ page_description }}</p>
        </header>
        <div class="articles-grid">
            {% for post in posts %}
            <div class="article-card">
                <a href="{{ post.filename }}"><h3>{{ post.title }}</h3></a>
            </div>
            {% endfor %}
        </div>
        <footer>
            <p>Generated for Educational Purposes. Source: <a href="https://infoedu.uz" rel="dofollow">infoedu.uz</a></p>
        </footer>
    </main>
</body>
</html>"""

LANDING_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Educational articles and news from Uzbekistan">
    <title>Educational Articles - InfoEdu</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
    <style>
        .hero { text-align: center; padding: 3rem 2rem 2rem; margin-bottom: 2rem; }
        .hero h1 { font-size: 2.5rem; margin-bottom: 1rem; }
        .hero p { font-size: 1.1rem; color: var(--pico-muted-color); margin-bottom: 2rem; }
        .language-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 2rem; margin-bottom: 4rem; }
        .language-card { padding: 2rem; border: 2px solid var(--pico-muted-border-color); border-radius: var(--pico-border-radius); text-align: center; transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s; text-decoration: none; color: inherit; display: block; }
        .language-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.15); border-color: var(--pico-primary-color); }
        .language-card h2 { margin-top: 0; margin-bottom: 0.5rem; }
        .language-card p { margin-bottom: 0; color: var(--pico-muted-color); }
        footer { margin-top: 4rem; padding-top: 2rem; border-top: 1px solid var(--pico-muted-border-color); text-align: center; color: var(--pico-muted-color); font-size: 0.9rem; }
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
        <footer>
            <p>Generated for Educational Purposes. Source: <a href="https://infoedu.uz" rel="dofollow">infoedu.uz</a></p>
        </footer>
    </main>
</body>
</html>"""

# ============================================================================
# Main Processing Function
# ============================================================================

def process_article(args):
    """Process a single article (for parallel execution)."""
    post_index, post, lang_code, lang_config, sitemap_urls = args
    try:
        # Clean content
        cleaned_content = clean_content(post['content'])
        
        # Translate
        translated_title = translate_text(post['title'], 'uz', lang_code)
        translated_content = translate_text(cleaned_content, 'uz', lang_code)
        
        # Inject backlink
        if sitemap_urls:
            target_url = random.choice(sitemap_urls)
            anchor_text = random.choice(lang_config['anchors'])
            translated_content = inject_backlink(translated_content, target_url, anchor_text)
        
        # Generate metadata
        meta_description = extract_meta_description(translated_content)
        slug = generate_slug(translated_title)
        filename = f"{slug}.html"
        
        return {
            'title': translated_title,
            'content': translated_content,
            'filename': filename,
            'slug': slug,
            'index': post_index,
            'meta_description': meta_description
        }
    except Exception as e:
        print(f"Error processing article {post_index}: {e}")
        return None

# ============================================================================
# Main Execution
# ============================================================================

print("=" * 60)
print("Google Colab Static SEO Website Generator")
print("=" * 60)

# Step 1: Upload CSV file
print("\n[STEP 1] Upload your posts.csv file...")
uploaded = files.upload()

csv_file = None
for filename in uploaded.keys():
    if filename.endswith('.csv'):
        csv_file = filename
        print(f"[OK] Found CSV file: {csv_file}")
        break

if not csv_file:
    print("[ERROR] No CSV file found! Please upload a file named 'posts.csv'")
    raise FileNotFoundError("CSV file not found")

# Step 2: Setup directories
print("\n[STEP 2] Setting up directories...")
setup_directories()

# Step 3: Read CSV
print("\n[STEP 3] Reading CSV file...")
posts = read_posts_csv(csv_file)
print(f"[OK] Loaded {len(posts)} posts")

if not posts:
    print("[ERROR] No posts found in CSV!")
    raise ValueError("No posts found")

# Step 4: Fetch sitemap URLs
print("\n[STEP 4] Fetching sitemap URLs...")
sitemap_urls = fetch_sitemap_urls(SITEMAP_URL)
print(f"[OK] Found {len(sitemap_urls)} URLs for backlinks")

# Step 5: Setup Jinja2 environment
env = Environment(loader=BaseLoader())
article_template = env.from_string(ARTICLE_TEMPLATE)
index_template = env.from_string(INDEX_TEMPLATE)
landing_template = env.from_string(LANDING_TEMPLATE)

# Step 6: Process each language
all_processed_posts = {}

for lang_code, lang_config in LANGUAGES.items():
    print(f"\n{'='*60}")
    print(f"Processing {lang_config['name']} ({lang_code})...")
    print(f"{'='*60}")
    
    # Process articles in parallel
    tasks = [(idx, post, lang_code, lang_config, sitemap_urls) for idx, post in enumerate(posts)]
    
    processed_posts = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        with tqdm(total=len(tasks), desc=f"Translating {lang_config['name']}", unit="article") as pbar:
            futures = {executor.submit(process_article, task): task[0] for task in tasks}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    processed_posts.append(result)
                pbar.update(1)
    
    # Sort by index
    processed_posts.sort(key=lambda x: x['index'])
    
    # Assign internal links (5 random articles)
    print(f"\n[INFO] Assigning internal links...")
    for post in processed_posts:
        current_idx = post['index']
        available_indices = [i for i in range(len(processed_posts)) if i != current_idx]
        num_links = min(5, len(available_indices))
        related_indices = random.sample(available_indices, num_links) if available_indices else []
        post['related_articles'] = [
            {
                'title': processed_posts[i]['title'],
                'filename': processed_posts[i]['filename']
            }
            for i in related_indices
        ]
    
    # Generate HTML files
    print(f"\n[INFO] Generating HTML files...")
    lang_dir = os.path.join(OUTPUT_DIR, lang_code)
    related_title = "Читайте также" if lang_code == 'ru' else "Read Also"
    
    for post in tqdm(processed_posts, desc="Generating HTML", unit="file"):
        html_content = article_template.render(
            title=post['title'],
            content=post['content'],
            meta_description=post['meta_description'],
            lang_code=lang_code,
            lang_name=lang_config['name'],
            related_articles=post.get('related_articles', []),
            related_section_title=related_title
        )
        
        article_path = os.path.join(lang_dir, post['filename'])
        with open(article_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    # Generate index.html for this language
    if lang_code == 'ru':
        page_title = "Образовательные статьи"
        page_description = "Статьи и новости об образовании в Узбекистане"
        meta_desc = "Образовательные статьи и новости из Узбекистана"
    else:
        page_title = "Educational Articles"
        page_description = "Articles and news about education in Uzbekistan"
        meta_desc = "Educational articles and news from Uzbekistan"
    
    index_html = index_template.render(
        posts=[{'title': p['title'], 'filename': p['filename']} for p in processed_posts],
        lang_code=lang_code,
        lang_name=lang_config['name'],
        page_title=page_title,
        page_description=page_description,
        meta_description=meta_desc
    )
    
    index_path = os.path.join(lang_dir, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    print(f"[OK] Generated {len(processed_posts)} articles + index.html for {lang_config['name']}")
    all_processed_posts[lang_code] = processed_posts

# Step 7: Generate landing page
print(f"\n[STEP 7] Generating landing page...")
landing_html = landing_template.render()
landing_path = os.path.join(OUTPUT_DIR, 'index.html')
with open(landing_path, 'w', encoding='utf-8') as f:
    f.write(landing_html)
print("[OK] Landing page generated")

# Step 8: Create ZIP file
print(f"\n[STEP 8] Creating ZIP file...")
zip_filename = "website.zip"
with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files_list in os.walk(OUTPUT_DIR):
        for file in files_list:
            file_path = os.path.join(root, file)
            arcname = os.path.relpath(file_path, OUTPUT_DIR)
            zipf.write(file_path, arcname)
print(f"[OK] Created {zip_filename}")

# Step 9: Download ZIP
print(f"\n[STEP 9] Downloading {zip_filename}...")
files.download(zip_filename)

print("\n" + "=" * 60)
print("✅ Build complete!")
print(f"Generated {len(posts)} articles in {len(LANGUAGES)} languages")
print(f"Output: {zip_filename}")
print("=" * 60)
