"""Data models for thema ads optimizer."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AdGroupInput:
    """Input data for processing an ad group."""
    customer_id: str
    campaign_name: str
    campaign_id: str
    ad_group_id: str


@dataclass
class ExistingAd:
    """Existing RSA data."""
    resource_name: str
    status: str
    headlines: List[str]
    descriptions: List[str]
    final_urls: List[str]
    path1: str
    path2: str


@dataclass
class CachedData:
    """Prefetched data for a customer."""
    labels: dict  # label_name -> resource_name
    existing_ads: dict  # ad_group_resource -> ExistingAd
    campaigns: dict  # campaign_name -> resource_name


@dataclass
class ProcessingResult:
    """Result of processing an ad group."""
    customer_id: str
    ad_group_id: str
    success: bool
    new_ad_resource: Optional[str] = None
    error: Optional[str] = None
    operations_count: int = 0
