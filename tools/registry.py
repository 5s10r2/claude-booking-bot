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
    "default": ["brand_info"],
    "broker": [
        "save_preferences",
        "search_properties",
        "fetch_property_details",
        "shortlist_property",
        "fetch_property_images",
        "fetch_landmarks",
        "fetch_nearby_places",
        "fetch_room_details",
        "fetch_properties_by_query",
    ],
    "booking": _BOOKING_BASE_TOOLS + (_KYC_TOOLS if settings.KYC_ENABLED else []),
    "profile": [
        "fetch_profile_details",
        "get_scheduled_events",
        "get_shortlisted_properties",
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
        "description": "Fetch brand and property information for the current platform. Returns rent ranges, amenities, property types, and coverage areas.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "save_preferences": {
        "name": "save_preferences",
        "description": "Save or update user's property search preferences. Call this before searching to store location, budget, property type, and other filters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Area/locality AND city, e.g. 'Koramangala, Bangalore'"},
                "city": {"type": "string", "description": "City name, e.g. 'Bangalore'"},
                "min_budget": {"type": "number", "description": "Minimum monthly rent budget"},
                "max_budget": {"type": "number", "description": "Maximum monthly rent budget"},
                "move_in_date": {"type": "string", "description": "Preferred move-in date, pass as user stated it"},
                "property_type": {"type": "string", "description": "One of: PG Rooms, Co-Living, Hostel, or null for flats"},
                "unit_types_available": {"type": "string", "description": "Comma-separated: ROOM, 1RK, 1BHK, 2BHK, 3BHK, 4BHK, 5BHK"},
                "pg_available_for": {"type": "string", "description": "All Girls, All Boys, or Any"},
                "sharing_types_enabled": {"type": "string", "description": "Room sharing count: 1 for single, 2 for double, etc."},
                "amenities": {"type": "string", "description": "Comma-separated amenities: gym, wifi, parking, kitchen, etc."},
                "description": {"type": "string", "description": "User's free-text description of what they want"},
                "commute_from": {"type": "string", "description": "User's commute reference point — office, college, or any landmark they want properties near. E.g. 'Reliance Corporate Park, Navi Mumbai'"},
            },
            "required": ["location"],
        },
    },
    "search_properties": {
        "name": "search_properties",
        "description": "Search for properties based on saved preferences. Returns up to 20 properties with name, location, rent, images, and match scores. Show 5 at a time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "radius_flag": {"type": "boolean", "description": "Set true to expand search radius by 5km"},
            },
            "required": [],
        },
    },
    "fetch_property_details": {
        "name": "fetch_property_details",
        "description": "Get detailed information about a specific property including amenities, rules, rent, rooms, and images.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact name of the property as shown in search results"},
            },
            "required": ["property_name"],
        },
    },
    "shortlist_property": {
        "name": "shortlist_property",
        "description": "Add a property to the user's shortlist for later reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact name of the property to shortlist"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_property_images": {
        "name": "fetch_property_images",
        "description": "Fetch images for a specific property. Returns image URLs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_landmarks": {
        "name": "fetch_landmarks",
        "description": "Get distance from a landmark to a specific property.",
        "input_schema": {
            "type": "object",
            "properties": {
                "landmark_name": {"type": "string", "description": "Name of the landmark or place"},
                "property_name": {"type": "string", "description": "Exact property name"},
            },
            "required": ["landmark_name", "property_name"],
        },
    },
    "fetch_nearby_places": {
        "name": "fetch_nearby_places",
        "description": "Find nearby points of interest (restaurants, metro stations, hospitals, etc.) around a property.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
                "radius": {"type": "integer", "description": "Search radius in meters (default 5000)"},
                "amenity": {"type": "string", "description": "Type of place to search for, e.g. restaurant, hospital, school"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_room_details": {
        "name": "fetch_room_details",
        "description": "Get available room details for a property including room types, sharing, and availability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_properties_by_query": {
        "name": "fetch_properties_by_query",
        "description": "Fetch properties matching a text query/name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Property name or search query"},
            },
            "required": ["query"],
        },
    },
    "save_phone_number": {
        "name": "save_phone_number",
        "description": "Save the user's 10-digit Indian mobile number so it can be used for payment links, visit scheduling, and KYC. Call this when the user provides their phone number and a mobile number is required to proceed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "The user's mobile number (10-digit Indian number, with or without +91 prefix)",
                },
            },
            "required": ["phone_number"],
        },
    },
    "save_visit_time": {
        "name": "save_visit_time",
        "description": "Schedule a physical visit to a property. Visits available 9 AM - 5 PM, next 7 days, 30-minute slots.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
                "visit_date": {"type": "string", "description": "Visit date as stated by user"},
                "visit_time": {"type": "string", "description": "Visit time as stated by user"},
                "visit_type": {"type": "string", "description": "Always 'Physical visit'"},
            },
            "required": ["property_name", "visit_date", "visit_time"],
        },
    },
    "save_call_time": {
        "name": "save_call_time",
        "description": "Schedule a phone call or video tour with a property. Available 10 AM - 9 PM, next 7 days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
                "visit_date": {"type": "string", "description": "Date as stated by user"},
                "visit_time": {"type": "string", "description": "Time as stated by user"},
                "visit_type": {"type": "string", "description": "'Phone Call' or 'Video Tour'"},
            },
            "required": ["property_name", "visit_date", "visit_time", "visit_type"],
        },
    },
    "create_payment_link": {
        "name": "create_payment_link",
        "description": "Generate a payment link for the token amount to reserve a bed/room.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
            },
            "required": ["property_name"],
        },
    },
    "verify_payment": {
        "name": "verify_payment",
        "description": "Verify and record a completed payment for a property reservation.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "check_reserve_bed": {
        "name": "check_reserve_bed",
        "description": "Check if a bed is already reserved for the user at a property. Returns success: true if reserved, false if not.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
            },
            "required": ["property_name"],
        },
    },
    "reserve_bed": {
        "name": "reserve_bed",
        "description": "Reserve a bed/room at a property. ONLY call after KYC verification and payment completion.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
            },
            "required": ["property_name"],
        },
    },
    "cancel_booking": {
        "name": "cancel_booking",
        "description": "Cancel an existing visit, call, or booking for a property.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
            },
            "required": ["property_name"],
        },
    },
    "reschedule_booking": {
        "name": "reschedule_booking",
        "description": "Reschedule an existing visit or call to a new date/time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "Exact property name"},
                "visit_date": {"type": "string", "description": "New date"},
                "visit_time": {"type": "string", "description": "New time"},
                "visit_type": {"type": "string", "description": "Physical visit, Phone Call, or Video Tour"},
            },
            "required": ["property_name"],
        },
    },
    "fetch_kyc_status": {
        "name": "fetch_kyc_status",
        "description": "Check if the user has completed KYC (Aadhaar verification).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "initiate_kyc": {
        "name": "initiate_kyc",
        "description": "Start KYC process by submitting user's 12-digit Aadhaar number. An OTP will be sent to their registered phone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "aadhar_number": {"type": "string", "description": "12-digit Aadhaar number"},
            },
            "required": ["aadhar_number"],
        },
    },
    "verify_kyc": {
        "name": "verify_kyc",
        "description": "Complete KYC by verifying the OTP sent to user's phone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "otp": {"type": "string", "description": "OTP received by the user"},
            },
            "required": ["otp"],
        },
    },
    "fetch_profile_details": {
        "name": "fetch_profile_details",
        "description": "Fetch the user's saved profile and search preferences.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_scheduled_events": {
        "name": "get_scheduled_events",
        "description": "Get all scheduled visits, calls, and bookings for the user.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "get_shortlisted_properties": {
        "name": "get_shortlisted_properties",
        "description": "Get the list of properties the user has shortlisted.",
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
    from tools.broker.landmarks import fetch_landmarks
    from tools.broker.nearby_places import fetch_nearby_places
    from tools.broker.room_details import fetch_room_details
    from tools.broker.query_properties import fetch_properties_by_query
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

    handlers = {
        "brand_info": brand_info,
        "save_preferences": save_preferences,
        "search_properties": search_properties,
        "save_phone_number": save_phone_number,
        "fetch_property_details": fetch_property_details,
        "shortlist_property": shortlist_property,
        "fetch_property_images": fetch_property_images,
        "fetch_landmarks": fetch_landmarks,
        "fetch_nearby_places": fetch_nearby_places,
        "fetch_room_details": fetch_room_details,
        "fetch_properties_by_query": fetch_properties_by_query,
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
