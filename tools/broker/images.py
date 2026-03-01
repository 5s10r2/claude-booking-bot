import httpx

from config import settings
from db.redis_store import set_property_images_id
from utils.api import check_rentok_response
from utils.properties import find_property


async def fetch_property_images(user_id: str, property_name: str, **kwargs) -> str:
    prop = find_property(user_id, property_name)
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
            check_rentok_response(data, "fetchPropertyImages")
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
