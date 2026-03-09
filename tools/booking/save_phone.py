import re

from db.redis_store import set_user_phone, get_user_phone


TOOL_SCHEMA = {
    "name": "save_phone_number",
    "description": "Save the user's 10-digit Indian mobile number so it can be used for payment links, visit scheduling, and KYC. Call this when the user provides their phone number and a mobile number is required to proceed.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "phone_number": {
                "type": "string",
                "description": "The user's mobile number (10-digit Indian number, with or without +91 prefix)",
            },
        },
        "required": ["phone_number"],
    },
}


def save_phone_number(user_id: str, phone_number: str, **kwargs) -> str:
    """
    Validate and persist the user's phone number so subsequent booking
    API calls (payment link, visit scheduling, KYC) can send a real phone
    to the Rentok tenant system.

    Accepts inputs like:
      - "9876543210"       (10 digits, local)
      - "919876543210"     (12 digits, international without +)
      - "+919876543210"    (E.164)
      - "98765 43210"      (with spaces)
    """
    # Strip everything except digits
    digits = re.sub(r"\D", "", phone_number)

    # Accept 10-digit local or 12-digit international (91XXXXXXXXXX)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]          # strip country code → 10 digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]          # strip leading 0 → 10 digits

    if len(digits) != 10:
        return (
            f"'{phone_number}' doesn't look like a valid 10-digit Indian mobile number. "
            "Please share your number again — e.g., 9876543210."
        )

    # Don't re-store if it's already correct (idempotent)
    existing = get_user_phone(user_id)
    if existing == digits:
        return f"Phone number {digits} is already saved. Let's continue!"

    set_user_phone(user_id, digits)
    return (
        f"Got it! I've saved your mobile number ending in **{digits[-4:]}**. "
        "Let me now proceed with your request."
    )
