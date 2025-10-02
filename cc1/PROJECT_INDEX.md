# PROJECT INDEX
_Project structure and technical specs. Update when: creating files, adding dependencies, defining schemas._

## Stack
Backend: FastAPI (Python 3.11) | Frontend: Bootstrap 5 + Vanilla JS | Database: PostgreSQL 15 | AI: OpenAI API | Deploy: Docker + docker-compose | Google Ads: AsyncIO + Batch API (v28) | Automation: Docker multi-stage builds

## Directory Structure
```
test2/
├── cc1/                   # CC1 documentation
│   ├── TASKS.md          # Task tracking
│   ├── LEARNINGS.md      # Knowledge capture
│   ├── BACKLOG.md        # Future planning
│   └── PROJECT_INDEX.md  # This file
├── thema_ads_project/     # Google Ads automation project
│   ├── thema_ads          # Legacy script (refactored to use .env)
│   ├── .env               # Credentials for legacy script (git ignored)
│   ├── .env.example       # Template for legacy script environment
│   ├── README.md          # Legacy script setup instructions
│   └── thema_ads_optimized/  # High-performance optimized version
│       ├── config.py       # Environment-based configuration
│       ├── models.py       # Data structures
│       ├── google_ads_client.py  # Client initialization
│       ├── main_optimized.py     # Async orchestrator
│       ├── operations/     # API operations (prefetch, ads, labels)
│       │   ├── prefetch.py
│       │   ├── ads.py
│       │   └── labels.py
│       ├── templates/      # Ad content generators
│       │   └── generators.py
│       ├── processors/     # Data loading (Excel/CSV)
│       │   └── data_loader.py
│       ├── utils/          # Utilities (cache, retry)
│       │   ├── cache.py
│       │   └── retry.py
│       ├── data/           # Input files (mounted volume)
│       ├── logs/           # Output logs (mounted volume)
│       ├── Dockerfile      # Multi-stage build
│       ├── docker-compose.yml
│       ├── docker-run.sh   # Helper script
│       ├── requirements.txt
│       ├── .env            # Google Ads credentials
│       └── README.md       # Usage documentation
├── backend/
│   ├── main.py           # FastAPI app with CORS & Thema Ads endpoints
│   │                     # CSV parsing: empty row handling, dash removal, optional columns
│   ├── database.py       # PostgreSQL connection & schema initialization
│   │                     # Schema: campaign_id and campaign_name columns added
│   ├── gpt_service.py    # AI integration
│   ├── thema_ads_service.py  # Thema Ads job management with state persistence
│   │                          # Features: delete job, campaign info fetching at runtime
│   ├── thema_ads_schema.sql  # Database schema for job tracking
│   └── scraper_service.py    # Web scraping utilities
├── frontend/
│   ├── index.html        # Main page (Bootstrap CDN)
│   ├── thema-ads.html    # Thema Ads progress tracking UI
│   ├── css/
│   │   └── style.css     # Custom styles
│   └── js/
│       ├── app.js        # Vanilla JavaScript
│       └── thema-ads.js  # Thema Ads frontend logic with polling
│                         # Features: delete job UI with confirmation
├── docker-compose.yml    # Service orchestration (no version attr)
├── Dockerfile           # Python container
├── requirements.txt     # Python dependencies
├── .env.example        # Environment template
├── .env                # Local environment (git ignored)
├── .gitignore          # Version control excludes
│                       # Ignores: .env files, thema_ads legacy script, Excel files (*.xlsx, *.xls)
├── README.md           # Quick start guide
├── CLAUDE.md           # Claude Code instructions
├── THEMA_ADS_GUIDE.md  # Complete Thema Ads documentation
├── START_HERE.md       # Quick start for web interface
├── start-thema-ads.sh  # Automated setup script
└── sample_input.csv    # Example CSV for Thema Ads upload
```

## Environment Variables

### Required (FastAPI/OpenAI)
```bash
OPENAI_API_KEY=sk-...  # Your OpenAI API key
DATABASE_URL=postgresql://postgres:postgres@db:5432/myapp
AI_MODEL=gpt-4o-mini  # Or other OpenAI model
```

### Required (Google Ads - thema_ads_optimized)
```bash
GOOGLE_DEVELOPER_TOKEN=...           # Google Ads developer token
GOOGLE_REFRESH_TOKEN=1//09...        # OAuth refresh token
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...     # OAuth client secret
GOOGLE_LOGIN_CUSTOMER_ID=3011145605  # Manager account ID

# Performance Tuning (optional)
MAX_CONCURRENT_CUSTOMERS=10          # Parallel customer processing
MAX_CONCURRENT_OPERATIONS=50         # Concurrent operations per customer
BATCH_SIZE=1000                      # Operations per batch (max 10000)
API_RETRY_ATTEMPTS=3                 # Retry failed operations
API_RETRY_DELAY=1.0                  # Delay between retries (seconds)
ENABLE_CACHING=true                  # Cache label/campaign lookups

# Application Settings
INPUT_FILE=input_data.xlsx           # Excel/CSV file to process
LOG_LEVEL=INFO                       # DEBUG | INFO | WARNING | ERROR
DRY_RUN=false                        # Set to true for testing
```

### Required (Legacy Script - thema_ads)
```bash
# Google Ads OAuth Credentials (REQUIRED)
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REFRESH_TOKEN=1//09...
GOOGLE_DEVELOPER_TOKEN=...
GOOGLE_LOGIN_CUSTOMER_ID=...

# Azure Mail Credentials (OPTIONAL - for email features)
MAIL_TENANT_ID=...
MAIL_CLIENT_ID=...
MAIL_CLIENT_SECRET=...
MAIL_CLIENT_SECRET_ID=...

# File Paths (OPTIONAL - defaults provided)
EXCEL_PATH=C:\Users\YourName\Downloads\Python\your_file.xlsx
SERVICE_ACCOUNT_FILE=C:\Users\YourName\Downloads\Python\service-account.json
```

### Important Notes
- **OAuth Credentials**: refresh_token must match the client_id/client_secret used to generate it
- **API Version**: Requires google-ads>=25.1.0 (currently using v28.0.0)
- **Performance**: For 1M ads, consider running in chunks of 10k-50k

## Docker Configuration

### Uvicorn Server Settings (docker-compose.yml)
```bash
command: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --timeout-keep-alive 600 --timeout-graceful-shutdown 60
```
- **timeout-keep-alive**: 600 seconds (10 minutes) - supports large file uploads without connection drops
- **timeout-graceful-shutdown**: 60 seconds - allows in-flight requests to complete during restart
- **reload**: Auto-reload on code changes (development mode)

## Database Schema

### Thema Ads Job Tracking
```sql
-- Jobs table: tracks each processing job
CREATE TABLE thema_ads_jobs (
    id SERIAL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_ad_groups INTEGER DEFAULT 0,
    processed_ad_groups INTEGER DEFAULT 0,
    successful_ad_groups INTEGER DEFAULT 0,
    failed_ad_groups INTEGER DEFAULT 0,
    skipped_ad_groups INTEGER DEFAULT 0,
    input_file VARCHAR(255),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT
);

-- Job items: tracks each individual ad group
CREATE TABLE thema_ads_job_items (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES thema_ads_jobs(id) ON DELETE CASCADE,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50),           -- Optional: from CSV or fetched at runtime
    campaign_name TEXT,                -- Optional: from CSV or fetched at runtime
    ad_group_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    new_ad_resource VARCHAR(500),
    error_message TEXT,
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Input data: stores uploaded CSV data
CREATE TABLE thema_ads_input_data (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES thema_ads_jobs(id) ON DELETE CASCADE,
    customer_id VARCHAR(50) NOT NULL,
    campaign_id VARCHAR(50),           -- Optional: from CSV or fetched at runtime
    campaign_name TEXT,                -- Optional: from CSV or fetched at runtime
    ad_group_id VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- SEO workflow tables (existing)
CREATE TABLE pa.jvs_seo_werkvoorraad (...);
CREATE TABLE pa.jvs_seo_werkvoorraad_kopteksten_check (...);
CREATE TABLE pa.content_urls_joep (...);
```

## Dependencies

### Backend (Python 3.11)
```
# FastAPI & Web
fastapi==0.104.1          # Web framework
uvicorn[standard]==0.24.0 # ASGI server
python-multipart==0.0.6   # File upload support (CSV)

# AI & External APIs
openai==1.35.0            # OpenAI API client
httpx==0.25.2             # HTTP client (pinned for OpenAI compatibility)
requests==2.31.0          # HTTP requests
beautifulsoup4==4.12.3    # Web scraping
lxml==5.1.0               # XML/HTML parsing

# Database
psycopg2-binary==2.9.9    # PostgreSQL adapter

# Google Ads
google-ads==28.0.0        # Google Ads API client (upgraded from v24)
pandas==2.2.0             # Data processing and Excel handling
openpyxl==3.1.2           # Excel file reading

# Utilities
python-dotenv==1.0.0      # Environment variable management
```

## Git Repository

- **URL**: https://github.com/joep-1993/theme_ads
- **User**: joep-1993 <joepvanschagen34@gmail.com>
- **Authentication**: SSH (ed25519 key)
- **Protected Files**: thema_ads_project/thema_ads, *.xlsx, *.xls (in .gitignore)

## API Endpoints

### Core
- `GET /` - System status
- `GET /api/health` - Health check
- `POST /api/generate` - AI text generation
- `GET /static/*` - Frontend files

### SEO Workflow
- `POST /api/process-urls` - Process batch of URLs for SEO content
- `GET /api/status` - Get SEO processing status

### Labels Applied by Thema Ads
**Ad Groups get labeled with:**
- `BF_2025` - Black Friday 2025 campaign marker
- `SD_DONE` - Processing complete marker (used to skip already-processed ad groups)
  - **Only applied to successfully processed ad groups**
  - Ad groups without existing ads are NOT labeled (skipped for different reason)

**New Ads get labeled with:**
- `SINGLES_DAY` - Singles Day themed ad
- `THEMA_AD` - Themed ad marker

**Existing Ads get labeled with:**
- `THEMA_ORIGINAL` - Original ad marker

### Job Status Categories
**Completed**: Successfully created new themed ads
**Skipped**: Two types
- Already processed (has SD_DONE label from previous run)
- No existing ads (ad group has 0 ads, can't be processed)

**Failed**: Actual errors (API failures, permission issues, etc.)

### Thema Ads Job Management
- `POST /api/thema-ads/upload` - Upload CSV file and auto-start processing (flexible format, see CSV Format below)
- `POST /api/thema-ads/jobs/{job_id}/start` - Start processing job (deprecated - jobs auto-start on upload)
- `POST /api/thema-ads/jobs/{job_id}/pause` - Pause running job
- `POST /api/thema-ads/jobs/{job_id}/resume` - Resume paused/failed job
- `GET /api/thema-ads/jobs/{job_id}` - Get job status & progress
- `GET /api/thema-ads/jobs` - List all jobs (limit=20)
- `GET /api/thema-ads/jobs/{job_id}/failed-items-csv` - Download failed and skipped items as CSV (includes status and reason columns)
- `DELETE /api/thema-ads/jobs/{job_id}` - Delete job and all associated data (blocks running jobs)

#### CSV Format
**Minimum columns** (campaign info fetched at runtime):
- `customer_id` (required) - dashes automatically removed
- `ad_group_id` (required)

**Recommended columns** (faster, no API calls):
- `customer_id` (required)
- `campaign_id` (optional)
- `campaign_name` (optional)
- `ad_group_id` (required)

**Notes**:
- Column order doesn't matter (parsed by name, not position)
- Extra columns are ignored (e.g., status, budget, ad group name)
- Empty rows are automatically skipped
- Delimiter auto-detected (comma or semicolon)
- Maximum file size: 30MB
- Encoding auto-detected (UTF-8, Windows-1252, ISO-8859-1, Latin1)
- Jobs automatically start processing after successful upload

#### Downloaded CSV Format (Failed/Skipped Items)
- `customer_id` - Google Ads customer ID
- `campaign_id` - Campaign ID (if available)
- `campaign_name` - Campaign name (if available)
- `ad_group_id` - Ad group ID
- `status` - "failed" or "skipped"
- `reason` - Human-readable explanation:
  - "Ad group has 'SD_DONE' label (already processed)"
  - "Ad group has 0 ads"
  - Original error message for actual failures

---
_Last updated: 2025-10-02_
