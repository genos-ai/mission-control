"""
MCD pruning helpers (Plan 88, 88.3.2).

Pure functions over the Mission Context Document. The size measure here is the
one the MCD cap compares against: UTF-8 bytes of the JSON serialisation.
"""

import json


def mcd_size_bytes(value: object) -> int:
    """UTF-8 byte length of the JSON serialisation of value."""
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
