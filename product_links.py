# import requests
# from bs4 import BeautifulSoup
# from urllib.parse import urljoin
# from concurrent.futures import ThreadPoolExecutor
#
#
# def fetch_page_links(url, headers):
#     """Fetch product links from a single page HTML"""
#     r = requests.get(url, headers=headers, timeout=50)
#     if r.status_code != 200:
#         print(f"Failed to fetch {url}")
#         return set()
#
#     soup = BeautifulSoup(r.text, "html.parser")
#     product_links = set()
#
#     # 🔹 Extract only real product links from product grid
#     for a in soup.find_all("a", href=True):
#         href = a["href"]
#         if href.endswith("-Typen"):
#             full_url = urljoin(url, href)
#             product_links.add(full_url)
#
#     # 🔹 Extract pagination URLs
#     pagination = soup.select_one(".floatright")
#     page_urls = []
#     if pagination:
#         for a in pagination.find_all("a", href=True):
#             page_urls.append(urljoin(url, a["href"]))
#
#     return product_links, page_urls
#
#
# def get_all_product_links(start_url):
#     # headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
#
#     headers = {
#         "User-Agent": (
#             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#             "AppleWebKit/537.36 (KHTML, like Gecko) "
#             "Chrome/144.0.0.0 Safari/537.36"
#         )
#     }
#
#     visited_pages = set()
#     to_visit_pages = [start_url]
#     all_product_links = set()
#
#     while to_visit_pages:
#         # Fetch pages in parallel for speed
#         with ThreadPoolExecutor(max_workers=5) as executor:
#             results = list(executor.map(lambda u: fetch_page_links(u, headers), to_visit_pages))
#
#         next_pages = []
#         for i, (products, pages) in enumerate(results):
#             all_product_links.update(products)
#             visited_pages.add(to_visit_pages[i])
#             # Only add unvisited pages
#             for p in pages:
#                 if p not in visited_pages and p not in to_visit_pages and p not in next_pages:
#                     next_pages.append(p)
#
#         to_visit_pages = next_pages
#
#     return list(all_product_links)
#
#
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _scroll_to_bottom(page, max_iterations: int = 40, wait_ms: int = 600) -> None:
    """
    Scrolls the page to the bottom, repeatedly, to trigger lazy loading.
    Stops when further scrolling no longer increases the document height
    or when max_iterations is reached.
    """
    last_height = 0

    for _ in range(max_iterations):
        # Scroll to the bottom
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        page.wait_for_timeout(wait_ms)

        # Check if more content was loaded
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height


def fetch_page_links(url, headers):
    """
    Fetch product links from a single sub-sub-category page HTML.

    This implementation uses Playwright to fully render the page and
    scroll to the bottom so that lazily loaded products appear before
    parsing. The function signature and return type remain unchanged.
    """
    product_links = set()
    page_urls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context_kwargs = {}
        if isinstance(headers, dict) and "User-Agent" in headers:
            context_kwargs["user_agent"] = headers["User-Agent"]

        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        try:
            page.goto(url, wait_until="load", timeout=60000)

            # Try to accept cookies if the banner appears
            try:
                page.locator("button.button_einverstanden").first.click(timeout=3000)
                page.wait_for_timeout(500)
            except PlaywrightTimeoutError:
                # Cookie banner not visible; continue normally
                pass

            # Scroll to the bottom to ensure all products are loaded
            _scroll_to_bottom(page)

            # Get the fully rendered HTML and parse with the existing logic
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # 🔹 Extract only real product links from the main product grid (div#products)
            # Exclude recommendations section (div.productkundenintere.eauch)
            products_container = soup.find("div", id="products")
            if products_container:
                # Only search for links within the main products container
                for a in products_container.find_all("a", href=True):
                    href = a["href"]
                    if href.endswith("-Typen"):
                        # Double-check: ensure this link is not inside recommendations section
                        # by checking if any parent is the recommendations container
                        parent = a.parent
                        is_in_recommendations = False
                        while parent:
                            if parent.name == "div" and "productkundenintere" in parent.get("class", []):
                                is_in_recommendations = True
                                break
                            parent = parent.parent

                        if not is_in_recommendations:
                            full_url = urljoin(url, href)
                            product_links.add(full_url)

            # 🔹 Extract pagination URLs
            pagination = soup.select_one(".floatright")
            if pagination:
                for a in pagination.find_all("a", href=True):
                    page_urls.append(urljoin(url, a["href"]))

        finally:
            browser.close()

    return product_links, page_urls


def get_all_product_links(start_url):
    """
    Given a sub-sub-category URL, return all product links for that
    category across all pagination pages.
    """
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

    # Sequentially visit each pagination page to avoid missing links
    while to_visit_pages:
        current_url = to_visit_pages.pop(0)
        if current_url in visited_pages:
            continue

        visited_pages.add(current_url)

        products, pages = fetch_page_links(current_url, headers)
        all_product_links.update(products)

        # Add new pagination pages to the queue
        for p_url in pages:
            if p_url not in visited_pages and p_url not in to_visit_pages:
                to_visit_pages.append(p_url)

    return list(all_product_links)

x = get_all_product_links("https://www.tomanro.de/15-Handseilwinden-Gruppe")
print(x)
print(len(x))

new_lst = []
for i in x:
    if i not in new_lst:
        new_lst.append(i)

print("len of new list: ", len(new_lst))