#!/usr/bin/env python3
"""
Remove .html from URLs in existing HTML files.
This script updates all links in generated HTML files to use clean URLs.
"""

import os
import re
from pathlib import Path

OUTPUT_DIR = "output"


def remove_html_from_links(html_content: str) -> str:
    """
    Remove .html extension from all internal links in HTML content.
    """
    # Pattern to match href attributes with .html
    # Matches: href="something.html" or href='something.html'
    patterns = [
        # Relative links: href="article.html" or href='article.html'
        (r'href="([^"]+\.html)"', r'href="\1"'),
        (r"href='([^']+\.html)'", r"href='\1'"),
        # But we want to remove .html, so:
        (r'href="([^"]+?)\.html"', r'href="\1"'),
        (r"href='([^']+?)\.html'", r"href='\1'"),
    ]
    
    # Remove .html from internal links (not external URLs)
    # Match relative paths and paths starting with /en/ or /ru/
    content = html_content
    
    # Pattern 1: href="article.html" -> href="article"
    content = re.sub(r'href="([^"/]+)\.html"', r'href="\1"', content)
    content = re.sub(r"href='([^'/]+)\.html'", r"href='\1'", content)
    
    # Pattern 2: href="../en/article.html" -> href="../en/article"
    content = re.sub(r'href="(\.\./)?(en|ru)/([^"]+?)\.html"', r'href="\1\2/\3"', content)
    content = re.sub(r"href='(\.\./)?(en|ru)/([^']+?)\.html'", r"href='\1\2/\3'", content)
    
    # Pattern 3: href="en/article.html" -> href="en/article"
    content = re.sub(r'href="(en|ru)/([^"]+?)\.html"', r'href="\1/\2"', content)
    content = re.sub(r"href='(en|ru)/([^']+?)\.html'", r"href='\1/\2'", content)
    
    # Pattern 4: href="index.html" -> href="index" (but keep index.html for root)
    # Actually, let's keep index.html as is for now, or change to just "/"
    # content = re.sub(r'href="index\.html"', r'href="/"', content)
    
    return content


def process_html_file(file_path: str):
    """
    Process a single HTML file to remove .html from links.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remove .html from links
        updated_content = remove_html_from_links(content)
        
        # Only write if content changed
        if content != updated_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Error processing {file_path}: {e}")
        return False


def main():
    print("=" * 60)
    print("Removing .html from URLs in existing HTML files")
    print("=" * 60)
    
    if not os.path.exists(OUTPUT_DIR):
        print(f"[ERROR] {OUTPUT_DIR} directory not found!")
        return
    
    html_files = []
    
    # Find all HTML files
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for file in files:
            if file.endswith('.html'):
                html_files.append(os.path.join(root, file))
    
    print(f"[INFO] Found {len(html_files)} HTML files")
    print(f"[INFO] Processing files...")
    
    updated_count = 0
    for file_path in html_files:
        if process_html_file(file_path):
            updated_count += 1
            if updated_count % 100 == 0:
                print(f"  [OK] Updated {updated_count} files...")
    
    print(f"\n[OK] Processing complete!")
    print(f"     Updated: {updated_count} files")
    print(f"     Total: {len(html_files)} files")
    print(f"\n[INFO] .htaccess file is already in {OUTPUT_DIR}/")
    print(f"       Make sure to upload .htaccess to your hosting root directory.")


if __name__ == "__main__":
    main()
