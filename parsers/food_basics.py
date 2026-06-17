import re
from typing import Dict, Any, List, Optional
from .base import Parser
from .factory import register_parser

@register_parser
class FoodBasicsParser(Parser):
    vendor_name = "Food Basics"

    @classmethod
    def matches(cls, text: str) -> float:
        if not text:
            return 0.0
        txt = text.lower()
        # strong signal if header contains "food basics" or "foodbasics"
        if "food basics" in txt or "foodbasics" in txt:
            return 1.0
        # moderate signal: presence of 'Your savings today' + 'Promotional discounts'
        if "your savings today" in txt and "promotional discounts" in txt:
            return 0.6
        return 0.0

    def _find_date(self, text: str) -> Optional[str]:
        # try formats like "Sept 03 2024 20:44" or "09/03/2024"
        m = re.search(r'([A-Za-z]{3,9}\s+\d{1,2}\s+\d{4})\s+(\d{1,2}:\d{2})', text)
        if m:
            for fmt in ('%b %d %Y %H:%M', '%B %d %Y %H:%M'):
                try:
                    dt = self.datetime.strptime(m.group(1) + ' ' + m.group(2), fmt)
                    return dt.strftime('%Y-%m-%d')
                except Exception:
                    continue
        m2 = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text)
        if m2:
            try:
                dt = self.datetime.strptime(m2.group(1), '%m/%d/%Y')
                return dt.strftime('%Y-%m-%d')
            except Exception:
                pass
        return None

    def _find_trans_number(self, text: str) -> Optional[str]:
        m = re.search(r'Trans#\s*:\s*(\d+)', text, re.IGNORECASE)
        if m:
            return m.group(1)
        m2 = re.search(r'Transaction\s+Record[\s\S]*?(\d{6,})', text, re.IGNORECASE)
        if m2:
            return m2.group(1)
        return None

    def _parse_items(self, text: str) -> List[Dict[str, Any]]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        items: List[Dict[str, Any]] = []
        i = 0
        # iterate lines
        while i < len(lines):
            ln = lines[i]
            # pattern: "(2)LSM.NO SALT ADD." or "LSM.NO SALT ADD." with next line "2 @ $1.77 3.54"
            m_paren = re.match(r'^\(?(\d+)\)?\s*([A-Z0-9\.\- #&]+)$', ln)
            if m_paren and i + 1 < len(lines):
                qty = int(m_paren.group(1))
                name = m_paren.group(2).strip()
                next_ln = lines[i+1]
                m_qtyline = re.search(r'(\d+)\s*@\s*\$?([0-9\.,]+)\s+([0-9\.,]+)', next_ln)
                if m_qtyline:
                    unit_price = self.parse_decimal(m_qtyline.group(2))
                    total_price = self.parse_decimal(m_qtyline.group(3))
                    items.append({
                        "item_name": name,
                        "quantity": qty,
                        "quantity_unit": "cnt",
                        "unit_price": unit_price,
                        "total_price": total_price
                    })
                    i += 2
                    continue
            # weight-priced: name on one line, weight line next e.g. "0.155 kg @ $6.57/kg 1.02"
            m_weight = re.match(r'^([0-9\.,]+)\s*(kg|g|lb|lbs)\s*@\s*\$?([0-9\.,]+)/?kg?\s+([0-9\.,]+)$', ln, re.IGNORECASE)
            if m_weight and items:
                prev = items.pop()
                weight = self.parse_decimal(m_weight.group(1))
                unit = m_weight.group(2).lower()
                unit_price = self.parse_decimal(m_weight.group(3))
                total_price = self.parse_decimal(m_weight.group(4))
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
            # standalone qty line like "2 @ $1.77 3.54" with name on previous line
            m_qtyline2 = re.match(r'^(\d+)\s*@\s*\$?([0-9\.,]+)\s+([0-9\.,]+)$', ln)
            if m_qtyline2 and i - 1 >= 0:
                name = lines[i-1].strip()
                qty = int(m_qtyline2.group(1))
                unit_price = self.parse_decimal(m_qtyline2.group(2))
                total_price = self.parse_decimal(m_qtyline2.group(3))
                # remove any prior simple-line item that duplicated this
                if items and items[-1]["item_name"] == name:
                    items.pop()
                items.append({
                    "item_name": name,
                    "quantity": qty,
                    "quantity_unit": "cnt",
                    "unit_price": unit_price,
                    "total_price": total_price
                })
                i += 1
                continue
            # single-line: "TOMATO RED 4.98"
            m_single = re.match(r'^([A-Z0-9\.\- &]+?)\s+([0-9]+\.[0-9]{2})$', ln)
            if m_single:
                name = m_single.group(1).strip()
                price = self.parse_decimal(m_single.group(2))
                items.append({
                    "item_name": name,
                    "quantity": 1,
                    "quantity_unit": "cnt",
                    "unit_price": price,
                    "total_price": price
                })
                i += 1
                continue
            # skip savings or promotional lines
            if re.match(r'^(saving|savings|promotional)', ln, re.IGNORECASE):
                i += 1
                continue
            i += 1

        # final cleanup: drop obvious non-items
        cleaned: List[Dict[str, Any]] = []
        for it in items:
            name = re.sub(r'\b(Saving|Savings|Promotional).*$', '', it["item_name"], flags=re.IGNORECASE).strip()
            if not name or re.match(r'^(subtotal|total|debit|credit|promotional|your savings)', name, re.IGNORECASE):
                continue
            it["item_name"] = name
            cleaned.append(it)
        return cleaned

    def parse(self, text: str) -> Dict[str, Any]:
        txt = self.normalize_text(text)
        items = self._parse_items(txt)

        # totals
        subtotal = None
        total = None
        tax = None
        m_sub = re.search(r'SUBTOTAL\s+([0-9\.,]+)', txt, re.IGNORECASE)
        if m_sub:
            subtotal = self.parse_decimal(m_sub.group(1))
        m_tot = re.search(r'\bTOTAL\b\s+([0-9\.,]+)', txt, re.IGNORECASE)
        if m_tot:
            total = self.parse_decimal(m_tot.group(1))
        m_total_line = re.search(r'Total\s*:\s*(?:[A-Z]{3}\$)?\s*\$?([0-9\.,]+)', txt, re.IGNORECASE)
        if m_total_line:
            total = self.parse_decimal(m_total_line.group(1))

        if subtotal is not None and total is not None:
            try:
                tax = round(total - subtotal, 2)
            except Exception:
                tax = None

        date = self._find_date(txt)
        trans = self._find_trans_number(txt)
        # currency
        currency = "CAD" if "CAD" in txt or "CAD$" in txt or "C$" in txt else "CAD"

        # normalize numeric fields to floats with two decimals where applicable
        for it in items:
            if isinstance(it.get("unit_price"), float):
                it["unit_price"] = round(it["unit_price"], 2)
            if isinstance(it.get("total_price"), float):
                it["total_price"] = round(it["total_price"], 2)

        result = {
            "vendor_name": self.vendor_name,
            "receipt_date": date,
            "receipt_number": trans,
            "items": items,
            "subtotal": subtotal,
            "tax_amount": tax if tax is not None else 0.0,
            "total_amount": total,
            "currency": currency
        }
        return result
