import base64
from typing import List, Optional

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

OLLAMA_API_URL = "http://localhost:11434/api/chat"
OLLAMA_TIMEOUT_SECONDS = 600
TEXT_MODEL_NAME = "qwen3:8b" # "granite3-moe:1b"
VISION_MODEL_NAME = "glm-ocr" # "qwen3-vl:8b" # "Maternion/LightOnOCR-2:1b"
SUPPORTED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

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
    receipt_date: str = Field(..., description="Date of the purchase in YYYY-MM-DD format.")
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
