import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import re
import time
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# User agent - Custom identifier for Beslist scraper
USER_AGENT = "Beslist script voor SEO"

# Create a persistent session with retry logic
def create_session():
    """Create a requests session with retry logic and connection pooling"""
    session = requests.Session()

    # Configure retries
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )

    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=1)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session

# Global session for connection reuse
_session = create_session()

def get_scraper_ip() -> Optional[str]:
    """Get the IP address used by the scraper for outbound requests"""
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=5)
        if response.status_code == 200:
            return response.json().get("ip")
    except Exception as e:
        print(f"Failed to get scraper IP: {str(e)}")
    return None

def clean_url(url: str) -> str:
    """Remove query parameters from URL"""
    return url.split("?")[0] if url else ""

def is_valid_url(url: str) -> bool:
    """Check if URL is valid (not empty, not #, not javascript:)"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip().lower()
    if not url or url == "#" or url.startswith("javascript:"):
        return False
    return True

def scrape_product_page(url: str, conservative_mode: bool = False) -> Optional[Dict]:
    """
    Scrape a product listing page and extract:
    - h1 title
    - list of products (title, url, description)

    Args:
        url: URL to scrape
        conservative_mode: If True, use conservative rate (max 2 URLs/sec). Default: False (optimized rate)

    Returns None if request fails or statuscode != 200
    """
    try:
        # Clean URL first
        clean = clean_url(url)

        # Select delay based on mode
        if conservative_mode:
            # Conservative mode: max 2 URLs per second (0.5-0.7 second delay)
            delay = 0.5 + random.uniform(0, 0.2)
        else:
            # Optimized delay based on rate limit testing (0.2-0.3 second)
            # Testing showed no rate limiting even at faster rates - user-agent appears whitelisted
            delay = 0.2 + random.uniform(0, 0.1)

        time.sleep(delay)

        # Make HTTP request with browser-like headers using persistent session
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none"
        }
        response = _session.get(clean, headers=headers, timeout=30)

        # Handle 202 (Cloudflare queuing) - should be rare with whitelisted IP
        # Only retry once with shorter wait time
        if response.status_code == 202:
            print(f"Got 202 for {clean}, retrying after 2s...")
            time.sleep(2)
            response = _session.get(clean, headers=headers, timeout=30)

        # Check status code
        if response.status_code != 200:
            status_msg = {
                403: "Access denied (403 Forbidden)",
                503: "Service unavailable (503)",
                500: "Server error (500)",
                502: "Bad gateway (502)",
                504: "Gateway timeout (504)"
            }.get(response.status_code, f"HTTP error ({response.status_code})")
            print(f"Scraping failed: {status_msg} for {clean}")
            return None

        # Check for hidden 503 errors in HTML body (Beslist.nl returns 200 with 503 message)
        # This happens when rate limited - we should retry later, not mark as "no products"
        if '503' in response.text or 'Service Unavailable' in response.text:
            print(f"Scraping failed: Hidden 503 (rate limited) for {clean}")
            return None

        # Parse HTML with lxml (2-3x faster than html.parser)
        soup = BeautifulSoup(response.text, 'lxml')

        # Extract h1 title
        h1_element = soup.select_one("h1.productsTitle--tHP5S")
        h1_title = h1_element.get_text(strip=True) if h1_element else "No Title Found"

        # Check if this is a grouped page (contains FacetValueV2)
        is_grouped = "FacetValueV2" in response.text

        # Extract product URLs from plpUrl fields in JavaScript data (Beslist.nl uses JS navigation)
        # Product URLs are in format: "plpUrl":"/p/product-name/40000/ean/"
        product_url_pattern = r'"plpUrl":"(/p/[^"]+/40000/[^"]+/)"'
        all_product_urls = re.findall(product_url_pattern, response.text)

        # URLs are already unique from plpUrl extraction (one per product)
        unique_product_urls = all_product_urls

        # Extract product containers
        product_containers = soup.select("div.product--WiTVr")
        products = []

        for i, container in enumerate(product_containers[:70]):  # Max 70 as in n8n workflow
            # Extract title
            title_element = container.select_one("h2.product_title--eQD3J")
            title = title_element.get_text(strip=True) if title_element else "No Title"

            # Extract description - if not present, use title as fallback
            desc_element = container.select_one("div.productInfo__description--S1odY")
            listview_content = desc_element.get_text(strip=True) if desc_element else title

            # Get URL from regex results by index (URLs are in same order as containers)
            product_url = ""
            if i < len(unique_product_urls):
                product_url = "https://www.beslist.nl" + unique_product_urls[i]

            # Only add if both URL and content are valid
            if is_valid_url(product_url) and listview_content:
                products.append({
                    "title": title,
                    "url": product_url,
                    "listviewContent": listview_content
                })

        return {
            "url": clean,
            "h1_title": h1_title,
            "products": products,
            "is_grouped": is_grouped
        }

    except requests.RequestException as e:
        print(f"Request error for {url}: {str(e)}")
        return None
    except Exception as e:
        print(f"Scraping error for {url}: {str(e)}")
        return None

def sanitize_content(content: str) -> str:
    """
    Sanitize HTML content for SQL insertion:
    - Escape single quotes
    - Decode HTML entities
    """
    if not content:
        return ""

    # Replace HTML entities
    sanitized = (content
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&#039;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&euro;", "€")
        .replace("&copy;", "©")
        .replace("&trade;", "™")
    )

    # Escape single quotes for SQL (double them)
    sanitized = sanitized.replace("'", "''")

    return sanitized
