import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor


def fetch_page_links(url, headers):
    """Fetch product links from a single page HTML"""
    r = requests.get(url, headers=headers, timeout=50)
    if r.status_code != 200:
        print(f"Failed to fetch {url}")
        return set()

    soup = BeautifulSoup(r.text, "html.parser")
    product_links = set()

    # 🔹 Extract only real product links from product grid
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.endswith("-Typen"):
            full_url = urljoin(url, href)
            product_links.add(full_url)

    # 🔹 Extract pagination URLs
    pagination = soup.select_one(".floatright")
    page_urls = []
    if pagination:
        for a in pagination.find_all("a", href=True):
            page_urls.append(urljoin(url, a["href"]))

    return product_links, page_urls


def get_all_product_links(start_url):
    # headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/144.0.0.0 Safari/537.36"
        )
    }

    visited_pages = set()
    to_visit_pages = [start_url]
    all_product_links = set()

    while to_visit_pages:
        # Fetch pages in parallel for speed
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(lambda u: fetch_page_links(u, headers), to_visit_pages))

        next_pages = []
        for i, (products, pages) in enumerate(results):
            all_product_links.update(products)
            visited_pages.add(to_visit_pages[i])
            # Only add unvisited pages
            for p in pages:
                if p not in visited_pages and p not in to_visit_pages and p not in next_pages:
                    next_pages.append(p)

        to_visit_pages = next_pages

    return list(all_product_links)


