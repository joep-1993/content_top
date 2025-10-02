import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import re

# User agent as specified
USER_AGENT = "n8n-bot-jvs"

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

        # Make HTTP request with custom user agent
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(clean, headers=headers, timeout=30)

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
