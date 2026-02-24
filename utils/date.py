"""
Date transcription and parsing utility.

Since Claude handles the user's natural language dates (e.g. "next Monday",
"kal", "parso") and passes them to tools, we just need a robust parser
that handles both DD/MM/YYYY and common natural language date strings.
No external LLM call needed — Claude does the heavy lifting.
"""

import re
from datetime import datetime, timedelta

import pytz

IST = pytz.timezone("Asia/Kolkata")

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def transcribe_date(raw_date: str) -> str:
    """Convert a date string to DD/MM/YYYY format.

    Handles:
    - Already formatted: "25/12/2025", "2025-12-25"
    - Relative: "today", "tomorrow", "day after tomorrow"
    - Days from now: "5 days from today"
    - Day of week: "this monday", "next friday"
    - Specific: "25th", "25th march", "3rd of next month"
    - ISO: "2025-03-25"
    """
    query = raw_date.strip().lower()
    now = datetime.now(IST)

    # Already DD/MM/YYYY
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", query):
        return query

    # ISO format YYYY-MM-DD
    iso_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", query)
    if iso_match:
        return f"{iso_match.group(3)}/{iso_match.group(2)}/{iso_match.group(1)}"

    # DD-MM-YYYY
    dash_match = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", query)
    if dash_match:
        return f"{dash_match.group(1)}/{dash_match.group(2)}/{dash_match.group(3)}"

    # "N days from today/now"
    days_match = re.search(r"(\d+)\s+days?\s+from\s+(today|now)", query)
    if days_match:
        target = now + timedelta(days=int(days_match.group(1)))
        return target.strftime("%d/%m/%Y")

    # "in N days"
    in_days_match = re.search(r"in\s+(\d+)\s+days?", query)
    if in_days_match:
        target = now + timedelta(days=int(in_days_match.group(1)))
        return target.strftime("%d/%m/%Y")

    if "today" in query:
        return now.strftime("%d/%m/%Y")

    if "day after tomorrow" in query:
        return (now + timedelta(days=2)).strftime("%d/%m/%Y")

    if "tomorrow" in query:
        return (now + timedelta(days=1)).strftime("%d/%m/%Y")

    # "Nth of current month"
    current_month_match = re.search(r"(\d{1,2})(st|nd|rd|th)\s+of\s+current\s+month", query)
    if current_month_match:
        day = int(current_month_match.group(1))
        return datetime(now.year, now.month, day).strftime("%d/%m/%Y")

    # "next to next month"
    if "next to next month" in query:
        target_month = (now.month + 2 - 1) % 12 + 1
        target_year = now.year + (1 if now.month + 2 > 12 else 0)
        day_match = re.search(r"(\d{1,2})(st|nd|rd|th)", query)
        day = int(day_match.group(1)) if day_match else 1
        return datetime(target_year, target_month, day).strftime("%d/%m/%Y")

    # "next month"
    if "next month" in query:
        target_month = now.month % 12 + 1
        target_year = now.year if target_month != 1 else now.year + 1
        day_match = re.search(r"(\d{1,2})(st|nd|rd|th)", query)
        day = int(day_match.group(1)) if day_match else 1
        return datetime(target_year, target_month, day).strftime("%d/%m/%Y")

    # Specific month name
    for month in _MONTHS:
        if month in query:
            day_match = re.search(r"(\d{1,2})(st|nd|rd|th)?", query)
            day = int(day_match.group(1)) if day_match else 1
            month_num = _MONTHS.index(month) + 1
            year = now.year if month_num >= now.month else now.year + 1
            return datetime(year, month_num, day).strftime("%d/%m/%Y")

    # Day of week
    for day_name in _DAYS:
        if day_name in query:
            target_idx = _DAYS.index(day_name)
            current_idx = now.weekday()
            if "next" in query:
                delta = (target_idx - current_idx + 7) % 7
                delta = delta if delta != 0 else 7
            else:
                delta = (target_idx - current_idx) % 7
                if delta == 0:
                    delta = 0  # "this monday" when today is monday = today
            return (now + timedelta(days=delta)).strftime("%d/%m/%Y")

    # Bare ordinal like "21st" or "4th"
    ordinal_match = re.search(r"(\d{1,2})(st|nd|rd|th)", query)
    if ordinal_match:
        day = int(ordinal_match.group(1))
        return datetime(now.year, now.month, day).strftime("%d/%m/%Y")

    # If nothing matched, return as-is (Claude may have passed DD/MM/YYYY already)
    return raw_date.strip()


def check_if_date_exceeds(date_str: str, days: int) -> bool:
    """Check if a date exceeds N days from now."""
    try:
        target = datetime.strptime(date_str, "%d/%m/%Y")
        now = datetime.now()
        return target > now + timedelta(days=days)
    except ValueError:
        return False


def today_date() -> str:
    return datetime.now(IST).strftime("%d/%m/%Y")


def current_day() -> str:
    return datetime.now(IST).strftime("%A")
