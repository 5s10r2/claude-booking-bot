"""
Property match scoring: calculate how well a property matches user preferences.
"""

from typing import Optional


def match_score(
    property_data: dict,
    preferences: dict,
    amenity_weights: Optional[dict] = None,
) -> float:
    """Calculate a 0-100 match score between a property and user preferences.

    Scoring components:
    - Budget match (0-30 pts)
    - Location proximity (0-20 pts via distance if available)
    - Amenity overlap (0-30 pts)
    - Property type match (0-10 pts)
    - Gender match (0-10 pts)
    """
    score = 0.0

    # Budget match (30 pts)
    prop_rent = _parse_number(property_data.get("rent", property_data.get("rent_starts_from", 0)))
    min_budget = _parse_number(preferences.get("min_budget", 0))
    max_budget = _parse_number(preferences.get("max_budget", 100000))

    if prop_rent > 0:
        if min_budget <= prop_rent <= max_budget:
            score += 30
        elif prop_rent < min_budget:
            diff_pct = (min_budget - prop_rent) / max(min_budget, 1)
            score += max(0, 30 - diff_pct * 30)
        else:
            diff_pct = (prop_rent - max_budget) / max(max_budget, 1)
            score += max(0, 30 - diff_pct * 60)

    # Distance score (20 pts)
    distance = property_data.get("distance", property_data.get("distanceBwPropertyAndSearchArea"))
    if distance is not None:
        dist_km = _parse_number(distance) / 1000.0
        if dist_km <= 2:
            score += 20
        elif dist_km <= 5:
            score += max(0, 20 - (dist_km - 2) * 4)
        elif dist_km <= 10:
            score += max(0, 8 - (dist_km - 5))
        # Beyond 10km, 0 points

    # Amenity overlap (30 pts)
    user_amenities = _parse_amenities(preferences.get("amenities", ""))
    prop_amenities = _parse_amenities(
        property_data.get("amenities", property_data.get("commonAmenities", ""))
    )

    if user_amenities:
        overlap = len(user_amenities & prop_amenities)
        score += min(30, (overlap / len(user_amenities)) * 30)
    else:
        score += 15  # No preference = neutral

    # Property type match (10 pts)
    pref_type = preferences.get("property_type", "").lower()
    prop_type = property_data.get("property_type", "").lower()
    if pref_type and prop_type:
        if pref_type in prop_type or prop_type in pref_type:
            score += 10
    else:
        score += 5  # No preference

    # Gender match (10 pts)
    pref_gender = preferences.get("pg_available_for", "").lower()
    prop_gender = property_data.get("pg_available_for", "").lower()
    if pref_gender and prop_gender:
        if pref_gender == "any" or prop_gender == "any" or pref_gender in prop_gender:
            score += 10
    else:
        score += 5

    return round(min(100, max(0, score)), 1)


def indicator(score: float) -> str:
    """Return a visual indicator for a match score."""
    if score >= 80:
        return "Excellent Match"
    elif score >= 60:
        return "Good Match"
    elif score >= 40:
        return "Fair Match"
    return "Low Match"


def _parse_number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = "".join(c for c in value if c.isdigit() or c == ".")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _parse_amenities(value) -> set:
    if isinstance(value, list):
        return {a.strip().lower() for a in value if a.strip()}
    if isinstance(value, str):
        return {a.strip().lower() for a in value.split(",") if a.strip()}
    return set()
