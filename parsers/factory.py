from typing import Type, List
from .base import Parser
from .generic import GenericParser

_registry: List[Type[Parser]] = []

def register_parser(cls: Type[Parser]):
    """Register a Parser class. Call at import time from each module."""
    if cls not in _registry:
        _registry.append(cls)
    return cls

def available_parsers():
    return list(_registry)

def get_parser_for_text(text: str, vendor_hint: str = None) -> Parser:
    """
    Choose best parser for text. If vendor_hint provided, try to find matching parser.
    Returns an instance of Parser (never None).
    """
    txt = text or ""
    # vendor hint override
    if vendor_hint:
        for cls in _registry:
            if getattr(cls, "vendor_name", "").lower() == vendor_hint.lower():
                return cls()
    # score each registered parser by matches()
    best_cls = None
    best_score = -1.0
    for cls in _registry:
        try:
            score = float(cls.matches(txt))
        except Exception:
            score = 0.0
        if score > best_score:
            best_score = score
            best_cls = cls
    if best_cls and best_score > 0:
        return best_cls()
    # fallback to GenericParser if none matched or low score
    return GenericParser()
