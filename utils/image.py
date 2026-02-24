"""
Image utilities: WEBP→JPEG conversion, upload to WhatsApp media API.
"""

import io
from typing import Optional

import httpx

try:
    from PIL import Image
except ImportError:
    Image = None


async def convert_webp_to_jpeg(image_url: str) -> Optional[bytes]:
    """Download a WEBP image and convert to JPEG bytes."""
    if Image is None:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()

        img = Image.open(io.BytesIO(resp.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        print(f"[image] Error converting {image_url}: {e}")
        return None


async def upload_media_from_url(
    image_url: str,
    whatsapp_config: dict,
) -> Optional[str]:
    """Upload an image to WhatsApp media API.

    If the URL is WEBP, converts to JPEG first.
    Returns the media_id string, or None on failure.
    """
    is_meta = whatsapp_config.get("is_meta", True)
    phone_number_id = whatsapp_config.get("phone_number_id", "")
    headers = whatsapp_config.get("headers", {})

    # Determine if we need conversion
    is_webp = image_url.lower().endswith(".webp")

    if is_webp:
        jpeg_bytes = await convert_webp_to_jpeg(image_url)
        if jpeg_bytes is None:
            return None
        filename = "property.jpg"
        content_type = "image/jpeg"
        file_data = jpeg_bytes
    else:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                file_data = resp.content
        except Exception:
            return None

        content_type = "image/jpeg"
        if image_url.lower().endswith(".png"):
            content_type = "image/png"
        filename = "property.jpg"

    # Upload to WhatsApp media endpoint
    if is_meta:
        upload_url = f"https://graph.facebook.com/v19.0/{phone_number_id}/media"
    else:
        upload_url = f"https://amped-express.interakt.ai/api/v17.0/{phone_number_id}/media"

    try:
        upload_headers = dict(headers)
        upload_headers.pop("Content-Type", None)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                upload_url,
                headers=upload_headers,
                data={"messaging_product": "whatsapp"},
                files={"file": (filename, file_data, content_type)},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("id")
    except Exception as e:
        print(f"[image] Error uploading media: {e}")
        return None
