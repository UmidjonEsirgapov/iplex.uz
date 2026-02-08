#!/usr/bin/env python3
"""
Generate sitemap.xml from existing output files.
Run this after build.py to create/update sitemap.xml
"""

import os
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = "output"
LANGUAGES = ['en', 'ru']


def generate_sitemap(base_url: str = "https://yoursite.com"):
    """
    Generate sitemap.xml file with all articles and index pages.
    """
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
    for lang_code in LANGUAGES:
        lang_dir = os.path.join(OUTPUT_DIR, lang_code)
        
        if not os.path.exists(lang_dir):
            continue
        
        # Add language index page
        urls.append({
            'loc': f"{base_url}/{lang_code}/",
            'lastmod': current_date,
            'changefreq': 'daily',
            'priority': '0.9'
        })
        
        # Add all HTML articles for this language (without .html extension)
        for file in os.listdir(lang_dir):
            if file.endswith('.html') and file != 'index.html':
                clean_url = file.replace('.html', '')
                urls.append({
                    'loc': f"{base_url}/{lang_code}/{clean_url}",
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


def main():
    import sys
    
    print("=" * 60)
    print("Sitemap Generator")
    print("=" * 60)
    
    # Get URL from command line argument or use default
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = "https://yoursite.com"
        print(f"[INFO] Using default URL: {base_url}")
        print(f"[INFO] To use custom URL, run: python generate_sitemap.py https://yourdomain.com")
    
    print(f"\n[INFO] Generating sitemap for: {base_url}")
    
    sitemap_xml = generate_sitemap(base_url)
    sitemap_path = os.path.join(OUTPUT_DIR, 'sitemap.xml')
    
    with open(sitemap_path, 'w', encoding='utf-8') as f:
        f.write(sitemap_xml)
    
    # Count URLs
    url_count = sitemap_xml.count('<url>')
    
    print(f"\n[OK] Sitemap generated successfully!")
    print(f"     File: {sitemap_path}")
    print(f"     URLs: {url_count}")
    print(f"\n[INFO] Upload sitemap.xml to your website root directory")
    print(f"       and submit it to Google Search Console.")


if __name__ == "__main__":
    main()
