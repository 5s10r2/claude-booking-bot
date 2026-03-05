"""
Central tool registry: maps tool names to Anthropic schemas + handler functions.
Each agent picks the tools it needs by name.
"""

from typing import Callable
from config import settings

# Handler imports (lazy — registered at startup)
_TOOL_HANDLERS: dict[str, Callable] = {}
_TOOL_SCHEMAS: dict[str, dict] = {}

_KYC_TOOLS: list[str] = ["fetch_kyc_status", "initiate_kyc", "verify_kyc"]
_BOOKING_BASE_TOOLS: list[str] = [
    "save_phone_number",
    "save_visit_time",
    "save_call_time",
    "create_payment_link",
    "verify_payment",
    "check_reserve_bed",
    "reserve_bed",
    "cancel_booking",
    "reschedule_booking",
]

_AGENT_TOOLS: dict[str, list[str]] = {
    "default": ["brand_info", "web_search"],
    "broker": [
        "save_preferences",
        "search_properties",
        "fetch_property_details",
        "shortlist_property",
        "fetch_property_images",
        "fetch_landmarks",
        "estimate_commute",
        "fetch_nearby_places",
        "fetch_room_details",
        "fetch_properties_by_query",
        "compare_properties",
        "web_search",
    ],
    "booking": _BOOKING_BASE_TOOLS + (_KYC_TOOLS if settings.KYC_ENABLED else []) + ["save_preferences", "web_search"],
    "profile": [
        "fetch_profile_details",
        "get_scheduled_events",
        "get_shortlisted_properties",
        "web_search",
    ],
}


def register_tool(name: str, schema: dict, handler: Callable) -> None:
    _TOOL_SCHEMAS[name] = schema
    _TOOL_HANDLERS[name] = handler


def get_schemas_for_agent(agent_name: str) -> list[dict]:
    tool_names = _AGENT_TOOLS.get(agent_name, [])
    return [_TOOL_SCHEMAS[n] for n in tool_names if n in _TOOL_SCHEMAS]


def get_handlers_for_agent(agent_name: str) -> dict[str, Callable]:
    tool_names = _AGENT_TOOLS.get(agent_name, [])
    return {n: _TOOL_HANDLERS[n] for n in tool_names if n in _TOOL_HANDLERS}


def get_all_handlers() -> dict[str, Callable]:
    return dict(_TOOL_HANDLERS)


# ---------------------------------------------------------------------------
# Tool schema definitions (Anthropic format)
# ---------------------------------------------------------------------------

SCHEMAS = {
    "brand_info": {
        "name": "brand_info",
        "description": (
            "Fetch brand information, coverage areas, rent ranges, amenities, and property types for the current platform. "
            "Use ONLY when the user explicitly asks about the brand, its services, cities covered, or what facilities are offered. "
            "Do NOT call for general greetings or property searches — this is for brand-level FAQ only. "
            "Returns cached data (24h TTL) so repeat calls are instant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "save_preferences": {
        "name": "save_preferences",
        "description": (
            "Save or update the user's property search preferences to Redis. MUST be called before search_properties — the search reads from saved preferences. "
            "Idempotent: safe to call multiple times; new values merge with existing preferences (unchanged fields are preserved). "
            "At minimum, pass 'location' (city or area+city). Pass all known filters to get the best search results. "
            "Also use this to record deal_breakers when a user rejects 2+ properties for the same reason (e.g., 'no AC', 'far from metro')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Area/locality AND city, e.g. 'Koramangala, Bangalore'. City alone is also valid."},
                "city": {"type": "string", "description": "City name, e.g. 'Bangalore'. Pass separately even if included in location."},
                "min_budget": {"type": "number", "description": "Minimum monthly rent budget in INR. Omit if user didn't specify a floor."},
                "max_budget": {"type": "number", "description": "Maximum monthly rent budget in INR. Default to 100000 if user didn't specify."},
                "move_in_date": {"type": "string", "description": "Preferred move-in date, pass as user stated it (e.g. 'next week', '1st March')"},
                "property_type": {"type": "string", "description": "One of: PG Rooms, Co-Living, Hostel, or null for flats/apartments"},
                "unit_types_available": {"type": "string", "description": "Comma-separated unit types: ROOM, 1RK, 1BHK, 2BHK, 3BHK, 4BHK, 5BHK. Map user language: 'PG'→ROOM, 'studio'→1RK,2RK, 'flat'→1BHK,2BHK,3BHK"},
                "pg_available_for": {"type": "string", "description": "Gender filter: 'All Girls', 'All Boys', or 'Any'. Map user language: 'for girls/ladies/women'→All Girls"},
                "sharing_types_enabled": {"type": "string", "description": "Room sharing count: '1' for single, '2' for double, '3' for triple. Map: 'private room'→1, 'sharing'→2,3"},
                "amenities": {"type": "string", "description": "Comma-separated full amenity list for backward compatibility. Always pass combined must_have + nice_to_have here."},
                "must_have_amenities": {"type": "string", "description": "Amenities the user MUST have (said 'need', 'require', 'must have', 'essential'). E.g. 'AC, WiFi'. Affects match scoring with heavy penalty if missing."},
                "nice_to_have_amenities": {"type": "string", "description": "Amenities the user PREFERS but aren't essential (said 'prefer', 'nice to have', 'if possible'). E.g. 'gym, parking'. Gives bonus score if present."},
                "deal_breakers": {"type": "string", "description": "Patterns from user rejecting 2+ properties for the same reason. E.g. 'no AC, far from metro'. Heavily penalizes matching properties in future searches. Be specific."},
                "description": {"type": "string", "description": "Free-text description of what the user wants, useful for context"},
                "commute_from": {"type": "string", "description": "Office, college, or landmark the user commutes to. E.g. 'Reliance Corporate Park, Navi Mumbai'. Enables commute-aware search and estimate_commute calls."},
            },
            "required": ["location"],
        },
    },
    "search_properties": {
        "name": "search_properties",
        "description": (
            "Search for properties using the user's saved preferences (from save_preferences). ALWAYS call save_preferences first — this tool reads from those saved values. "
            "Returns up to 20 properties sorted by match score, each with: name, location, rent, gender, images, match_score, and distance from search area. "
            "Show 5 results at a time with continuous numbering across batches. Set radius_flag=true to expand search by 5km when initial results are insufficient or user asks for 'more options'. "
            "If results include a [RELAXED:...] prefix, it means exact matches weren't found and criteria were automatically widened — present these confidently."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "radius_flag": {"type": "boolean", "description": "Set true to expand search radius by 5km. Use when: all results already shown and user wants more, or initial results are too few."},
            },
            "required": [],
        },
    },
    "fetch_property_details": {
        "name": "fetch_property_details",
        "description": (
            "Get comprehensive details for a specific property: amenities (food, services, common area), house rules, rent breakdown, room types, images, address, and microsite URL. "
            "Use when user asks 'tell me more about X', 'details of X', or wants to know amenities/rules/rent for a specific property. "
            "The property_name must match exactly as shown in search results (case-sensitive). "
            "If the API returns an error or empty data, offer to schedule a call instead of saying 'data didn't load'. Do NOT use for listing multiple properties — use search_properties for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name as shown in search results. Must match precisely — partial or modified names will fail."},
            },
            "required": ["property_name"],
        },
    },
    "shortlist_property": {
        "name": "shortlist_property",
        "description": (
            "Add a property to the user's persistent shortlist (stored in Redis, survives across sessions). "
            "Use when user says 'shortlist', 'save this', 'add to favorites', 'bookmark', or 'I like this one'. "
            "Also updates the user's cross-session memory with the shortlisted property for returning-user personalization. "
            "The property must have appeared in a previous search — property_name must be exact. Returns confirmation message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results to add to shortlist"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_property_images": {
        "name": "fetch_property_images",
        "description": (
            "Fetch all available image URLs for a specific property. Use when user asks for 'photos', 'images', 'pictures', or 'what does it look like'. "
            "Returns an array of image URLs that can be displayed as a gallery or carousel. "
            "The property_name must be exact from search results. If no images are available, the result will indicate so — suggest scheduling a video tour instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_landmarks": {
        "name": "fetch_landmarks",
        "description": (
            "Calculate driving distance and time from a property to any named landmark using OSRM routing. "
            "Use for simple distance queries like 'how far is X from the airport?' or 'distance to Y station'. "
            "For commute questions (office, college, daily travel), PREFER estimate_commute instead — it returns both driving AND transit routes. "
            "Falls back to haversine (straight-line) distance if routing fails. Returns distance in km and estimated driving time in minutes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "landmark_name": {"type": "string", "description": "Name of the landmark, station, airport, or place to measure distance to"},
                "property_name": {"type": "string", "description": "Exact property name from search results"},
            },
            "required": ["landmark_name", "property_name"],
        },
    },
    "estimate_commute": {
        "name": "estimate_commute",
        "description": (
            "Estimate commute time from a property to a destination via BOTH car and public transit (metro/train). "
            "Returns: driving time, AND a full transit breakdown with walking segments + metro/train ride (line name, stop count, station names). "
            "PREFERRED over fetch_landmarks for any commute-related question — 'how do I get to office from X?', 'commute time to college'. "
            "Transit data covers Mumbai, Bangalore, Delhi, and Pune metro/rail networks. City is auto-detected from property data but can be overridden."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results"},
                "destination": {"type": "string", "description": "Destination: office name, college, area, or full address. E.g. 'Infosys Electronic City', 'IIT Bombay'"},
                "city": {"type": "string", "description": "City name (optional — auto-detected from property data). Pass only to override auto-detection."},
            },
            "required": ["property_name", "destination"],
        },
    },
    "fetch_nearby_places": {
        "name": "fetch_nearby_places",
        "description": (
            "Find nearby points of interest around a property using OpenStreetMap data. "
            "Excellent for the 'compensation pattern': when a property lacks an amenity (no gym, no restaurant), search nearby to show alternatives within walking distance. "
            "Also use proactively after showing property details to strengthen the value proposition — 'hospitals nearby', 'metro stations', 'restaurants'. "
            "Returns place name, type, and distance. Default radius is 5000m. Supported amenity types: restaurant, hospital, school, gym, cafe, pharmacy, metro, park, supermarket, bank, atm."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results"},
                "radius": {"type": "integer", "description": "Search radius in meters. Default 5000. Use 1000-2000 for walking distance, 5000 for general area."},
                "amenity": {"type": "string", "description": "Type of place to search for: restaurant, hospital, school, gym, cafe, pharmacy, metro, park, supermarket, bank, atm. Omit to get a mix of all types."},
            },
            "required": ["property_name"],
        },
    },
    "fetch_room_details": {
        "name": "fetch_room_details",
        "description": (
            "Get detailed room-level information for a property: room types (single/double/triple), sharing configurations, per-bed pricing, and bed availability counts. "
            "Use when user asks 'what rooms are available?', 'how much for a single room?', 'any beds left?', or before booking to check availability. "
            "Low beds_available (1-3) is a scarcity signal worth mentioning to the user. "
            "The property_name must be exact from search results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_properties_by_query": {
        "name": "fetch_properties_by_query",
        "description": (
            "Look up properties by name or text query across all brand properties. "
            "Use when user mentions a specific property by name that isn't in the current search results, or when you need to find a property the user visited/discussed in a previous session. "
            "Do NOT use for general property search — use search_properties for that. This is a name/text lookup, not a filtered search. "
            "Returns basic property info: name, location, rent, type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Property name or partial name to look up. E.g. 'Stanza Living', 'Zolo'"},
            },
            "required": ["query"],
        },
    },
    "compare_properties": {
        "name": "compare_properties",
        "description": (
            "Compare 2-3 properties side-by-side in a single call. Fetches details AND room data for all properties in parallel, then returns a structured comparison table with match scores and a recommendation. "
            "Use when user says 'compare', 'which is better', 'X vs Y', or is torn between options. "
            "After comparison, combine with estimate_commute and fetch_nearby_places on the recommended property to build a compelling case. "
            "Maximum 3 properties per comparison. Property names must be comma-separated and exact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_names": {
                    "type": "string",
                    "description": "Comma-separated exact property names (2-3). E.g. 'Stanza Living HSR, Zolo Stays Koramangala'",
                },
            },
            "required": ["property_names"],
        },
    },
    "web_search": {
        "name": "web_search",
        "description": (
            "Search the web for real-time market data, area intelligence, brand reviews, or general knowledge that property tools cannot answer. "
            "Use for: rent market trends, neighborhood safety/vibe, connectivity info, brand reputation, or any factual question outside your property database. "
            "Results are cached in Redis — repeat queries return instantly. Maximum 3 web searches per conversation, so use them on high-value questions. "
            "NEVER say 'I don't have web access' — you DO. Be specific in queries: 'average PG rent in Andheri West Mumbai 2025' beats 'rent Andheri'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Specific search query. Include city, area, year for best results. E.g. 'average rent for PG in Koramangala Bangalore 2025'",
                },
                "category": {
                    "type": "string",
                    "description": "'area' for neighborhood/rent/connectivity data, 'brand' for reviews/reputation, 'general' for anything else",
                    "enum": ["area", "brand", "general"],
                },
                "context": {
                    "type": "string",
                    "description": "Brief context for why you need this search — improves result relevance. E.g. 'user asking about safety in this area'",
                },
            },
            "required": ["query", "category"],
        },
    },
    "save_phone_number": {
        "name": "save_phone_number",
        "description": (
            "Save the user's mobile number to Redis for use in payment links, visit scheduling, lead creation, and KYC. "
            "Call this when the user provides their phone number, or when another tool (create_payment_link, save_visit_time) indicates a phone number is required. "
            "Accepts 10-digit Indian numbers with or without +91 prefix. Validates format before saving. "
            "This is a prerequisite for most booking operations — if a tool returns 'phone number needed', prompt the user and call this first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "10-digit Indian mobile number, with or without +91 prefix. E.g. '9876543210' or '+919876543210'",
                },
            },
            "required": ["phone_number"],
        },
    },
    "save_visit_time": {
        "name": "save_visit_time",
        "description": (
            "Schedule a physical property visit. Available slots: 9 AM to 5 PM, 30-minute intervals, within the next 7 days only. "
            "Also creates an external lead in the Rentok CRM system. Requires the user's phone number to be saved first (via save_phone_number). "
            "Pass visit_type as 'Physical visit'. If the slot is unavailable, the result will indicate so — suggest 2-3 alternative times. "
            "After scheduling, proactively ask if the user also wants to reserve a bed/room."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results"},
                "visit_date": {"type": "string", "description": "Visit date as stated by user. E.g. 'tomorrow', 'March 10', 'next Monday'"},
                "visit_time": {"type": "string", "description": "Visit time as stated by user. E.g. '2 PM', '10:30 AM', 'morning'"},
                "visit_type": {"type": "string", "description": "Always pass 'Physical visit' for this tool"},
            },
            "required": ["property_name", "visit_date", "visit_time"],
        },
    },
    "save_call_time": {
        "name": "save_call_time",
        "description": (
            "Schedule a phone call or video tour with a property. Available slots: 10 AM to 9 PM, within the next 7 days. "
            "Use when user prefers a remote interaction before visiting in person. The visit_type must be either 'Phone Call' or 'Video Tour'. "
            "If the slot is unavailable, suggest alternative times. After scheduling, proactively ask if they'd also like to reserve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results"},
                "visit_date": {"type": "string", "description": "Date as stated by user. E.g. 'tomorrow', 'Friday'"},
                "visit_time": {"type": "string", "description": "Time as stated by user. E.g. '3 PM', 'evening'"},
                "visit_type": {"type": "string", "description": "Must be either 'Phone Call' or 'Video Tour'"},
            },
            "required": ["property_name", "visit_date", "visit_time", "visit_type"],
        },
    },
    "create_payment_link": {
        "name": "create_payment_link",
        "description": (
            "Generate a Rentok payment link for the property's token amount to reserve a bed/room. "
            "Requires the user's phone number (saved via save_phone_number). If phone is missing, the result will say so — ask the user for their number first. "
            "Returns a payment URL (pay.rentok.com) and the token amount in INR. The token amount is set by the property and is fully adjustable against rent. "
            "After sharing the link, STOP and wait for the user to confirm payment before calling verify_payment. A 24h follow-up reminder is automatically scheduled."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name from search results"},
            },
            "required": ["property_name"],
        },
    },
    "verify_payment": {
        "name": "verify_payment",
        "description": (
            "Verify and record a completed payment for a property reservation. Call ONLY after the user confirms they've completed the payment via the payment link. "
            "Checks payment status, records it in the backend, and updates the lead status to 'Token' in the CRM. "
            "Takes no parameters — reads from the pending payment info stored when create_payment_link was called. "
            "If payment hasn't been received yet, re-share the payment link. If verified, proceed to reserve_bed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "check_reserve_bed": {
        "name": "check_reserve_bed",
        "description": (
            "Check if the user already has a bed reserved at a specific property. ALWAYS call this FIRST in the reservation flow, before payment or KYC. "
            "Returns success=true if already reserved (no further action needed), success=false if not reserved (proceed with payment flow). "
            "Prevents duplicate reservations. If already reserved, inform the user and offer to schedule a visit or help with another property."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name to check reservation status for"},
            },
            "required": ["property_name"],
        },
    },
    "reserve_bed": {
        "name": "reserve_bed",
        "description": (
            "Reserve a bed/room at a property. This is the FINAL step in the booking flow — call ONLY after payment has been verified (via verify_payment). "
            "If KYC is enabled, KYC must also be completed before this step. Never skip the payment step. "
            "This action is consequential — confirm the property name with the user before calling. "
            "Returns confirmation with reservation details on success."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name to reserve a bed at"},
            },
            "required": ["property_name"],
        },
    },
    "cancel_booking": {
        "name": "cancel_booking",
        "description": (
            "Cancel an existing visit, call, video tour, or reservation for a property. "
            "Use when user says 'cancel my visit', 'I don't want to go', 'cancel the booking'. "
            "Confirm the property name with the user before calling — cancellation cannot be undone easily. "
            "Returns success/failure status. On success, suggest rescheduling or exploring other properties."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name whose booking should be cancelled"},
            },
            "required": ["property_name"],
        },
    },
    "reschedule_booking": {
        "name": "reschedule_booking",
        "description": (
            "Reschedule an existing visit, call, or video tour to a new date and time. "
            "Use when user says 'reschedule', 'change the time', 'move my visit to another day'. "
            "Requires at least the property_name. If new date/time not provided, ask the user before calling. "
            "If the new slot is unavailable, suggest 2-3 alternatives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name of the booking to reschedule"},
                "visit_date": {"type": "string", "description": "New date for the visit/call. E.g. 'Thursday', 'March 15'"},
                "visit_time": {"type": "string", "description": "New time for the visit/call. E.g. '4 PM', 'afternoon'"},
                "visit_type": {"type": "string", "description": "'Physical visit', 'Phone Call', or 'Video Tour'. Pass the same type as the original booking."},
            },
            "required": ["property_name"],
        },
    },
    "fetch_kyc_status": {
        "name": "fetch_kyc_status",
        "description": (
            "Check whether the user has completed KYC (Aadhaar identity verification). "
            "Call at the start of the reservation flow to determine if KYC step can be skipped. "
            "Returns verified=true if KYC is complete, verified=false if not. "
            "If not verified, proceed to initiate_kyc. If verified, skip directly to payment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "initiate_kyc": {
        "name": "initiate_kyc",
        "description": (
            "Start the Aadhaar KYC process by submitting the user's 12-digit Aadhaar number. "
            "Sends an OTP to the phone number registered with Aadhaar (not necessarily the number saved with us). "
            "If the result says a mobile number is needed, ask the user for their phone and call save_phone_number first, then retry. "
            "After success, STOP and wait for the user to provide the OTP before calling verify_kyc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "aadhar_number": {"type": "string", "description": "User's 12-digit Aadhaar number. Validate length before calling."},
            },
            "required": ["aadhar_number"],
        },
    },
    "verify_kyc": {
        "name": "verify_kyc",
        "description": (
            "Complete the KYC process by verifying the OTP that was sent to the user's Aadhaar-registered phone. "
            "Call ONLY after initiate_kyc succeeded and the user has provided their OTP. "
            "Returns verified=true on success (proceed to payment), or failed=true if OTP is wrong (ask user to re-enter or request a new OTP via initiate_kyc)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "otp": {"type": "string", "description": "The OTP code the user received on their phone"},
            },
            "required": ["otp"],
        },
    },
    "fetch_profile_details": {
        "name": "fetch_profile_details",
        "description": (
            "Fetch the user's saved profile: search preferences (location, budget, property type, amenities, commute_from), personal info, and account details. "
            "Use when user asks 'what are my preferences?', 'show my profile', 'what did I search for?'. "
            "Returns all saved preferences in a structured format. If no preferences are saved, the result will be empty — tell the user they can set preferences by describing what they're looking for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_scheduled_events": {
        "name": "get_scheduled_events",
        "description": (
            "Retrieve all scheduled visits, calls, video tours, and active reservations for the user. "
            "Use when user asks 'what visits do I have?', 'my bookings', 'upcoming events', 'scheduled appointments'. "
            "Returns each event with: property name, event type (visit/call/video), date, time, and status. "
            "If no events exist, suggest scheduling a visit or exploring properties."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_shortlisted_properties": {
        "name": "get_shortlisted_properties",
        "description": (
            "Get the list of properties the user has previously shortlisted (saved as favorites). "
            "Use when user asks 'my shortlisted properties', 'saved properties', 'favorites', 'properties I liked'. "
            "Returns property names and basic details. After showing, offer to get details, compare, or schedule visits for any of them. "
            "Do NOT confuse with shortlist_property (which ADDS to the list) — this READS the list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


def init_registry() -> None:
    """Register all tool schemas and handler functions. Call at startup."""
    from tools.broker.search import search_properties
    from tools.broker.property_details import fetch_property_details
    from tools.broker.shortlist import shortlist_property
    from tools.broker.images import fetch_property_images
    from tools.broker.landmarks import fetch_landmarks, estimate_commute
    from tools.broker.nearby_places import fetch_nearby_places
    from tools.broker.room_details import fetch_room_details
    from tools.broker.query_properties import fetch_properties_by_query
    from tools.broker.compare import compare_properties
    from tools.booking.save_phone import save_phone_number
    from tools.booking.schedule_visit import save_visit_time
    from tools.booking.schedule_call import save_call_time
    from tools.booking.payment import create_payment_link, verify_payment
    from tools.booking.reserve import check_reserve_bed, reserve_bed
    from tools.booking.cancel import cancel_booking
    from tools.booking.reschedule import reschedule_booking
    from tools.booking.kyc import fetch_kyc_status, initiate_kyc, verify_kyc
    from tools.profile.details import fetch_profile_details
    from tools.profile.events import get_scheduled_events
    from tools.profile.shortlisted import get_shortlisted_properties
    from tools.default.brand_info import brand_info
    from tools.broker.preferences import save_preferences
    from tools.common.web_search import web_search

    handlers = {
        "brand_info": brand_info,
        "save_preferences": save_preferences,
        "search_properties": search_properties,
        "save_phone_number": save_phone_number,
        "fetch_property_details": fetch_property_details,
        "shortlist_property": shortlist_property,
        "fetch_property_images": fetch_property_images,
        "fetch_landmarks": fetch_landmarks,
        "estimate_commute": estimate_commute,
        "fetch_nearby_places": fetch_nearby_places,
        "fetch_room_details": fetch_room_details,
        "fetch_properties_by_query": fetch_properties_by_query,
        "compare_properties": compare_properties,
        "web_search": web_search,
        "save_visit_time": save_visit_time,
        "save_call_time": save_call_time,
        "create_payment_link": create_payment_link,
        "verify_payment": verify_payment,
        "check_reserve_bed": check_reserve_bed,
        "reserve_bed": reserve_bed,
        "cancel_booking": cancel_booking,
        "reschedule_booking": reschedule_booking,
        "fetch_kyc_status": fetch_kyc_status,
        "initiate_kyc": initiate_kyc,
        "verify_kyc": verify_kyc,
        "fetch_profile_details": fetch_profile_details,
        "get_scheduled_events": get_scheduled_events,
        "get_shortlisted_properties": get_shortlisted_properties,
    }

    for name, handler in handlers.items():
        schema = SCHEMAS.get(name)
        if schema:
            register_tool(name, schema, handler)
