import re
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, Any, Optional, List

def parse_decimal(s: str) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(Decimal(s.replace(',', '').strip()))
    except (InvalidOperation, AttributeError):
        return None

def normalize_text(text: str) -> str:
    return re.sub(r'\r\n?', '\n', text).strip()

class Parser(ABC):
    vendor_name: str = "generic"

    @classmethod
    def matches(cls, text: str) -> float:
        """
        Return a confidence score 0..1 that this parser matches the text.
        Default: 0 (no special match). Override in vendor parsers.
        """
        return 0.0

    @abstractmethod
    def parse(self, text: str) -> Dict[str, Any]:
        """
        Parse receipt text and return dict matching your JSON schema.
        Must return at least:
          { "receipt_text": raw, "data": { ... } }
        """
        raise NotImplementedError

    # helper utilities available to parsers
    parse_decimal = staticmethod(parse_decimal)
    normalize_text = staticmethod(normalize_text)
    datetime = datetime
