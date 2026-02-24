import httpx

from config import settings
from db.redis_store import get_property_info_map, set_property_images_id


async def fetch_property_images(user_id: str, property_name: str, **kwargs) -> str:
    info_map = get_property_info_map(user_id)
    prop = None
    for p in info_map:
        if p.get("property_name", "").strip().lower() == property_name.strip().lower():
            prop = p
            break
    if not prop:
        for p in info_map:
            if property_name.strip().lower() in p.get("property_name", "").strip().lower():
                prop = p
                break

    if not prop:
        return f"Property '{property_name}' not found in search results."

    pg_id = prop.get("pg_id", "")
    pg_number = prop.get("pg_number", "")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/fetchPropertyImages",
                json={"pg_id": pg_id, "pg_number": pg_number},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error fetching images: {str(e)}"

    images = data.get("images", data.get("data", []))
    if not images:
        return f"No images found for '{property_name}'."

    image_list = []
    for img in images[:10]:
        if isinstance(img, dict):
            image_list.append(img)
        elif isinstance(img, str):
            image_list.append({"media_id": img, "url": img})

    set_property_images_id(user_id, image_list)

    urls = [i.get("url", i.get("media_id", "")) for i in image_list]
    return f"Found {len(urls)} images for '{prop.get('property_name', property_name)}':\n" + "\n".join(urls)
