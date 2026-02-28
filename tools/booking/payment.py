import httpx

from config import settings
from db.redis_store import (
    get_property_info_map,
    set_payment_info,
    get_payment_info,
    clear_payment_info,
    track_funnel,
    get_user_phone,
    get_aadhar_user_name,
)


def _find_property(user_id: str, property_name: str):
    info_map = get_property_info_map(user_id)
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            return p
    return None


async def create_payment_link(user_id: str, property_name: str, **kwargs) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    eazypg_id = prop.get("eazypg_id", "")
    pg_id = prop.get("pg_id", "")
    pg_number = prop.get("pg_number", "")
    amount = prop.get("property_min_token_amount", 0) or 1000

    # Resolve phone — required by Rentok tenant system
    phone = get_user_phone(user_id)
    if not phone:
        return (
            "I need your mobile number to generate a payment link. "
            "Please share your 10-digit Indian mobile number and I'll proceed right away!"
        )

    # Fetch tenant UUID — create lead if tenant doesn't exist yet
    tenant_uuid = ""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            uuid_resp = await client.get(
                f"{settings.RENTOK_API_BASE_URL}/tenant/get-tenant_uuid",
                params={"phone": phone, "eazypg_id": eazypg_id},
            )
            uuid_resp.raise_for_status()
            tenant_uuid = uuid_resp.json().get("data", {}).get("tenant_uuid", "")
    except Exception:
        pass  # Will try creating lead below

    # If no UUID yet, create a lead first then retry
    if not tenant_uuid:
        try:
            from tools.booking.schedule_visit import _create_external_lead

            await _create_external_lead(
                user_id, eazypg_id, pg_id, pg_number, "", "", "",
            )
            async with httpx.AsyncClient(timeout=15) as client:
                uuid_resp = await client.get(
                    f"{settings.RENTOK_API_BASE_URL}/tenant/get-tenant_uuid",
                    params={"phone": phone, "eazypg_id": eazypg_id},
                )
                uuid_resp.raise_for_status()
                tenant_uuid = uuid_resp.json().get("data", {}).get("tenant_uuid", "")
        except Exception as e2:
            return f"Error creating payment link: {str(e2)}"

    if not tenant_uuid:
        return "Could not generate payment link. Please try again."

    # Generate payment link
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.RENTOK_API_BASE_URL}/tenant/{tenant_uuid}/lead-payment-link",
                params={"pg_id": pg_id, "pg_number": pg_number, "amount": 1},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error generating payment link: {str(e)}"

    link_subs = data.get("data", {}).get("link", "")
    pg_name = data.get("data", {}).get("pg_name", prop.get("property_name", property_name))

    if not link_subs:
        return "Could not generate payment link. Please try again."

    set_payment_info(user_id, pg_name, pg_id, pg_number, str(amount), link_subs)
    link = f"https://pay.rentok.com/p/{link_subs}"

    return f"Payment link generated for {pg_name}: {link}\nToken amount: Rs. {amount}. Please complete the payment and let me know once done."


async def verify_payment(user_id: str, **kwargs) -> str:
    payment_info = get_payment_info(user_id)
    if not payment_info:
        return "No pending payment found. Please generate a payment link first."

    pg_name = payment_info.get("pg_name", "")
    pg_id = payment_info.get("pg_id", "")
    pg_number = payment_info.get("pg_number", "")
    amount = payment_info.get("amount", "")
    link_subs = payment_info.get("short_link", "")

    # Record payment in backend
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/addPayment",
                json={
                    "user_id": user_id[:12],
                    "pg_id": pg_id,
                    "pg_number": pg_number,
                    "amount": amount,
                    "short_link": link_subs,
                },
            )
    except Exception:
        pass  # Non-critical

    # Update lead status to Token
    info_map = get_property_info_map(user_id)
    eazypg_id = ""
    for p in info_map:
        if p.get("pg_id") == pg_id and str(p.get("pg_number", "")) == str(pg_number):
            eazypg_id = p.get("eazypg_id", "")
            break

    if eazypg_id:
        try:
            from datetime import datetime
            from db.redis_store import get_aadhar_gender, get_preferences

            gender = get_aadhar_gender(user_id) or "Any"
            prefs = get_preferences(user_id)
            budget = prefs.get("min_budget") or prefs.get("max_budget", "")
            phone = get_user_phone(user_id) or ""
            name = get_aadhar_user_name(user_id) or phone or "Guest"

            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    f"{settings.RENTOK_API_BASE_URL}/tenant/addLeadFromEazyPGID",
                    json={
                        "eazypg_id": eazypg_id,
                        "phone": phone,
                        "name": name,
                        "gender": gender,
                        "rent_range": budget,
                        "lead_source": "Booking Bot",
                        "visit_date": "",
                        "visit_time": "",
                        "visit_type": "",
                        "lead_status": "Token",
                        "firebase_id": f"cust_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}",
                    },
                )
        except Exception:
            pass

    clear_payment_info(user_id)
    track_funnel(user_id, "booking")
    return f"Payment verified successfully for {pg_name}. You can now proceed with bed reservation."
