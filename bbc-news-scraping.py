import requests
from bs4 import BeautifulSoup
import csv
import os
from datetime import datetime

BASE_URL = "https://www.bbc.com"
CSV_FILE = "articles.csv"

def get_article_links():
    res = requests.get(f"{BASE_URL}/news")
    soup = BeautifulSoup(res.text, "lxml")

    links = soup.select('a[href*="/news"]')

    article_urls = []
    for link in links:
        href = link.get("href")
        if href and "/news" in href and "live" not in href and "av" not in href:
            if href.startswith("/"):
                href = BASE_URL + href
            article_urls.append(href)

    return list(set(article_urls))  


def scrape_article(url):
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "lxml")

    title_tag = soup.select_one("h1")
    title = title_tag.text.strip() if title_tag else "No title"

    paragraphs = soup.select("article p")
    content = "\n".join([p.text.strip() for p in paragraphs])

    return title, content


def save_to_csv(url, title, content):
    
    file_exists = os.path.isfile(CSV_FILE)
    
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Timestamp', 'URL', 'Title', 'Content']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow({
            'Timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'URL': url,
            'Title': title,
            'Content': content
        })


def remove_duplicate_urls():
    if not os.path.isfile(CSV_FILE):
        return
    
    rows = []
    with open(CSV_FILE, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)
    
    seen_urls = {}
    for i, row in enumerate(rows):
        url = row['URL']
        seen_urls[url] = i  
    
    unique_rows = [rows[i] for url, i in seen_urls.items()]
    
    cleaned_rows = [row for row in unique_rows if row["Content"].strip() != ""]
    
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Timestamp', 'URL', 'Title', 'Content']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)
    
    print(f"Removed duplicates. Kept {len(unique_rows)} unique articles.")


links = get_article_links()
print(f"Found {len(links)} article links")

for url in links:  
    title, content = scrape_article(url)
    
    save_to_csv(url, title, content)
    print(f"Saved to {CSV_FILE}")

print(f"All articles saved to {CSV_FILE}")

remove_duplicate_urls()
