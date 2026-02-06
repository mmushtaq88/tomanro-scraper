import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor


BASE_URL = "https://www.tomanro.de/"
MENU_ENDPOINT = "https://www.tomanro.de/MenuDeskNeu.php?Menubut={}"

def get_sub_sub_category_links():
    """
    Fetches all sub-sub-category (final product listing) links
    from tomanro.de mega menus.

    Returns:
        list[str]: Absolute URLs of sub-sub-category pages
    """

    session = requests.Session()
    links = set()

    # There are 6 top-level menus
    for menubut in range(1, 7):
        url = MENU_ENDPOINT.format(menubut)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.select("a.MainMenuLink[href]"):
            href = a["href"].strip()

            # Final product listing pages
            if href.endswith("-Gruppe") and not href.endswith("-Hauptgruppe"):
                full_url = urljoin(BASE_URL, href)
                links.add(full_url)

    return sorted(links)

##################################################################################################################
## PRODUCTS LINKS EXTRACTOR
##################################################################################################################

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


#############################################################################################################
## SINGLE PRODUCT EXTRACTOR
#############################################################################################################

def scrape_product_variants(page_link):
    """
    Scrapes product variant grid from a page and returns product information.
    Handles both page types: with accordions and without accordions.

    Args:
        page_link (str): URL of the page to scrape

    Returns:
        list: List of dictionaries containing product information for unique variants
    """

    # Configure Selenium options
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    options.add_argument(f'user-agent={user_agent}')

    driver = None
    try:
        # Initialize Chrome driver
        driver = webdriver.Chrome(options=options)

        # Navigate to the page
        driver.get(page_link)

        # Wait for the page to load
        time.sleep(5)

        # Get page source
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')

        # Get base product name
        product_name_element = soup.find('h1', class_='TypUeber')
        base_product_name = ""
        if product_name_element:
            base_product_name = product_name_element.get('content', '').strip()
            if not base_product_name:
                base_product_name = product_name_element.text.strip()

        # Try both page structures
        all_variants = []

        # METHOD 1: Check for pages WITHOUT accordions (TabZel2 structure)
        tab_zel2 = soup.find('div', class_='TabZel2')
        if tab_zel2:
            variants = extract_variants_from_tabzel2(tab_zel2, base_product_name)
            all_variants.extend(variants)

        # METHOD 2: Check for pages WITH accordions (TabZeile panel structure)
        tab_zeile_panels = soup.find_all('div', class_='TabZeile panel panel-default')
        if tab_zeile_panels:
            variants = extract_variants_from_accordions(tab_zeile_panels, base_product_name)
            all_variants.extend(variants)

        # METHOD 3: Direct search for CarArtikel anywhere (fallback)
        if not all_variants:
            car_artikel_list = soup.find_all('div', class_='CarArtikel')
            for variant in car_artikel_list:
                product_data = extract_variant_data(variant, base_product_name, is_accordion=False)
                all_variants.append(product_data)

        # Remove duplicates based on serial number
        unique_variants = []
        seen_serials = set()

        for variant in all_variants:
            serial = variant.get('product_serial_number', '')
            if serial and serial not in seen_serials:
                seen_serials.add(serial)
                unique_variants.append(variant)
            elif not serial:  # If no serial, still add it (rare case)
                unique_variants.append(variant)

        # Clean the data
        cleaned_variants = clean_product_data(unique_variants)

        return cleaned_variants

    except Exception as e:
        return []

    finally:
        if driver:
            driver.quit()


def extract_variants_from_tabzel2(tab_zel2_element, base_product_name):
    """Extract variants from pages WITHOUT accordions (TabZel2 structure)."""
    variants = []

    # Find all CarArtikel in desktop version first (cleanest data)
    prodgrup_desktop = tab_zel2_element.find('div', class_='ProdgrupDesktop')
    if prodgrup_desktop:
        produkte_car = prodgrup_desktop.find('div', class_='ProdukteCar')
        if produkte_car:
            car_artikel_list = produkte_car.find_all('div', class_='CarArtikel')
        else:
            car_artikel_list = prodgrup_desktop.find_all('div', class_='CarArtikel')
    else:
        # Fallback: get all CarArtikel in TabZel2
        car_artikel_list = tab_zel2_element.find_all('div', class_='CarArtikel')

    for variant in car_artikel_list:
        product_data = extract_variant_data(variant, base_product_name, is_accordion=False)
        variants.append(product_data)

    return variants


def extract_variants_from_accordions(tab_zeile_panels, base_product_name):
    """Extract variants from pages WITH accordions (TabZeile panel structure)."""
    variants = []

    for panel in tab_zeile_panels:
        # Look for content divs inside the accordion
        content_divs = panel.find_all('div', class_='content', style=lambda x: x and 'display: block' in str(x))

        for content_div in content_divs:
            # Extract data from this content div
            product_data = extract_variant_data_from_content(content_div, base_product_name)
            if product_data:
                variants.append(product_data)

        # Also look for CarArtikel directly in the panel (fallback)
        car_artikel_list = panel.find_all('div', class_='CarArtikel')
        for variant in car_artikel_list:
            product_data = extract_variant_data(variant, base_product_name, is_accordion=True)
            variants.append(product_data)

    return variants


def extract_variant_data_from_content(content_div, base_product_name):
    """Extract variant data from content div in accordion pages."""
    product_data = {}

    # Get variant description
    variant_desc_element = content_div.find('div', class_='ArtTypBez Bezeichnung')
    variant_desc = variant_desc_element.text.strip() if variant_desc_element else ""

    # Product name
    if base_product_name and variant_desc:
        product_data['product_name'] = f"{base_product_name} {variant_desc}"
    elif base_product_name:
        product_data['product_name'] = base_product_name
    else:
        product_data['product_name'] = variant_desc if variant_desc else ""

    # Get price
    price_element = content_div.find('span', class_='preis')
    if price_element:
        price_text = price_element.text.strip()
        # Clean price text
        price_text = re.sub(r'\s+', ' ', price_text)
        product_data['product_price'] = price_text
    else:
        product_data['product_price'] = ""

    # Get serial number
    serial_element = content_div.find('div', class_='ArtDetailsCar HstArtikel')
    if serial_element:
        product_data['product_serial_number'] = serial_element.text.strip()
    else:
        product_data['product_serial_number'] = ""

    return product_data


def extract_variant_data(variant_element, base_product_name, is_accordion=False):
    """Extract data from a single variant element (works for both page types)."""
    product_data = {}

    # Extract variant name/description
    if is_accordion:
        # For accordion pages, look for ArtTypBez Bezeichnung
        art_typ_bez = variant_element.find('div', class_='ArtTypBez Bezeichnung')
    else:
        # For non-accordion pages, look for ArtTypBez
        art_typ_bez = variant_element.find('div', class_='ArtTypBez')

    variant_name = ""
    if art_typ_bez:
        variant_name = art_typ_bez.text.strip()
        # Clean variant name
        if base_product_name in variant_name:
            variant_name = variant_name.replace(base_product_name, '').strip()

    # Combine with base product name
    if base_product_name and variant_name:
        product_data['product_name'] = f"{base_product_name} {variant_name}"
    else:
        product_data['product_name'] = base_product_name or variant_name

    # Extract price - different selectors for different page types
    if is_accordion:
        # For accordion pages: span.preis inside SortPreis2
        sort_preis = variant_element.find('div', class_='SortPreis2')
        if sort_preis:
            price_element = sort_preis.find('span', class_='preis')
            price_text = price_element.text.strip() if price_element else sort_preis.get_text(strip=True)
        else:
            price_text = ""
    else:
        # For non-accordion pages: SortPreis2 text
        sort_preis = variant_element.find('div', class_='SortPreis2')
        price_text = sort_preis.get_text(strip=True) if sort_preis else ""

    # Clean price text
    if price_text:
        price_text = re.sub(r'\s+', ' ', price_text)
        # Remove "exkl. 19% MwSt." if present
        price_text = re.sub(r'exkl\.\s*\d+%\s*MwSt\.', '', price_text, flags=re.IGNORECASE)
        price_text = price_text.strip()

    product_data['product_price'] = price_text

    # Extract serial number
    if is_accordion:
        # For accordion pages: ArtDetailsCar HstArtikel
        art_details = variant_element.find('div', class_='ArtDetailsCar HstArtikel')
    else:
        # For non-accordion pages: ArtDetailsCar
        art_details = variant_element.find('div', class_='ArtDetailsCar')

    if art_details:
        product_data['product_serial_number'] = art_details.text.strip()
    else:
        product_data['product_serial_number'] = ""

    # Additional fallback for serial number from image
    if not product_data['product_serial_number']:
        img_element = variant_element.find('img', class_='Bildanzeigen')
        if img_element:
            for attr in ['alt', 'title']:
                text = img_element.get(attr, '')
                if 'Artikel-Nr.:' in text:
                    match = re.search(r'Artikel-Nr\.:\s*([^\s]+)', text)
                    if match:
                        product_data['product_serial_number'] = match.group(1)
                        break

    return product_data


def clean_product_data(products):
    """Clean and standardize product data."""
    cleaned_products = []

    for product in products:
        cleaned = product.copy()

        # Clean product name - remove duplicates
        name = cleaned.get('product_name', '')
        # Remove duplicate product names if they appear twice
        words = name.split()
        if len(words) > 2 and words[0] == words[1]:
            name = ' '.join(words[1:])
        cleaned['product_name'] = name.strip()

        # Clean price - ensure consistent format
        price = cleaned.get('product_price', '')
        # Remove extra text and ensure € symbol at the end
        price = re.sub(r'[^\d,\s€]', '', price).strip()
        # Format: "1.958,37 €" not "1.958,37€"
        if '€' in price and not price.endswith(' €'):
            price = price.replace('€', '').strip() + ' €'
        cleaned['product_price'] = price

        cleaned_products.append(cleaned)

    return cleaned_products


def get_product_variants(page_link):
    """
    Main function to get product variants from any page type.

    Args:
        page_link (str): URL of the product page

    Returns:
        list: List of dictionaries with product data for each unique variant
              Returns empty list if no variants found or error occurs
    """
    return scrape_product_variants(page_link)



#####################################################################################################
## MAIN SCRAPER
#####################################################################################################
import csv
from concurrent.futures import ThreadPoolExecutor

def scrape_all_products_to_csv(output_file='output.csv', max_workers=5):
    """
    Fetch all product variants from tomanro.de and save to a CSV file.

    Steps:
    1. Fetch all sub-sub-category links.
    2. For each category, fetch all product links.
    3. For each product, fetch all variants.
    4. Save all variants to a CSV file.

    Args:
        output_file (str): Path to save the CSV file.
        max_workers (int): Number of threads for parallel product scraping.
    """

    print("Fetching all category links...")
    category_links = get_sub_sub_category_links()
    print(f"Found {len(category_links)} categories.")

    all_products = []

    for idx, category_link in enumerate(category_links, start=1):
        print(f"\n[{idx}/{len(category_links)}] Processing category: {category_link}")
        product_links = get_all_product_links(category_link)
        print(f"  Found {len(product_links)} products in this category.")

        # Scrape product variants in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(get_product_variants, product_links))

        # Flatten list of lists and append to all_products
        for variant_list in results:
            all_products.extend(variant_list)

        print(f"  Total variants collected so far: {len(all_products)}")

    if all_products:
        # Write to CSV
        keys = all_products[0].keys()
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_products)

        print(f"\nScraping completed. Total variants: {len(all_products)}")
        print(f"Data saved to {output_file}")
    else:
        print("No product data found.")

if __name__ == "__main__":
    scrape_all_products_to_csv()
