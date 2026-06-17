import re
from typing import Dict, Any, List
from .base import Parser

class GenericParser(Parser):
    vendor_name = "generic"

    @classmethod
    def matches(cls, text: str) -> float:
        # generic parser should be last-resort -> low base score
        return 0.1

    def parse(self, text: str) -> Dict[str, Any]:
        txt = self.normalize_text(text)
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]

        # naive total/subtotal detection
        subtotal = None
        total = None
        tax = None
        currency = None

        m = re.search(r'SUBTOTAL\s+([0-9\.,]+)', txt, re.IGNORECASE)
        if m:
            subtotal = self.parse_decimal(m.group(1))
        m = re.search(r'\bTOTAL\b\s+([0-9\.,]+)', txt, re.IGNORECASE)
        if m:
            total = self.parse_decimal(m.group(1))
        # fallback "Total : CAD$ 20.40"
        m = re.search(r'Total\s*:\s*(?:[A-Z]{3}\$)?\s*\$?([0-9\.,]+)', txt, re.IGNORECASE)
        if m:
            total = self.parse_decimal(m.group(1))

        if subtotal is not None and total is not None:
            tax = round((total - subtotal), 2)

        # attempt to extract items: lines that end with price
        items: List[Dict[str, Any]] = []
        item_line_re = re.compile(r'^(.+?)\s+([0-9]+\.[0-9]{2})$')
        i = 0
        while i < len(lines):
            ln = lines[i]
            m = item_line_re.match(ln)
            if m:
                name = m.group(1).strip()
                price = self.parse_decimal(m.group(2))
                items.append({
                    "item_name": name,
                    "quantity": 1,
                    "quantity_unit": "cnt",
                    "unit_price": price,
                    "total_price": price
                })
                i += 1
                continue
            # detect weight-pricing lines: "0.155 kg @ $6.57/kg 1.02"
            m2 = re.match(r'^([0-9\.,]+)\s*(kg|g|lb|lbs)\s*@\s*\$?([0-9\.,]+)/?kg?\s+([0-9\.,]+)$', ln, re.IGNORECASE)
            if m2 and items:
                # attach to previous item name
                prev = items.pop()
                weight = self.parse_decimal(m2.group(1))
                unit = m2.group(2).lower()
                unit_price = self.parse_decimal(m2.group(3))
                total_price = self.parse_decimal(m2.group(4))
                if unit == 'g':
                    qty = weight / 1000.0
                    qty_unit = 'kg'
                else:
                    qty = weight
                    qty_unit = unit
                items.append({
                    "item_name": prev["item_name"],
                    "quantity": qty,
                    "quantity_unit": qty_unit,
                    "unit_price": unit_price,
                    "total_price": total_price
                })
                i += 1
                continue
            i += 1

        # best-effort vendor detection via header tokens
        vendor = None
        for ln in lines[:6]:
            if re.search(r'FOOD BASICS', ln, re.IGNORECASE):
                vendor = "Food Basics"
                break

        result = {
            "vendor_name": vendor,
            "receipt_date": None,
            "receipt_number": None,
            "items": items,
            "subtotal": subtotal,
            "tax_amount": tax if tax is not None else 0.0,
            "total_amount": total,
            "currency": currency or "CAD"
        }
        return result
