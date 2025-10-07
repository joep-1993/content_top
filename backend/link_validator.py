import re
import requests
from typing import List, Dict, Tuple
from bs4 import BeautifulSoup

# Base domain for relative URLs
BASE_DOMAIN = "https://www.beslist.nl"

# Status codes that indicate broken links
BROKEN_STATUS_CODES = [301, 404]

def extract_hyperlinks_from_content(content: str) -> List[str]:
    """
    Extract all href URLs from HTML content.
    Returns list of relative URLs found in <a href="..."> tags.
    """
    soup = BeautifulSoup(content, 'html.parser')
    links = []

    for link in soup.find_all('a', href=True):
        href = link['href']
        # Only include relative URLs (starting with /)
        if href.startswith('/'):
            links.append(href)

    return links

def check_url_status(url: str) -> Tuple[int, str]:
    """
    Check the HTTP status code of a URL.
    Returns tuple of (status_code, status_text).
    """
    try:
        full_url = BASE_DOMAIN + url if url.startswith('/') else url
        response = requests.head(full_url, allow_redirects=False, timeout=10)
        return (response.status_code, response.reason)
    except requests.exceptions.RequestException as e:
        # Return 0 for network errors
        return (0, str(e))

def validate_content_links(content: str) -> Dict:
    """
    Validate all hyperlinks in content.
    Returns dict with validation results:
    {
        'total_links': int,
        'broken_links': List[Dict],
        'valid_links': int,
        'has_broken_links': bool
    }
    """
    if not content:
        return {
            'total_links': 0,
            'broken_links': [],
            'valid_links': 0,
            'has_broken_links': False
        }

    # Extract all links
    links = extract_hyperlinks_from_content(content)

    if not links:
        return {
            'total_links': 0,
            'broken_links': [],
            'valid_links': 0,
            'has_broken_links': False
        }

    broken_links = []
    valid_count = 0

    # Check each unique link
    unique_links = list(set(links))

    for link in unique_links:
        status_code, status_text = check_url_status(link)

        if status_code in BROKEN_STATUS_CODES:
            broken_links.append({
                'url': link,
                'full_url': BASE_DOMAIN + link,
                'status_code': status_code,
                'status_text': status_text
            })
        elif status_code == 200:
            valid_count += 1

    return {
        'total_links': len(unique_links),
        'broken_links': broken_links,
        'valid_links': valid_count,
        'has_broken_links': len(broken_links) > 0
    }

def validate_content_links_batch(contents: List[Tuple[str, str]]) -> List[Dict]:
    """
    Validate hyperlinks for multiple content items.
    Args:
        contents: List of tuples (url, content)
    Returns:
        List of validation results with URL context
    """
    results = []

    for url, content in contents:
        validation = validate_content_links(content)
        validation['content_url'] = url
        results.append(validation)

    return results

# Test function
if __name__ == "__main__":
    # Test with sample content
    test_content = '''
    <p>Check out these products:</p>
    <a href="/p/product-1">Product 1</a>
    <a href="/p/product-2">Product 2</a>
    <a href="/p/invalid-product">Invalid Product</a>
    '''

    result = validate_content_links(test_content)
    print(f"Validation result: {result}")
