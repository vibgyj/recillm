import base64
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

OLLAMA_API_URL = "http://localhost:11434/api/chat"
OLLAMA_TIMEOUT_SECONDS = 900
TEXT_MODEL_NAME = "qwen3:8b" # "qwen3:4b" # "granite3-moe:1b"
VISION_MODEL_NAME = "glm-ocr" # "qwen3-vl:8b" # "Maternion/LightOnOCR-2:1b"
SUPPORTED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
DB_PATH = Path(__file__).with_name("receipts.sqlite3")

app = FastAPI(title="GPU-Optimized Invoice & Receipt Extractor")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LineItem(BaseModel):
    item_name: str = Field(description="The name or description of the purchased item.")
    quantity: Optional[float] = Field(default=None, description="Quantity of the item bought.")
    quantity_unit: Optional[str] = Field(default=None, description="Unit for the item quantity, e.g. kg, cnt, l, ml.")
    unit_price: Optional[float] = Field(default=None, description="Price per unit according to quantity_unit.")
    total_price: float = Field(..., description="Total price for the purchased item.")


class InvoiceReceiptSchema(BaseModel):
    vendor_name: str = Field(..., description="Name of the store or company.")
    receipt_date: date = Field(..., description="Date of the purchase.")
    receipt_number: Optional[str] = Field(default=None, description="Unique receipt number used by the merchant.")
    items: List[LineItem] = Field(
        ..., description="Line items on the receipt or invoice.")
    subtotal: Optional[float] = Field(default=None, description="Total before taxes.")
    tax_amount: Optional[float] = Field(default=None, description="Amount of taxes applied.")
    total_amount: float = Field(..., description="Total amount including taxes.")
    currency: Optional[str] = Field(default=None, description="Currency code such as USD or CAD.")


class ExtractResponse(BaseModel):
    receipt_text: str = Field(..., description="Raw extracted text from the receipt/invoice image.")
    data: InvoiceReceiptSchema = Field(..., description="Structured invoice/receipt data.")


class SaveReceiptRequest(BaseModel):
    receipt_id: Optional[str] = Field(
        default=None,
        description="Existing local receipt id to update. If omitted, the server creates one.",
    )
    receipt_text: Optional[str] = Field(default=None, description="Raw extracted receipt text.")
    data: InvoiceReceiptSchema = Field(..., description="Reviewed invoice/receipt data to save.")


class SaveReceiptResponse(BaseModel):
    receipt_id: str = Field(..., description="Local receipt id written to SQLite.")
    action: str = Field(..., description="Whether the receipt was created or updated.")
    item_count: int = Field(..., description="Number of line items written.")


class ReceiptSummary(BaseModel):
    receipt_id: str
    vendor_name: str
    receipt_date: date
    receipt_number: Optional[str] = None
    total_amount: float
    currency: Optional[str] = None
    item_count: int
    created_at: str
    updated_at: str


class SavedReceipt(BaseModel):
    receipt_id: str
    vendor_name: str
    receipt_date: date
    receipt_number: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: float
    currency: Optional[str] = None
    receipt_text: Optional[str] = None
    created_at: str
    updated_at: str
    items: List[LineItem]


def _connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _parse_receipt_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"Unsupported receipt date value: {value!r}")

    normalized = value.strip()
    if not normalized:
        raise ValueError("Receipt date is empty.")

    try:
        return date.fromisoformat(normalized[:10])
    except ValueError:
        pass

    digits = re.sub(r"\D+", "", normalized)
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date()
        except ValueError:
            pass

    for fmt in ("%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Unsupported receipt date format: {value!r}")


def _receipt_date_for_db(receipt_date: date) -> str:
    return receipt_date.isoformat()


def _normalize_receipt_dates(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT receipt_id, receipt_date FROM receipts").fetchall()
    for row in rows:
        normalized = _parse_receipt_date(row["receipt_date"]).isoformat()
        if row["receipt_date"] != normalized:
            conn.execute(
                "UPDATE receipts SET receipt_date = ? WHERE receipt_id = ?",
                (normalized, row["receipt_id"]),
            )


def _migrate_receipt_date_column(conn: sqlite3.Connection) -> None:
    table_info = conn.execute("PRAGMA table_info(receipts)").fetchall()
    receipt_date_column = next((row for row in table_info if row["name"] == "receipt_date"), None)
    if receipt_date_column is None or receipt_date_column["type"].upper() == "DATE":
        _normalize_receipt_dates(conn)
        return

    receipt_rows = conn.execute(
        """
        SELECT
            receipt_id,
            vendor_name,
            receipt_date,
            receipt_number,
            subtotal,
            tax_amount,
            total_amount,
            currency,
            receipt_text,
            created_at,
            updated_at
        FROM receipts
        """
    ).fetchall()
    item_rows = conn.execute(
        """
        SELECT
            item_id,
            receipt_id,
            item_order,
            item_name,
            quantity,
            quantity_unit,
            unit_price,
            total_price
        FROM items
        """
    ).fetchall()

    conn.executescript(
        """
        CREATE TABLE receipts_migrated (
            receipt_id TEXT PRIMARY KEY,
            vendor_name TEXT NOT NULL,
            receipt_date DATE NOT NULL,
            receipt_number TEXT,
            subtotal REAL,
            tax_amount REAL,
            total_amount REAL NOT NULL,
            currency TEXT,
            receipt_text TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE items_migrated (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id TEXT NOT NULL,
            item_order INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            quantity REAL,
            quantity_unit TEXT,
            unit_price REAL,
            total_price REAL NOT NULL,
            FOREIGN KEY (receipt_id) REFERENCES receipts_migrated(receipt_id) ON DELETE CASCADE
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO receipts_migrated (
            receipt_id,
            vendor_name,
            receipt_date,
            receipt_number,
            subtotal,
            tax_amount,
            total_amount,
            currency,
            receipt_text,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["receipt_id"],
                row["vendor_name"],
                _parse_receipt_date(row["receipt_date"]).isoformat(),
                row["receipt_number"],
                row["subtotal"],
                row["tax_amount"],
                row["total_amount"],
                row["currency"],
                row["receipt_text"],
                row["created_at"],
                row["updated_at"],
            )
            for row in receipt_rows
        ],
    )
    conn.executemany(
        """
        INSERT INTO items_migrated (
            item_id,
            receipt_id,
            item_order,
            item_name,
            quantity,
            quantity_unit,
            unit_price,
            total_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["item_id"],
                row["receipt_id"],
                row["item_order"],
                row["item_name"],
                row["quantity"],
                row["quantity_unit"],
                row["unit_price"],
                row["total_price"],
            )
            for row in item_rows
        ],
    )
    conn.execute("DROP TABLE items")
    conn.execute("DROP TABLE receipts")
    conn.execute("ALTER TABLE receipts_migrated RENAME TO receipts")
    conn.execute("ALTER TABLE items_migrated RENAME TO items")


def _ensure_db() -> None:
    with _connect_db() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id TEXT PRIMARY KEY,
                vendor_name TEXT NOT NULL,
                receipt_date DATE NOT NULL,
                receipt_number TEXT,
                subtotal REAL,
                tax_amount REAL,
                total_amount REAL NOT NULL,
                currency TEXT,
                receipt_text TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT NOT NULL,
                item_order INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                quantity REAL,
                quantity_unit TEXT,
                unit_price REAL,
                total_price REAL NOT NULL,
                FOREIGN KEY (receipt_id) REFERENCES receipts(receipt_id) ON DELETE CASCADE
            );
            """
        )
        _migrate_receipt_date_column(conn)
        conn.execute("PRAGMA foreign_keys = ON")


@app.on_event("startup")
def startup() -> None:
    _ensure_db()


def _slugify_vendor(vendor_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", vendor_name.lower()).strip("-")
    return slug or "receipt"


def _date_key(receipt_date: date) -> str:
    return receipt_date.strftime("%Y%m%d")


def _next_receipt_id(conn: sqlite3.Connection, data: InvoiceReceiptSchema) -> str:
    prefix = f"{_slugify_vendor(data.vendor_name)}-{_date_key(data.receipt_date)}"
    rows = conn.execute(
        "SELECT receipt_id FROM receipts WHERE receipt_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchall()
    max_sequence = 0
    for (receipt_id,) in rows:
        suffix = receipt_id.removeprefix(f"{prefix}-")
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{prefix}-{max_sequence + 1:03d}"


def _resolve_receipt_id(conn: sqlite3.Connection, request: SaveReceiptRequest) -> str:
    if request.receipt_id:
        return request.receipt_id

    data = request.data
    if data.receipt_number:
        existing = conn.execute(
            """
            SELECT receipt_id
            FROM receipts
            WHERE lower(vendor_name) = lower(?)
              AND receipt_date = ?
              AND receipt_number = ?
            """,
            (data.vendor_name, _receipt_date_for_db(data.receipt_date), data.receipt_number),
        ).fetchone()
        if existing:
            return existing[0]

    return _next_receipt_id(conn, data)


def _receipt_summary_from_row(row: sqlite3.Row) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=row["receipt_id"],
        vendor_name=row["vendor_name"],
        receipt_date=_parse_receipt_date(row["receipt_date"]),
        receipt_number=row["receipt_number"],
        total_amount=row["total_amount"],
        currency=row["currency"],
        item_count=row["item_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _list_receipts() -> list[ReceiptSummary]:
    _ensure_db()
    with _connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                r.receipt_id,
                r.vendor_name,
                r.receipt_date,
                r.receipt_number,
                r.total_amount,
                r.currency,
                r.created_at,
                r.updated_at,
                COUNT(i.item_id) AS item_count
            FROM receipts r
            LEFT JOIN items i ON i.receipt_id = r.receipt_id
            GROUP BY r.receipt_id
            ORDER BY r.receipt_date DESC, r.updated_at DESC, r.vendor_name ASC
            """
        ).fetchall()
    return [_receipt_summary_from_row(row) for row in rows]


def _get_receipt(receipt_id: str) -> SavedReceipt:
    _ensure_db()
    with _connect_db() as conn:
        receipt = conn.execute(
            """
            SELECT
                receipt_id,
                vendor_name,
                receipt_date,
                receipt_number,
                subtotal,
                tax_amount,
                total_amount,
                currency,
                receipt_text,
                created_at,
                updated_at
            FROM receipts
            WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()
        if receipt is None:
            raise HTTPException(status_code=404, detail="Receipt not found.")

        item_rows = conn.execute(
            """
            SELECT
                item_name,
                quantity,
                quantity_unit,
                unit_price,
                total_price
            FROM items
            WHERE receipt_id = ?
            ORDER BY item_order ASC, item_id ASC
            """,
            (receipt_id,),
        ).fetchall()

    return SavedReceipt(
        receipt_id=receipt["receipt_id"],
        vendor_name=receipt["vendor_name"],
        receipt_date=_parse_receipt_date(receipt["receipt_date"]),
        receipt_number=receipt["receipt_number"],
        subtotal=receipt["subtotal"],
        tax_amount=receipt["tax_amount"],
        total_amount=receipt["total_amount"],
        currency=receipt["currency"],
        receipt_text=receipt["receipt_text"],
        created_at=receipt["created_at"],
        updated_at=receipt["updated_at"],
        items=[
            LineItem(
                item_name=row["item_name"],
                quantity=row["quantity"],
                quantity_unit=row["quantity_unit"],
                unit_price=row["unit_price"],
                total_price=row["total_price"],
            )
            for row in item_rows
        ],
    )


def _save_receipt(request: SaveReceiptRequest) -> SaveReceiptResponse:
    _ensure_db()
    data = request.data
    with _connect_db() as conn:
        receipt_id = _resolve_receipt_id(conn, request)
        exists = conn.execute(
            "SELECT 1 FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        action = "updated" if exists else "created"

        conn.execute(
            """
            INSERT INTO receipts (
                receipt_id,
                vendor_name,
                receipt_date,
                receipt_number,
                subtotal,
                tax_amount,
                total_amount,
                currency,
                receipt_text,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(receipt_id) DO UPDATE SET
                vendor_name = excluded.vendor_name,
                receipt_date = excluded.receipt_date,
                receipt_number = excluded.receipt_number,
                subtotal = excluded.subtotal,
                tax_amount = excluded.tax_amount,
                total_amount = excluded.total_amount,
                currency = excluded.currency,
                receipt_text = excluded.receipt_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                receipt_id,
                data.vendor_name,
                _receipt_date_for_db(data.receipt_date),
                data.receipt_number,
                data.subtotal,
                data.tax_amount,
                data.total_amount,
                data.currency,
                request.receipt_text,
            ),
        )
        conn.execute("DELETE FROM items WHERE receipt_id = ?", (receipt_id,))
        conn.executemany(
            """
            INSERT INTO items (
                receipt_id,
                item_order,
                item_name,
                quantity,
                quantity_unit,
                unit_price,
                total_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    receipt_id,
                    index,
                    item.item_name,
                    item.quantity,
                    item.quantity_unit,
                    item.unit_price,
                    item.total_price,
                )
                for index, item in enumerate(data.items, start=1)
            ],
        )

    return SaveReceiptResponse(
        receipt_id=receipt_id,
        action=action,
        item_count=len(data.items),
    )


def _query_ollama(
    *,
    model: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    images: Optional[list[str]] = None,
    response_format: Optional[dict] = None,
) -> str:
    user_message: dict[str, object] = {"role": "user", "content": prompt}
    if images:
        user_message["images"] = images

    messages: list[dict[str, object]] = []
    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})
    messages.append(user_message)

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
    }
    if response_format is not None:
        payload["format"] = (
            response_format
            if response_format.get("type") is not None
            else {"type": "json", "json_schema": response_format}
        )

    try:
        response = requests.post(
            OLLAMA_API_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        return body["message"]["content"]
    except requests.RequestException as exc:
        raise HTTPException(status_code=500, detail=f"Ollama inference failed: {exc}") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Ollama returned an unexpected response.") from exc


def query_local_text_llm(raw_text: str) -> str:
    system_prompt = (
        "You're a data entry agent expert in converting and formatting receipt image extract raw text into a strict JSON data structure. "
        "You understand the context of each line and can determine whether it represents an item name, quantity, unit price, total price, or other relevant information. "

        "Items may be listed in various formats, and you should be able to parse them correctly. "
        "Some items may be represented in a single line with the item name and total price, while others may span multiple lines with quantity and unit price information. "

        "1 line Example:\n"
        "ITEM A 23423234234   $1.07 D\n"
        "Expected output: {\"item_name\": \"Item A 23423234234\", \"total_price\": 1.07}\n\n"

        "2 line Examples:\n"
        "ITEM B 32482394234\n"
        " 1.255 kg @ $1.18 /kg       $1.48 D\n"
        "Expected Output: {\"item_name\": \"ITEM B 32482394234\", \"quantity\": 1.255, \"quantity_unit\": \"kg\", \"unit_price\": 1.18, \"total_price\": 1.48}\n\n"

        "ITEM C\n"
        "  2 @ $1.76                 3.54\n"
        "Expected Output: {\"item_name\": \"ITEM C\", \"quantity\": 2, \"quantity_unit\": \"cnt\", \"unit_price\": 1.76, \"total_price\": 3.54}\n\n"
        
        "ITEM D\n"
        "  0.165 kg @ $6.47/kg       1.07\n"
        "Expected Output: {\"item_name\": \"ITEM D\", \"quantity\": 0.165, \"quantity_unit\": \"kg\", \"unit_price\": 6.47, \"total_price\": 1.07}\n\n"

        "Combined Example:\n"
        "ITEM A 23423234234   $1.07 D\n"
        "ITEM B 32482394234\n"
        " 1.255 kg @ $1.18 /kg       $1.48 D\n"
        "ITEM C\n"
        "  2 @ $1.76                 3.54\n"
        "ITEM D\n"
        "  0.165 kg @ $6.47/kg       1.07\n"
        "Expected output: [{\"item_name\": \"Item A 23423234234\", \"total_price\": 1.07},\n"
        "{\"item_name\": \"ITEM B 32482394234\", \"quantity\": 1.255, \"quantity_unit\": \"kg\", \"unit_price\": 1.18, \"total_price\": 1.48},\n"
        "{\"item_name\": \"ITEM C\", \"quantity\": 2, \"quantity_unit\": \"cnt\", \"unit_price\": 1.76, \"total_price\": 3.54},\n"
        "{\"item_name\": \"ITEM D\", \"quantity\": 0.165, \"quantity_unit\": \"kg\", \"unit_price\": 6.47, \"total_price\": 1.07}]\n"
    )
    prompt = (
        "Parse the receipt text below and return only valid JSON that matches the invoice/receipt schema.\n\n"
        f"{raw_text}"
    )
    return _query_ollama(
        model=TEXT_MODEL_NAME,
        prompt=prompt,
        system_prompt=system_prompt,
        response_format=InvoiceReceiptSchema.model_json_schema(),
    )


def query_local_vision_llm(image_bytes: bytes, _image_format: str = "png") -> str:
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = (
        "Extract text from the receipt image and return the raw text without any additional commentary or formatting. "
        "The text should be exactly as it appears on the receipt, including line breaks and spacing, to preserve the original structure for accurate parsing. "
    )
    return _query_ollama(model=VISION_MODEL_NAME, prompt=prompt, images=[image_b64])


@app.get("/receipts", response_model=list[ReceiptSummary])
def list_receipts() -> list[ReceiptSummary]:
    try:
        return _list_receipts()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"SQLite read failed: {exc}") from exc


@app.get("/receipts/{receipt_id}", response_model=SavedReceipt)
def get_receipt(receipt_id: str) -> SavedReceipt:
    try:
        return _get_receipt(receipt_id)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"SQLite read failed: {exc}") from exc


@app.post("/receipts", response_model=SaveReceiptResponse)
def save_receipt(request: SaveReceiptRequest) -> SaveReceiptResponse:
    try:
        return _save_receipt(request)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"SQLite save failed: {exc}") from exc


@app.post("/extract", response_model=ExtractResponse)
async def extract_document_data(file: UploadFile = File(...)) -> ExtractResponse:
    filename = (file.filename or "").lower()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    file_bytes = await file.read()
    if not filename.endswith(SUPPORTED_IMAGE_SUFFIXES):
        raise HTTPException(status_code=400, detail="Unsupported file format.")

    image_format = filename.rsplit(".", maxsplit=1)[-1]
    receipt_text = query_local_vision_llm(file_bytes, image_format)
    json_output = query_local_text_llm(receipt_text)

    try:
        parsed_data = InvoiceReceiptSchema.model_validate_json(json_output)
        return ExtractResponse(receipt_text=receipt_text, data=parsed_data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Schema mismatch error: {exc}. Raw payload: {json_output}",
        ) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
