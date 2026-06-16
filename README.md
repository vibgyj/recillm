# recillm

`recillm` is a local-first receipt/invoice extraction demo that combines:
- a FastAPI backend for OCR + structured parsing,
- a browser UI for uploading receipts and viewing extracted results, and
- a separate chat-style demo for asking questions about an image.

The project is designed to run entirely on your machine with local models served by Ollama.

## What this project does

The backend accepts a receipt/invoice image, sends it to a local vision model, extracts raw text, then asks a text model to convert that text into structured JSON.

The API returns:
- the raw OCR text, and
- a normalized object containing vendor, date, totals, and line items.

## Repository layout

- [api.py](api.py) — FastAPI service with the `/extract` endpoint.
- [receipt-scan.html](receipt-scan.html) — upload UI for parsing a receipt/invoice image.
- [vision-chat.html](vision-chat.html) — simple image Q&A chat demo.
- [requirements.txt](requirements.txt) — Python dependencies.

## Prerequisites

Before running the app, make sure you have:

1. Python 3.10+ installed.
2. A running Ollama instance on your machine.
3. The following model(s) pulled into Ollama:
   - `qwen3:8b` (used by the backend for JSON parsing)
   - `glm-ocr` (used by the backend for OCR)
   - optionally `qwen3-vl:2b` if you want to use the chat demo in [vision-chat.html](vision-chat.html)

You can check whether Ollama is available with:

```bash
curl http://localhost:11434/
```

If you need to pull models:

```bash
ollama pull qwen3:8b
ollama pull glm-ocr
ollama pull qwen3-vl:2b
```

## Install dependencies

```bash
pip install -r requirements.txt
```

## Run the backend

Start the API server:

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at:

- `http://localhost:8000/docs` for Swagger UI
- `http://localhost:8000/extract` for the upload endpoint

## Use the receipt scanner UI

Open [receipt-scan.html](receipt-scan.html) in a browser.

The page expects the backend to be running at:

```text
http://localhost:8000/extract
```

### Notes
- The backend currently accepts image files with extensions `.png`, `.jpg`, `.jpeg`, and `.webp`.
- PDF support is not implemented yet, but may be added in the future.
- The HTML upload UI may still mention PDF support in the interface text, so the backend behavior should be treated as the source of truth.

## Use the vision chat demo

Open [vision-chat.html](vision-chat.html) in a browser.

This UI sends requests directly to Ollama's chat API at:

```text
http://localhost:11434/api/chat
```

It is intended for experimenting with image-question prompts, not for the structured receipt extraction flow.

## API behavior

### `POST /extract`

Request body:
- multipart form-data
- field name: `file`

Response shape:

```json
{
  "receipt_text": "raw extracted text",
  "data": {
    "vendor_name": "Store name",
    "receipt_date": "YYYY-MM-DD",
    "receipt_number": "optional",
    "items": [
      {
        "item_name": "Example item",
        "quantity": 1,
        "quantity_unit": "cnt",
        "unit_price": 2.5,
        "total_price": 2.5
      }
    ],
    "subtotal": 10,
    "tax_amount": 1,
    "total_amount": 11,
    "currency": "USD"
  }
}
```

## CORS troubleshooting for Ollama

If the browser cannot reach Ollama, you may need to allow cross-origin requests.

### Windows
1. Quit the Ollama app from the system tray.
2. Run:
   ```powershell
   setx OLLAMA_ORIGINS "*"
   ```
3. Restart the Ollama app.

### macOS
1. Run:
   ```bash
   mkdir -p ~/Library/LaunchAgents
   launchctl setenv OLLAMA_ORIGINS "*"
   ```
2. Quit and restart Ollama.

### Linux
1. Edit the service file:
   ```bash
   sudo systemctl edit ollama.service
   ```
2. Add:
   ```ini
   [Service]
   Environment="OLLAMA_ORIGINS=*"
   ```
3. Restart the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart ollama
   ```

You can verify the setting with:

```bash
curl -I -H "Origin: http://localhost" http://localhost:11434/
```

Look for:

```text
Access-Control-Allow-Origin: *
```

## Current vs future behavior

### Currently supported
- Uploading receipt/invoice images in `.png`, `.jpg`, `.jpeg`, and `.webp` formats.
- Running OCR and structured extraction through a local FastAPI backend.
- Viewing the raw extracted text and parsed JSON output in the browser UI.

### Planned / future improvements
- Adding PDF parsing support.
- Improving prompt handling for edge-case receipts.
- Adding better validation and fallback behavior when the model output is incomplete.
- Expanding the UI and API for more document types.

## Known limitations

- The backend is currently designed for image uploads, not PDF parsing.
- Structured extraction quality depends heavily on the OCR output and the chosen models.
- Some receipts may require manual review if the formatting is unusual or low quality.
