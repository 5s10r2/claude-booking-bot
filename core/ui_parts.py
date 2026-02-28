"""
ui_parts.py — Backend-controlled UI part generator (Generative UI).

Generates structured UI parts (quick_replies, action_buttons) that the
frontend renders via its component registry. Replaces the fragile frontend
quick-replies.js which guessed context from regex on bot text.

Advantages over frontend chip generation:
  - Access to Redis (property names, user prefs, shortlist, memory)
  - Deterministic: no regex guessing — knows the agent + response context
  - Single source of truth: backend decides what UI to show
  - i18n-ready: chips are generated in the user's locale

Part types emitted:
  - quick_replies: { type, chips: [{ label, action, icon? }] }
  - action_buttons: { type, buttons: [{ label, action, style }] }
"""

import re
from core.log import get_logger
from db.redis_store import get_property_info_map, get_preferences

logger = get_logger("core.ui_parts")

# ── i18n labels ──────────────────────────────────────────────────────────

_LABELS = {
    "en": {
        "details": "Details",
        "visit": "Schedule Visit",
        "compare": "Compare",
        "shortlist": "Shortlist",
        "more_options": "More Options",
        "see_rooms": "See Rooms",
        "images": "Photos",
        "commute": "Commute Time",
        "my_bookings": "My Bookings",
        "browse_more": "Browse More",
        "ive_paid": "I've Paid",
        "search_pgs": "Search Properties",
        "diff_area": "Different Area",
        "loved_it": "Loved it!",
        "was_okay": "It was okay",
        "not_for_me": "Not for me",
        "confirm": "Confirm",
        "change_time": "Change Time",
        "reschedule": "Reschedule",
        "cancel_visit": "Cancel Visit",
        "search_here": "Search PGs Here",
        "tell_more": "Tell Me More",
    },
    "hi": {
        "details": "Details",
        "visit": "Visit Book Karo",
        "compare": "Compare Karo",
        "shortlist": "Shortlist Karo",
        "more_options": "Aur Options",
        "see_rooms": "Rooms Dekho",
        "images": "Photos Dekho",
        "commute": "Kitna Door Hai?",
        "my_bookings": "Meri Bookings",
        "browse_more": "Aur Dekho",
        "ive_paid": "Payment Ho Gaya",
        "search_pgs": "PG Search Karo",
        "diff_area": "Alag Area",
        "loved_it": "Bahut Pasand Aaya!",
        "was_okay": "Theek Tha",
        "not_for_me": "Pasand Nahi Aaya",
        "confirm": "Confirm Karo",
        "change_time": "Time Badlo",
        "reschedule": "Reschedule Karo",
        "cancel_visit": "Visit Cancel",
        "search_here": "Yahan PG Dhundho",
        "tell_more": "Aur Batao",
    },
}


def _t(key: str, locale: str) -> str:
    """Get localized label. Falls back to English."""
    return _LABELS.get(locale, _LABELS["en"]).get(key, _LABELS["en"].get(key, key))


# ── Property name extraction (mirrors frontend logic) ────────────────────

def _extract_listed_properties(text: str) -> list[dict]:
    """Extract numbered properties from search-result listings.
    Returns list of { num: int, name: str }.
    """
    props = []
    seen = set()

    # Bold format: **1. Name** or **1. Name — …**
    for m in re.finditer(r"\*\*(\d+)\.\s+([^*\n]+?)\*\*", text):
        num = int(m.group(1))
        if num not in seen:
            seen.add(num)
            name = re.sub(r"\s*[—–\-|]\s*$", "", m.group(2)).strip()
            props.append({"num": num, "name": name})

    if props:
        return props

    # H3 format: ### 1. Name or ### 🏠 1. Name
    for m in re.finditer(r"^#{1,3}\s+(?:[^\d\n]*?)(\d+)\.\s+(.+?)$", text, re.MULTILINE):
        num = int(m.group(1))
        if num not in seen:
            seen.add(num)
            name = re.sub(r"\s*[—–\-|]\s*$", "", m.group(2)).strip()
            props.append({"num": num, "name": name})

    return props


def _extract_single_name(text: str) -> str | None:
    """Extract a single property name from detail/commute/shortlist responses."""
    # 'Property Name' in single quotes
    m = re.search(r"'([^'\n]{3,50})'", text)
    if m:
        return m.group(1).strip()
    # **Property Name** — first bold match (skip numbered ones)
    m = re.search(r"\*\*([^*\d][^*\n]{2,40})\*\*", text)
    if m:
        return re.sub(r"\s*[—–\-|:]\s*$", "", m.group(1)).strip()
    return None


def _enrich_with_redis_names(props: list[dict], user_id: str) -> list[dict]:
    """If regex extraction missed names, try to fill from Redis property_info_map."""
    if not props or all(p.get("name") for p in props):
        return props

    try:
        info_map = get_property_info_map(user_id)
        if not info_map:
            return props
        for i, prop in enumerate(props):
            if not prop.get("name") and i < len(info_map):
                prop["name"] = info_map[i].get("property_name", "")
    except Exception:
        pass
    return props


# ── Context detection flags ──────────────────────────────────────────────

def _detect_context(text: str, agent: str) -> dict:
    """Detect what kind of response this is. Returns context flags."""
    lower = text.lower()

    # Multi-property detection
    has_multi_bold = bool(re.search(r"\*\*[23456789]\.\s", text))
    has_multi_h3 = bool(re.search(r"^#{1,3}\s+[^\d\n]*[23456789]\.\s", text, re.MULTILINE))
    has_one_bold = bool(re.search(r"\*\*1\.\s", text))
    has_one_h3 = bool(re.search(r"^#{1,3}\s+[^\d\n]*1\.\s", text, re.MULTILINE))

    has_multi = has_multi_bold or has_multi_h3
    has_one = (has_one_bold or has_one_h3) and not has_multi

    return {
        "has_multi": has_multi,
        "has_one": has_one,
        "is_qualifying": (
            "quick —" in lower or "quick—" in lower
            or "must-haves from" in lower
            or "has some great options" in lower
            or "just share what matters" in lower
            or ("boys" in lower and "girls" in lower and "monthly budget" in lower)
        ),
        "is_comparison": (
            "comparison" in lower or "⚖" in lower
            or ("compare" in lower and not has_multi)
        ),
        "is_commute": (
            "commute" in lower or "🚗" in lower or "🚇" in lower
            or "by car" in lower or "by metro" in lower
        ),
        "is_visit_feedback": (
            "how was your visit" in lower
            or "how did the visit go" in lower
            or "how did it go" in lower
        ),
        "is_shortlisted": "shortlist" in lower or "saved" in lower,
        "is_area_info": (
            "neighborhood" in lower or "from what i know" in lower
            or ("area" in lower and "search" in lower)
        ),
        "is_property_detail": (
            "rent starts from" in lower or "here's what we have" in lower
            or "type: flat" in lower or "type: pg" in lower
            or "type: hostel" in lower or "type: co-living" in lower
            or ("₹" in lower and "/month" in lower and "📍" in lower)
        ),
        "is_confirmed": (
            "confirmed" in lower or "scheduled" in lower or "booked" in lower
        ),
        "is_payment": (
            "payment" in lower or "token" in lower
            or ("link" in lower and ("pay" in lower or "₹" in lower))
        ),
    }


# ── Chip generators per context ──────────────────────────────────────────

def _broker_chips(text: str, ctx: dict, user_id: str, locale: str) -> list[dict]:
    """Generate chips for broker agent responses."""
    chips = []
    props = _extract_listed_properties(text)
    props = _enrich_with_redis_names(props, user_id)

    if ctx["is_qualifying"]:
        # Qualifying question — no chips, let user type freely
        return []

    if ctx["is_visit_feedback"]:
        chips = [
            {"label": f"❤️ {_t('loved_it', locale)}", "action": "I loved it! I want to book this property", "icon": "heart"},
            {"label": f"🤔 {_t('was_okay', locale)}", "action": "It was okay, but I'm not sure yet", "icon": "think"},
            {"label": f"👎 {_t('not_for_me', locale)}", "action": "Not for me. The property didn't match my expectations", "icon": "thumbs_down"},
        ]
        return chips

    if ctx["is_comparison"] and len(props) >= 2:
        # After comparison — offer visit/shortlist for specific properties
        chips = [
            {"label": f"📅 Visit {props[0]['name'][:20]}", "action": f"Schedule a visit for {props[0]['name']}", "icon": "calendar"},
            {"label": f"📅 Visit {props[1]['name'][:20]}", "action": f"Schedule a visit for {props[1]['name']}", "icon": "calendar"},
            {"label": f"🔍 {_t('more_options', locale)}", "action": "Show me more options", "icon": "search"},
        ]
        return chips

    if ctx["has_multi"] and len(props) >= 2:
        # Multiple search results — smart chips with property names
        p1, p2 = props[0], props[1]
        chips = [
            {"label": f"📋 #{p1['num']} {_t('details', locale)}", "action": f"Tell me more about {p1['name']}", "icon": "info"},
            {"label": f"📅 #{p1['num']} {_t('visit', locale)}", "action": f"Schedule a visit for {p1['name']}", "icon": "calendar"},
            {"label": f"⚖️ #{p1['num']} vs #{p2['num']}", "action": f"Compare {p1['name']} and {p2['name']}", "icon": "compare"},
        ]
        if len(props) >= 3:
            chips.append({"label": f"📋 #{props[2]['num']} {_t('details', locale)}", "action": f"Tell me more about {props[2]['name']}", "icon": "info"})
        else:
            chips.append({"label": f"⭐ {_t('shortlist', locale)}", "action": f"Shortlist {p1['name']}", "icon": "star"})
        return chips

    if ctx["has_multi"]:
        # Fallback generic multi-property (name extraction failed)
        chips = [
            {"label": f"📋 {_t('details', locale)}", "action": "Tell me more about the first property", "icon": "info"},
            {"label": f"📅 {_t('visit', locale)}", "action": "Schedule a visit", "icon": "calendar"},
            {"label": f"⭐ {_t('shortlist', locale)}", "action": "Shortlist the first property", "icon": "star"},
            {"label": f"⚖️ {_t('compare', locale)}", "action": "Compare the top 2 properties", "icon": "compare"},
        ]
        return chips

    if ctx["is_commute"]:
        name = _extract_single_name(text)
        chips = [
            {"label": f"📅 {_t('visit', locale)}", "action": f"Schedule a visit for {name}" if name else "Schedule a visit", "icon": "calendar"},
            {"label": f"⭐ {_t('shortlist', locale)}", "action": f"Shortlist {name}" if name else "Shortlist this property", "icon": "star"},
            {"label": f"🔍 {_t('more_options', locale)}", "action": "Show me more options", "icon": "search"},
        ]
        return chips

    if ctx["has_one"]:
        name = props[0]["name"] if props else None
        chips = [
            {"label": f"📅 {_t('visit', locale)}", "action": f"Schedule a visit for {name}" if name else "Schedule a visit", "icon": "calendar"},
            {"label": f"⭐ {_t('shortlist', locale)}", "action": f"Shortlist {name}" if name else "Shortlist this property", "icon": "star"},
            {"label": f"🛏️ {_t('see_rooms', locale)}", "action": f"Show me room options for {name}" if name else "Show me room options and pricing", "icon": "bed"},
            {"label": f"📷 {_t('images', locale)}", "action": f"Show me photos of {name}" if name else "Show me photos", "icon": "camera"},
        ]
        return chips

    if ctx["is_shortlisted"]:
        name = _extract_single_name(text)
        chips = [
            {"label": f"📅 {_t('visit', locale)}", "action": f"Schedule a visit for {name}" if name else "Schedule a visit", "icon": "calendar"},
            {"label": f"🔍 {_t('more_options', locale)}", "action": "Show me more properties", "icon": "search"},
        ]
        return chips

    if ctx["is_area_info"]:
        chips = [
            {"label": f"🔍 {_t('search_here', locale)}", "action": "Search for PGs here", "icon": "search"},
            {"label": f"ℹ️ {_t('tell_more', locale)}", "action": "Tell me more about the area", "icon": "info"},
        ]
        return chips

    if ctx["is_property_detail"]:
        name = _extract_single_name(text)
        chips = [
            {"label": f"📅 {_t('visit', locale)}", "action": f"Schedule a visit for {name}" if name else "Schedule a visit", "icon": "calendar"},
            {"label": f"⭐ {_t('shortlist', locale)}", "action": f"Shortlist {name}" if name else "Shortlist this property", "icon": "star"},
            {"label": f"🛏️ {_t('see_rooms', locale)}", "action": f"Show me room options for {name}" if name else "Show me room options and pricing", "icon": "bed"},
            {"label": f"🚗 {_t('commute', locale)}", "action": f"How far is {name} from my office?" if name else "How far is this from my office?", "icon": "car"},
        ]
        return chips

    # Default broker chips
    chips = [
        {"label": f"🔍 {_t('search_pgs', locale)}", "action": "Show me properties in Mumbai", "icon": "search"},
        {"label": f"📍 {_t('diff_area', locale)}", "action": "Search in a different area", "icon": "location"},
    ]
    return chips


def _booking_chips(text: str, ctx: dict, locale: str) -> list[dict]:
    """Generate chips for booking agent responses."""
    chips = []

    if ctx["is_confirmed"]:
        chips.append({"label": f"📋 {_t('my_bookings', locale)}", "action": "Show my upcoming visits", "icon": "list"})
        chips.append({"label": f"🔍 {_t('browse_more', locale)}", "action": "Show me more properties", "icon": "search"})

    if ctx["is_payment"]:
        chips.append({"label": f"✅ {_t('ive_paid', locale)}", "action": "I have completed the payment", "icon": "check"})

    return chips


def _profile_chips(locale: str) -> list[dict]:
    """Generate chips for profile agent responses."""
    return [
        {"label": f"🔍 {_t('search_pgs', locale)}", "action": "Show me properties in Mumbai", "icon": "search"},
    ]


def _default_chips(text: str, ctx: dict, locale: str) -> list[dict]:
    """Generate chips for default agent responses."""
    # Default/greeting — offer search
    return [
        {"label": f"🔍 {_t('search_pgs', locale)}", "action": "Show me properties in Mumbai", "icon": "search"},
    ]


# ── Main entry point ─────────────────────────────────────────────────────

def generate_ui_parts(
    response_text: str,
    agent_name: str,
    user_id: str,
    locale: str = "en",
) -> list[dict]:
    """Generate UI parts to append to the parts[] array.

    Called after the agent produces its text response. Analyzes the response
    + context to produce structured UI parts the frontend renders.

    Returns list of part dicts (may be empty).
    """
    if not response_text or not response_text.strip():
        return []

    # Normalize locale
    locale = locale if locale in _LABELS else "en"

    # Detect response context
    ctx = _detect_context(response_text, agent_name)

    # Generate chips based on agent
    chips = []
    if agent_name == "broker":
        chips = _broker_chips(response_text, ctx, user_id, locale)
    elif agent_name == "booking":
        chips = _booking_chips(response_text, ctx, locale)
    elif agent_name == "profile":
        chips = _profile_chips(locale)
    elif agent_name == "default":
        chips = _default_chips(response_text, ctx, locale)

    parts = []
    if chips:
        parts.append({"type": "quick_replies", "chips": chips})

    return parts
