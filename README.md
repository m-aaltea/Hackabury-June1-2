# GMI's PassPreview — Hackabury 2026

A sales and onboarding tool for Romax Digital. Paste any client website URL and the backend scrapes it, Gemini analyses the brand identity, and an animated digital wallet pass preview builds itself in real time. The pass can be edited inline and sent to the Romax team via a CTA flow.

---

## Architecture

```
User pastes a website URL
        ↓
React + Vite frontend (localhost:5173)
        ↓
FastAPI backend (localhost:8000)
        ↓
httpx fetches raw HTML → BeautifulSoup extracts
title, description, og:image, favicon, theme-color, body text
        ↓
colorthief pulls dominant colour palette from logo
        ↓
Gemini 2.5 Flash — Brand Analysis Agent
        ↓
Structured JSON: brand name, colours, pass type, fields, tagline
        ↓
Frontend animates pass card field by field
        ↓
User edits inline → CTA screen → mock send to Romax team
```

---

## File Structure

```
Hackabury-June1-2/
├── backend/
│   ├── main.py              # FastAPI app, /api/scrape endpoint
│   ├── scraper.py           # httpx + BeautifulSoup scrape logic
│   ├── gemini.py            # Gemini prompt, JSON parsing, confidence score
│   ├── requirements.txt
│   ├── start.sh
│   ├── Dockerfile           # multi-stage container build
│   └── .env                 # GEMINI_API_KEY (gitignored)
│
└── frontend/
    ├── Dockerfile           # Vite build -> nginx
    ├── nginx.conf.template  # /api proxy to the backend
    └── src/
        ├── components/
        │   ├── EntryScreen.jsx     # URL input + Preview Pass button
        │   ├── PassCard.jsx        # Animated pass card (Apple + Google Wallet)
        │   ├── EditPanel.jsx       # Inline editing — fields, colours, pass type
        │   ├── CTAScreen.jsx       # Email capture + platform link + mock send
        │   ├── InfoPanel.jsx       # Confidence score + pass info sidebar
        │   └── BlockedScreen.jsx   # Shown when site uses bot protection
        ├── App.jsx                 
        ├── api.js                 
        └── index.css
```

---

## Gemini Agent

**Model:** Gemini 2.5 Flash

**Input:** Scraped page data — title, description, body text, logo URL, theme colour, dominant image colours

**Output:** Structured JSON

```json
{
  "brand_name": "string",
  "logo_url": "string | null",
  "colours": {
    "primary": "#hex",
    "secondary": "#hex",
    "text": "#hex"
  },
  "pass_type": "Membership Card | Event Pass | Loyalty Card | Supporter Card | Member ID",
  "fields": [
    { "label": "string", "value": "string" }
  ],
  "tagline": "string",
  "confidence_score": 0.0
}
```

Gemini infers brand identity from scraped data and fills in realistic pass fields using its own knowledge of the brand when scraping is sparse or blocked. `confidence_score` reflects extraction quality from `0.0` to `1.0`.

---

## Pass Card

Two wallet styles — **Apple Wallet** and **Google Wallet** — toggled live.
Three barcode formats: QR Code, Barcode (linear), PDF417.

**Loading states:**
- **Skeleton phase** — shimmer animation while backend processes
- **Reveal phase** — real data fades in field by field over ~2s
- **Loaded** — static card with cardReveal animation

---

## Bot Protection Handling

The scraper detects blocked sites via response headers and HTML patterns:

| Reason | Detection |
|---|---|
| `cloudflare` | `cf-ray` header or "Just a moment" page |
| `bot_wall` | Imperva `x-iinfo` header, DataDome, PerimeterX markers |
| `captcha` | reCAPTCHA, hCaptcha strings in HTML |
| `forbidden` | HTTP 403 |
| `empty_page` | Response body under 1000 characters |

When blocked, Gemini falls back to brand knowledge and a `BlockedScreen` is shown with a preview option.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | React + Vite |
| Backend | FastAPI + uvicorn |
| Scraping | httpx + BeautifulSoup |
| Colour extraction | colorthief |
| AI | Gemini 2.5 Flash |
| Dev tooling | Claude Code |

---

## Dependencies

```
fastapi
uvicorn
httpx
beautifulsoup4
colorthief
google-genai
```

```bash
pip install -r requirements.txt
```

---

## Environment Variables

The Gemini key is read at runtime from the `GEMINI_API_KEY` environment variable. It is never baked into the container image.

```
GEMINI_API_KEY=your-key
```

On AWS, the deploy script stores this value in an encrypted SSM parameter instead of placing it in Terraform state or the Lambda configuration. The function reads it once per warm Lambda environment.

The frontend nginx container reads `BACKEND_URL` at runtime to decide where to proxy `/api` (default `http://backend:8000`).

---

## Running Locally

**Backend**
```bash
cd backend
./start.sh
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `localhost:5173`, proxies `/api` to `localhost:8000`.

**Backend with Docker**
```bash
docker build -t passpreview-backend ./backend
docker run -p 8000:8000 --env-file ./backend/.env passpreview-backend
```

The container listens on port `8000`. If `GEMINI_API_KEY` is omitted the API still starts and the Gemini step falls back to a generated pass.

**Frontend with Docker**
```bash
docker build -t passpreview-frontend ./frontend
docker run -p 8080:80 -e BACKEND_URL=http://backend:8000 passpreview-frontend
```

The two images are separate containers. For local development link them on a shared Docker network (or use docker-compose) so nginx can reach the backend by hostname. In an ECS task with `awsvpc` networking, set `BACKEND_URL=http://localhost:8000` instead, since the containers in the same task share a network namespace.

**Both services with Docker Compose**
```bash
docker compose up -d --build
```

This starts the backend (port `8000`, key from `backend/.env`) and the frontend (port `8080` by default, proxying `/api` to the backend). Open http://localhost:8080. Stop everything with `docker compose down`.

---

## Deploying to AWS (serverless + Terraform)

The production architecture is:

```
Browser
  -> CloudFront
       -> S3 (React/Vite files)
       -> API Gateway HTTP API (/api/*)
            -> Lambda container (FastAPI + Lambda Web Adapter)
                 -> Gemini API
```

There is no database in this application, so the stack deliberately does not provision DynamoDB or RDS. User image uploads remain browser-local data URLs, and the CTA form is currently a mock that only logs in the browser.

### Prerequisites

- An AWS account with credentials configured locally (`aws configure` or AWS SSO)
- Docker running
- Terraform 1.6 or newer
- Node.js and npm

The default region is London (`eu-west-2`) and the default Lambda architecture is ARM64. Override them with `AWS_REGION` and `LAMBDA_ARCHITECTURE` if needed.

### Deploy

```bash
GEMINI_API_KEY='your-key' ./deploy.sh
```

The script:

1. Builds the Vite frontend.
2. Creates the Terraform-managed ECR repository on the first run.
3. Builds and pushes an immutable Lambda container image.
4. Applies the full Terraform stack.
5. Saves the Gemini key as an encrypted SSM Standard parameter.
6. Uploads the frontend to S3 and invalidates CloudFront.

Terraform shows the plan and asks for confirmation before each apply. CloudFront commonly takes several minutes to create on the first deployment. At the end, the script prints the HTTPS app URL. Run the same command for later deployments; a new immutable image tag ensures Lambda is updated.

To customise Terraform settings:

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

Terraform state is local and gitignored. For a team or CI/CD deployment, move it to an encrypted remote backend before sharing access.

### Cost reality

This should be very cheap at hobby traffic, but it is not guaranteed to stay at `$0–2/month`:

- Lambda's monthly free request/compute allowance is ongoing.
- API Gateway's one-million-call free tier lasts only 12 months; calls are pay-as-you-go after that.
- Private ECR's 500 MB allowance also lasts only 12 months, after which the small stored image is billed per GB-month.
- S3 storage/requests, CloudWatch logs, and the Gemini API can add separate charges.
- CloudFront's standard free allowance is generous enough for a small static frontend.

The Terraform defaults use the AWS account-level Lambda concurrency quota, throttle API Gateway, retain only five images, and expire logs after 14 days. New AWS accounts commonly begin with a low account-level concurrency quota. Set a small AWS Budget alert as a separate account-level safeguard before sharing the URL publicly.

### Remove the stack

```bash
cd infra
terraform destroy
aws ssm delete-parameter --region eu-west-2 --name /passpreview/gemini-api-key
```

The SSM parameter is managed outside Terraform so the secret never enters Terraform state; remove it separately as shown.
