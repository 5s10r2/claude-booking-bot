from core.log import get_logger

logger = get_logger("utils.api")


class RentokAPIError(Exception):
    """Raised when Rentok API returns a success HTTP status but an error payload."""
    pass


def check_rentok_response(data: dict, context: str = "") -> dict:
    """Validate Rentok API response. Raises RentokAPIError if payload indicates failure."""
    status = data.get("status")
    if isinstance(status, int) and status >= 400:
        msg = data.get("message", "Unknown error")
        logger.warning("Rentok API error [%s]: status=%s msg=%s", context, status, msg)
        raise RentokAPIError(f"API error ({status}): {msg}")
    if isinstance(status, str) and status.lower() == "error":
        msg = data.get("message", "Unknown error")
        logger.warning("Rentok API error [%s]: %s", context, msg)
        raise RentokAPIError(f"API error: {msg}")
    return data
