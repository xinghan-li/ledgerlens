"""
Address Grounding: Use Gemini + Google Search to verify and complete
store addresses when the canonical database has no match.

Called as a fallback after address_matcher.correct_address() returns
without a match. Fills in missing structured fields (address_line1,
address_line2, city, state, zip_code, country) using real-world data.
"""
import json
import logging
from typing import Any, Dict, Optional

from google.genai import types

from ...config import settings
from ...services.llm.gemini_client import _get_client as _get_gemini_client

logger = logging.getLogger(__name__)

# Schema for the grounding response
_ADDRESS_SCHEMA = {
    "type": "object",
    "properties": {
        "verified": {"type": "boolean"},
        "address_line1": {"type": "string", "nullable": True},
        "address_line2": {"type": "string", "nullable": True},
        "city": {"type": "string", "nullable": True},
        "state": {"type": "string", "nullable": True},
        "zip_code": {"type": "string", "nullable": True},
        "country": {"type": "string", "nullable": True},
        "merchant_phone": {"type": "string", "nullable": True},
        "confidence": {"type": "string"},
        "source_note": {"type": "string", "nullable": True},
    },
    "required": ["verified", "confidence"],
}

_GROUNDING_PROMPT = """\
I have a store receipt with this merchant information:
- Store name: {merchant_name}
- Address from receipt (may be partial/damaged): {raw_address}
- City from receipt: {city}
- State/Province from receipt: {state}
- Zip/Postal code from receipt: {zip_code}
- Country from receipt: {country}
- Phone from receipt: {phone}

Use Google Search to find this store's real address. Return a JSON object with:
- verified: true if you found a matching real-world location, false if uncertain
- address_line1: street address only (e.g. "19715 Highway 99"), no unit/suite/city/state/zip
- address_line2: unit/suite number only as plain number (e.g. "101"), no prefix like "Suite" or "Unit". null if none.
- city: city name only
- state: state or province code (e.g. "WA", "BC")
- zip_code: zip or postal code
- country: country code (e.g. "US", "CA")
- merchant_phone: phone number if found
- confidence: "high", "medium", or "low"
- source_note: brief note about what you found (e.g. "Google Maps listing confirmed")

If you cannot find the store, set verified=false and return whatever partial info you have.\
"""


async def ground_address_with_search(
    llm_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Use Gemini + Google Search grounding to verify/complete a store address.
    Only called when canonical DB matching fails (no match in store_locations).

    Modifies llm_result in place: fills in missing structured address fields
    if grounding returns high/medium confidence.

    Args:
        llm_result: The LLM processing result (must have receipt.merchant_name).
    Returns:
        The (possibly updated) llm_result.
    """
    receipt = llm_result.get("receipt", {})
    merchant_name = receipt.get("merchant_name")
    if not merchant_name:
        return llm_result

    # Build the query from whatever address info we have
    raw_address = receipt.get("merchant_address") or ""
    city = receipt.get("city") or ""
    state = receipt.get("state") or ""
    zip_code = receipt.get("zip_code") or ""
    country = receipt.get("country") or ""
    phone = receipt.get("merchant_phone") or ""

    # Skip if we already have all structured fields filled
    if all([receipt.get("address_line1"), city, state, zip_code, country]):
        logger.debug("[grounding] All address fields present, skipping grounding")
        return llm_result

    prompt = _GROUNDING_PROMPT.format(
        merchant_name=merchant_name,
        raw_address=raw_address,
        city=city,
        state=state,
        zip_code=zip_code,
        country=country,
        phone=phone,
    )

    try:
        client = await _get_gemini_client()
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_ADDRESS_SCHEMA,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=config,
        )

        if not hasattr(response, "text") or not response.text:
            logger.warning("[grounding] Empty response from Gemini grounding")
            return llm_result

        result = json.loads(response.text.strip())
        confidence = result.get("confidence", "low")
        verified = result.get("verified", False)

        logger.info(
            "[grounding] merchant=%s verified=%s confidence=%s",
            merchant_name,
            verified,
            confidence,
        )

        # Only apply if verified and confidence is not low
        if not verified or confidence == "low":
            # Still record what we found in metadata
            if "_metadata" not in llm_result:
                llm_result["_metadata"] = {}
            llm_result["_metadata"]["address_grounding"] = {
                "verified": False,
                "confidence": confidence,
                "source_note": result.get("source_note"),
            }
            return llm_result

        # Sanitize LLM output before writing to receipt
        def _sanitize(val: str, max_len: int = 200) -> Optional[str]:
            if not isinstance(val, str):
                return None
            val = val.strip()
            if not val or "<" in val or "\n" in val:
                return None
            return val[:max_len]

        # Apply grounded address fields (only fill in missing/empty fields)
        field_map = {
            "address_line1": "address_line1",
            "address_line2": "address_line2",
            "city": "city",
            "state": "state",
            "zip_code": "zip_code",
            "country": "country",
            "merchant_phone": "merchant_phone",
        }
        fields_updated = []
        for grounding_key, receipt_key in field_map.items():
            grounded_value = _sanitize(result.get(grounding_key))
            if grounded_value and not receipt.get(receipt_key):
                receipt[receipt_key] = grounded_value
                fields_updated.append(receipt_key)

        # If high confidence and we have a better address_line1, override even existing
        if confidence == "high" and _sanitize(result.get("address_line1")):
            existing = receipt.get("address_line1") or ""
            grounded = _sanitize(result["address_line1"])
            if grounded and existing != grounded:
                receipt["address_line1"] = grounded
                if "address_line1" not in fields_updated:
                    fields_updated.append("address_line1")

        if fields_updated:
            logger.info("[grounding] Updated fields: %s", fields_updated)

        # Record grounding metadata
        if "_metadata" not in llm_result:
            llm_result["_metadata"] = {}
        llm_result["_metadata"]["address_grounding"] = {
            "verified": True,
            "confidence": confidence,
            "fields_updated": fields_updated,
            "source_note": result.get("source_note"),
        }

    except Exception as exc:
        logger.warning("[grounding] Address grounding failed: %s", exc)

    return llm_result
