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


# # Test function
# if __name__ == "__main__":
#     # Test with both types of pages
#     test_urls = [
#         # Page WITHOUT accordions
#         "https://www.tomanro.de/2636-Wampfler_Federleitungstrommel_Express_SR-Typen",
#         # Page WITH accordions (you'll need to provide actual URL)
#         # "URL_FOR_ACCORDION_PAGE_HERE"
#     ]
#
#     for url in test_urls:
#         print(f"\nTesting URL: {url}")
#         print("=" * 60)
#
#         variants = get_product_variants(url)
#
#         if variants:
#             print(f"Found {len(variants)} unique product variants:")
#             for i, variant in enumerate(variants, 1):
#                 print(f"\nVariant {i}:")
#                 print(f"  Name: {variant.get('product_name', 'N/A')}")
#                 print(f"  Price: {variant.get('product_price', 'N/A')}")
#                 print(f"  Serial: {variant.get('product_serial_number', 'N/A')}")
#         else:
#             print("No variants found.")
#
#         print(f"\nList structure (length: {len(variants)}):")
#         print(variants)



