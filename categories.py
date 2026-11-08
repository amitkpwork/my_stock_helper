"""Market-cap and sector-style buckets (pure functions, no network)."""
import pandas as pd

# Yahoo Finance sector names -> style. Simplified on purpose; edit to taste.
DEFENSIVE = {"Consumer Defensive", "Healthcare", "Utilities"}
CYCLICAL = {"Consumer Cyclical", "Basic Materials", "Industrials", "Energy", "Real Estate", "Financial Services"}


def style(sector) -> str:
    if not isinstance(sector, str) or not sector:
        return "n/a"
    if sector in DEFENSIVE:
        return "Defensive"
    if sector in CYCLICAL:
        return "Cyclical"
    return "Other"  # e.g. Technology, Communication Services


def cap_bucket(mcap_cr, large_cr: float, mid_cr: float) -> str:
    """mcap_cr is market cap in rupee crore."""
    if mcap_cr is None or pd.isna(mcap_cr) or mcap_cr <= 0:
        return "n/a"
    if mcap_cr >= large_cr:
        return "Large"
    if mcap_cr >= mid_cr:
        return "Mid"
    return "Small"
