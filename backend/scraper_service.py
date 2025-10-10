import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import re
import time
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# User agent - Chrome browser to work with whitelisted IP
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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

def scrape_product_page(url: str) -> Optional[Dict]:
    """
    Scrape a product listing page and extract:
    - h1 title
    - list of products (title, url, description)

    Returns None if request fails or statuscode != 200
    """
    try:
        # Clean URL first
        clean = clean_url(url)

        # Add significant delay to avoid rate limiting (5-7 seconds with random jitter)
        delay = 5 + random.uniform(0, 2)
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

        # Handle 202 (Cloudflare queuing) - retry with exponential backoff
        retry_count = 0
        max_retries = 3
        while response.status_code == 202 and retry_count < max_retries:
            retry_count += 1
            wait_time = 5 * (2 ** (retry_count - 1))  # 5s, 10s, 20s
            print(f"Got 202 for {clean}, retry {retry_count}/{max_retries} after {wait_time}s...")
            time.sleep(wait_time)
            response = _session.get(clean, headers=headers, timeout=30)

        # Check status code
        if response.status_code != 200:
            print(f"Non-200 status code {response.status_code} for {clean}")
            return None

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract h1 title
        h1_element = soup.select_one("h1.productsTitle--tHP5S")
        h1_title = h1_element.get_text(strip=True) if h1_element else "No Title Found"

        # Check if this is a grouped page (contains FacetValueV2)
        is_grouped = "FacetValueV2" in response.text

        # Extract product containers
        product_containers = soup.select("div.product--WiTVr")
        products = []

        for container in product_containers[:70]:  # Max 70 as in n8n workflow
            # Extract title
            title_element = container.select_one("h2.product_title--eQD3J")
            title = title_element.get_text(strip=True) if title_element else "No Title"

            # Extract description
            desc_element = container.select_one("div.productInfo__description--S1odY")
            listview_content = desc_element.get_text(strip=True) if desc_element else ""

            # Extract URL from link
            link_element = container.select_one("a[href]")
            product_url = link_element.get("href", "") if link_element else ""

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
