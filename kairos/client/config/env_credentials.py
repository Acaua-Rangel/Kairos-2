"""Binance API credentials sourced from the process environment (populated from ``.env``).

Replaces the old encrypted-keystore flow: this fork only ever needs Binance keys, so there is
nothing to route by connector beyond mapping ``BINANCE_API_KEY``/``BINANCE_API_SECRET`` onto
whichever field names the target connector's config map expects.
"""
import os
from typing import Dict, Optional, Tuple

_FIELDS: Dict[str, Tuple[str, str]] = {
    "binance": ("binance_api_key", "binance_api_secret"),
    "binance_perpetual": ("binance_perpetual_api_key", "binance_perpetual_api_secret"),
}


def env_api_keys(connector_name: str) -> Optional[Dict[str, str]]:
    """The connector's API key/secret from the environment, or ``None`` if unset/not applicable."""
    fields = _FIELDS.get(connector_name)
    if fields is None:
        return None
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        return None
    key_field, secret_field = fields
    return {key_field: api_key, secret_field: api_secret}
