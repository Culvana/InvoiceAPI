# InvoiceAPI

> **Status:** Beta – foundational REST service for ingesting, storing, and retrieving supplier invoices.

`InvoiceAPI` exposes a **FastAPI** back end (deployable as an Azure Function) that provides CRUD endpoints for invoice documents and their parsed line-item data. The service underpins Culvanaʼs *InvoiceTest* pipeline and feeds inventory cost updates to downstream apps.

---

## 🎯 Core Features

| Capability           | Details                                                                                                  |
| -------------------- | -------------------------------------------------------------------------------------------------------- |
| **Upload endpoint**  | `POST /invoices` accepts PDF, image, or spreadsheet files. Triggers async OCR + AI parsing.              |
| **Polling status**   | `GET /invoices/{invoice_id}` returns processing progress and parsed JSON once ready.                     |
| **Line-item search** | `GET /invoices/{invoice_id}/items?q=` to filter by SKU, description, or vendor code.                     |
| **Webhook events**   | Emits `invoice.processed` webhooks so other services (e.g., InventoryAPI) can update costs in real time. |
| **Token-based auth** | Supports Bearer JWTs or Azure AD EasyAuth with a `ROLES=invoice.write` claim.                            |
| **CORS**             | Origins list pulled from `ALLOWED_ORIGINS` env-var.                                                      |

---

## 📁 Repository Structure

```
InvoiceAPI/
├── app/
│   ├── main.py            # FastAPI app factory
│   ├── models.py          # Pydantic schemas
│   ├── routers/
│   │   └── invoices.py    # All /invoices routes
│   ├── services/
│   │   ├── parser.py      # Calls Azure Document Intelligence & GPT-4o
│   │   └── storage.py     # Uploads raw + JSON to Blob
│   └── core/
│       └── config.py      # Settings from env-vars
├── function_app.py        # Azure Functions entrypoint (HTTP trigger)
├── requirements.txt
└── Dockerfile             # Container deployment (optional)
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/Culvana/InvoiceAPI.git
cd InvoiceAPI
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --reload  # http://localhost:8000
```

### Environment Variables

| Variable              | Required | Purpose                                           |
| --------------------- | -------- | ------------------------------------------------- |
| `AZURE_STORAGE_CONN`  | ✅        | Where raw & parsed invoices are stored.           |
| `FORM_RECOG_ENDPOINT` | ✅        | Azure Document Intelligence URL.                  |
| `FORM_RECOG_KEY`      | ✅        | API key for above.                                |
| `OPENAI_API_KEY`      | ✅        | GPT-4o for cleanup / extraction.                  |
| `WEBHOOK_URL`         | optional | If set, POSTs an event when processing completes. |
| `ALLOWED_ORIGINS`     | optional | Comma-separated CORS list.                        |

Copy `env.example` to `.env` and fill values for local dev.

---

## 🧪 Tests & Linting

```bash
pip install pytest flake8
pytest -v
flake8 app
```

---

## ☁️ Deployment Options

### 1. Azure Functions (Consumption)

```
func azure functionapp publish culvana-invoice-api --python
```

### 2. Container (App Service / AKS)

```
docker build -t culvana/invoiceapi .
docker run -p 8000:80 --env-file .env culvana/invoiceapi
```

---

## 📝 License

MIT © Culvana 2025
