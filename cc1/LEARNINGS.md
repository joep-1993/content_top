# LEARNINGS
_Capture mistakes, solutions, and patterns. Update when: errors occur, bugs are fixed, patterns emerge._

## Docker Commands
```bash
# Development
docker-compose up              # Run with logs
docker-compose up -d           # Run in background
docker-compose logs -f app     # View app logs
docker-compose down            # Stop everything
docker-compose down -v         # Stop and remove volumes

# Debugging
docker-compose ps              # Check status
docker exec -it <container> bash  # Enter container

# Import data from local file into container
docker cp /path/to/file container_name:/tmp/file
docker-compose exec -T db psql -U postgres -d dbname -c "COPY table (column) FROM '/tmp/file';"

# CSV import from Windows to container
docker cp /path/to/file.csv content_top_app:/app/file.csv
docker-compose exec app python -m backend.import_content

# Access Frontend
# Navigate to http://localhost:8003/static/index.html
```

## Common Issues & Solutions

### Docker/WSL Integration
- **Error**: `docker-compose: command not found` in WSL 2
- **Cause**: Docker Desktop WSL integration not enabled
- **Solution**: Enable WSL integration in Docker Desktop settings
  - Open Docker Desktop → Settings → Resources → WSL Integration
  - Enable integration for your WSL distro
  - Restart WSL terminal
- **Documentation**: https://docs.docker.com/go/wsl2/

### FastAPI Async Endpoints with psycopg2 ThreadedConnectionPool
- **Problem**: API endpoint hangs indefinitely at `get_output_connection()` call. The async event loop was blocked by synchronous `getconn()` from ThreadedConnectionPool
- **Symptoms**:
  - First batch processes successfully
  - Second batch hangs forever at database connection
  - Logs show "[ENDPOINT] Getting output connection..." but never reach "[POOL] get_output_connection() called"
  - No errors, no timeouts - just infinite hang
- **Root Cause**: FastAPI async endpoint calling synchronous blocking psycopg2 pool operations
  - `async def` endpoint uses asyncio event loop
  - `pool.getconn()` is synchronous and blocks
  - Blocking the event loop prevents any async operations from completing
  - Even `await loop.run_in_executor()` doesn't fully solve it due to connection pool thread safety
- **Solution**: Convert endpoint from `async def` to `def` (synchronous)
```python
# ❌ Wrong: Async endpoint with sync database pool
@app.post("/api/process-urls")
async def process_urls():
    conn = get_output_connection()  # Blocks event loop!

# ✅ Correct: Synchronous endpoint
@app.post("/api/process-urls")
def process_urls():
    conn = get_output_connection()  # No event loop blocking
```
- **Alternative**: Use async-compatible driver (asyncpg) if async is required, but adds complexity
- **Impact**: Immediate fix - endpoint processes multiple batches successfully
- **Location**: backend/main.py (line 181), backend/database.py (connection pool functions)
- **Date**: 2025-10-23

### Redshift executemany() Blocking Indefinitely
- **Problem**: Second API request hangs at "[POOL] Getting Redshift connection..." - connection pool exhaustion
- **Symptoms**:
  - First request succeeds and completes
  - Second request waits forever for a Redshift connection
  - Logs show "Got Redshift connection" but never "Returned Redshift connection"
  - Connection pool exhausted (maxconn=5, all connections stuck)
- **Root Cause**: Redshift doesn't handle `executemany()` well with INSERT/UPDATE statements
  - Batch operations block indefinitely
  - Connection never completes transaction
  - Connection never returned to pool
  - Subsequent requests wait forever for available connection
- **Solution**: Replace all `executemany()` calls with individual `execute()` loops
```python
# ❌ Wrong: Blocks indefinitely on Redshift
if insert_content_data:
    output_cur.executemany("""
        INSERT INTO pa.content_urls_joep (url, content)
        VALUES (%s, %s)
    """, insert_content_data)

# ✅ Correct: Individual executes
if insert_content_data:
    print(f"[ENDPOINT] Inserting {len(insert_content_data)} content records...")
    for url, content in insert_content_data:
        output_cur.execute("""
            INSERT INTO pa.content_urls_joep (url, content)
            VALUES (%s, %s)
        """, (url, content))
    print(f"[ENDPOINT] Content inserts complete")
```
- **Performance**: Slightly slower than executemany() but actually completes (vs hanging forever)
- **Note**: executemany() works fine on PostgreSQL, only Redshift has this issue
- **Testing**: Verified 3 sequential requests complete successfully after fix
- **Location**: backend/main.py (lines 286-315)
- **Date**: 2025-10-23

### Redshift SQL Differences - ON CONFLICT Not Supported
- **Problem**: URL upload fails with syntax error: "syntax error at or near 'ON'"
- **Cause**: PostgreSQL's `ON CONFLICT DO NOTHING` syntax not supported by Redshift
- **Impact**: Cannot use INSERT ... ON CONFLICT for duplicate handling in Redshift
- **Solution**: Use batch checking strategy instead:
  1. Query existing URLs with WHERE IN (batches of 500)
  2. Filter duplicates in Python using set difference
  3. Batch insert only new URLs with executemany()
- **Example**:
```python
# Get existing URLs in batches
existing_urls = set()
batch_size = 500
for i in range(0, len(urls), batch_size):
    batch = urls[i:i + batch_size]
    placeholders = ','.join(['%s'] * len(batch))
    cur.execute(f"SELECT url FROM table WHERE url IN ({placeholders})", batch)
    existing_urls.update(row['url'] for row in cur.fetchall())

# Filter and insert new URLs
new_urls = [(url,) for url in urls if url not in existing_urls]
cur.executemany("INSERT INTO table (url) VALUES (%s)", new_urls)
```
- **Performance**: Batching queries (500 URLs per query) keeps Redshift queries fast
- **Location**: backend/main.py - `/api/upload-urls` endpoint (lines 463-542)
- **Date**: 2025-10-21

### Data Consistency Issue: Local Content Not Synced to Redshift
- **Problem**: 69,391 URLs had content locally, but only 60,000 had kopteksten=1 in Redshift (9,567 URLs out of sync)
- **Cause**: Batch processing completed locally but Redshift updates were lost or incomplete due to:
  - Network interruptions during batch commits
  - Interrupted processing sessions before Redshift sync
  - Failed Redshift UPDATE operations (silent failures)
- **Symptoms**:
  - System shows 50k+ pending URLs but only processes 24 per batch
  - Filtering logic excludes URLs that have local content but kopteksten=0 in Redshift
  - Progress stalls despite thousands of "pending" URLs
  - Status counts don't match actual content count
- **Impact**: URLs with completed content stuck in pending state, wasting processing cycles
- **Solution**: Created `backend/sync_redshift_flags.py` script to sync local content with Redshift
  - Queries `pa.content_urls_joep` (local content table - source of truth)
  - Updates Redshift `kopteksten=1` for all URLs with content
  - Batch updates (1000 URLs per query) for performance
  - Safe to run anytime (idempotent, only updates kopteksten=0 → kopteksten=1)
- **Script Usage**:
```bash
docker-compose exec -T app python -m backend.sync_redshift_flags
```
- **Result**: Synced 9,567 URLs, pending count dropped from 50,345 to 40,754 (accurate)
- **Prevention**: Run sync script after interrupted sessions or if progress stalls
- **Location**: backend/sync_redshift_flags.py, backend/main.py (filtering logic updated)
- **Date**: 2025-10-22

### Frontend Showing NaN/undefined in Batch Progress
- **Problem**: Frontend displays "Batch 1 Complete: undefined successful, NaN failed/skipped" during batch processing
- **Cause**: JavaScript directly using `data.processed` and `data.total_attempted` without null/undefined checks
- **Symptoms**:
  - Progress text shows "undefined" and "NaN" instead of numbers
  - Happens when API response has missing or undefined fields
  - Calculations like `total_attempted - processed` produce NaN
- **Solution**: Add default values using || operator:
```javascript
const batchProcessed = data.processed || 0;
const batchTotal = data.total_attempted || 0;
const batchFailed = batchTotal - batchProcessed;
```
- **Benefits**: Safe handling of undefined/null values, always displays valid numbers
- **Location**: frontend/js/app.js (lines 219-242)
- **Date**: 2025-10-22

### Beslist.nl Hidden 503 Errors in HTML Body
- **Problem**: Scraper marks URLs as "no_products_found" when actually rate limited
- **Cause**: Beslist.nl returns HTTP 200 status with "503 Service Unavailable" in HTML body when rate limited
- **Impact**: 33,946 URLs incorrectly marked as failed/skipped due to undetected rate limiting
- **Detection**:
```python
if response.status_code == 200:
    # Check for hidden 503 in HTML body
    if '503' in response.text or 'Service Unavailable' in response.text:
        print(f"Scraping failed: Hidden 503 (rate limited) for {url}")
        return None  # Keep URL in pending for retry
```
- **Behavior**: Returning None from scraper keeps URL in pending state (not marked as processed)
- **Location**: backend/scraper_service.py (lines 119-123)
- **Date**: 2025-10-21

### Docker Network Connectivity Loss After Restart
- **Problem**: After restarting Docker, all network connections from container timeout (ping, DNS, HTTP requests)
- **Symptoms**:
  - `docker-compose exec -T app python3 -c "requests.get('https://beslist.nl')"` hangs/times out
  - Even basic commands fail: `ping 8.8.8.8` times out
  - DNS lookups fail: `nslookup beslist.nl` times out
  - Scraper returns "scraping_failed" for all URLs
- **Root Cause Options**:
  1. **Proxy environment variables**: `HTTP_PROXY`/`HTTPS_PROXY` in docker-compose.yml pointing to invalid/inaccessible proxy
  2. **VPN routing issues**: VPN split tunneling configuration broken after Docker restart
  3. **WSL2 network bridge**: WSL2 network adapter needs refresh after Docker restart
- **Diagnostic Commands**:
```bash
# Test from host (should work)
curl -A "Beslist script voor SEO" https://www.beslist.nl/

# Test from container (fails if network broken)
docker-compose exec -T app sh -c "ping -c 2 8.8.8.8"
docker-compose exec -T app sh -c "nslookup beslist.nl"
```
- **Solutions** (try in order):
  1. **WSL restart** (fixes most issues): `wsl --shutdown` from Windows PowerShell, then restart WSL terminal
  2. **Check/unset proxy variables**:
```bash
echo $HTTP_PROXY $HTTPS_PROXY  # Check if set
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
docker-compose down && docker-compose up -d
```
  3. **Remove proxy from docker-compose.yml**: Change `- HTTP_PROXY=${HTTP_PROXY:-}` to `- HTTP_PROXY=`
  4. **Check VPN configuration**: Verify VPN split tunneling still routes beslist.nl traffic correctly
- **Prevention**: After restarting Docker, always test basic connectivity before processing URLs
- **Location**: docker-compose.yml (lines 23-24), network configuration
- **Date**: 2025-10-21

### Port Conflicts
- FastAPI on 8003 (external) → 8000 (internal container port)
- PostgreSQL on 5433 (not 5432) for same reason
- Frontend accessible at http://localhost:8003/static/index.html

### CORS Errors
- Check `allow_origins` in main.py
- For dev: use `["*"]`
- For production: specify exact frontend URL

### Database Connection
- Wait for PostgreSQL to fully start
- Check DATABASE_URL in .env
- Run `docker-compose logs db` to debug

### Database Schema Column Missing
- **Error**: `column "status" does not exist`
- **Cause**: Schema changes applied to wrong database (postgres vs content_top)
- **Solution**: Check DATABASE_URL in docker-compose.yml, apply schema to correct database
- **Command**: `docker-compose exec -T db psql -U postgres -d content_top < backend/schema.sql`

### Pending Count Not Decreasing After Processing (UPDATED 2025-10-22)
- **Problem**: Pending count stays static at 11,756 even after processing 100 URLs, system shows "No URLs to process"
- **Root Cause**: Skipped and failed URLs were:
  1. ✅ Written to local PostgreSQL tracking table (pa.jvs_seo_werkvoorraad_kopteksten_check)
  2. ❌ **NOT updating the Redshift kopteksten flag** (pa.jvs_seo_werkvoorraad_shopping_season)
- **Symptoms**:
  - Redshift kept showing URLs as unprocessed (kopteksten=0)
  - System fetched same URLs repeatedly
  - Immediately filtered them out (already in local tracking)
  - Result: "No URLs to process" despite 11,756 pending
  - Pending count calculation: total_urls - tracked = constant (never decreases)
- **Impact**: URLs stuck in infinite loop, no progress possible
- **Solution (2025-10-20)**: Add `redshift_ops.append(('update_werkvoorraad', url))` for permanent failures:
  - no_products_found (line 86) - Page loads but has no products
  - no_valid_links (line 111) - AI generates content without valid links
  - ai_generation_error (line 127) - AI service error
- **Solution (2025-10-21)**: **REMOVED** Redshift update for scraping failures:
  - scraping_failed (line 79) - Network errors, 503, timeouts, access denied
  - **Reason**: Temporary network/access issues should be retried, not marked as permanently processed
  - **Behavior**: URLs with scraping failures stay in pending, can be retried on next run
  - **Status**: Local tracking still records 'failed' status for monitoring
- **Solution (2025-10-22)**: **Three-state tracking system** + **503-specific handling**:
  - kopteksten=0: Pending (not yet processed)
  - kopteksten=1: Has content (successfully processed)
  - kopteksten=2: Processed without content (skipped/failed non-503 errors)
  - **503 errors (rate_limited_503)**: NOT marked in Redshift, kept pending for retry, batch stops immediately
  - **Local tracking query changed**: Now filters ALL processed URLs (not just successful), preventing infinite retry loop
- **Result**:
  - Permanent failures (no products, bad content) → kopteksten=2 in Redshift
  - Successful content → kopteksten=1 in Redshift
  - 503 rate limiting → kopteksten=0 (stays pending), batch stops immediately
  - Non-503 scraping failures → kopteksten=2 (won't retry)
- **Location**: backend/main.py (lines 73-135, 247-260), backend/scraper_service.py (returns {'error': '503'})

### Frontend Showing N/A for Timestamps from Redshift
- **Problem**: Recent Results section showed "N/A" timestamps because Redshift output table (pa.content_urls_joep) lacks created_at column
- **Cause**: Redshift table schema doesn't include timestamp columns, but frontend expected created_at field
- **Symptoms**:
  - API returns `"created_at": null` for all recent results
  - Frontend displays "N/A" next to every URL
  - Local PostgreSQL has timestamps but Redshift doesn't
- **Solution Options**:
  1. **Query local PostgreSQL for timestamps** (implemented): Use separate connection to local database for recent results with timestamps
  2. **Hide timestamps in UI** (implemented): Conditionally render timestamp element only when data available
  3. **Add created_at to Redshift** (not implemented): Requires Redshift schema change and backfill
- **Implementation**:
```python
# Backend: Query local PostgreSQL for timestamps
try:
    local_conn = get_db_connection()  # Local PostgreSQL
    local_cur = local_conn.cursor()
    local_cur.execute("SELECT url, content, created_at FROM pa.content_urls_joep ORDER BY created_at DESC LIMIT 5")
    recent = [{'url': r['url'], 'content': r['content'], 'created_at': r['created_at'].isoformat() if r['created_at'] else None} for r in local_cur.fetchall()]
except:
    # Fallback: Query Redshift without timestamps
    recent = [{'url': r['url'], 'content': r['content'], 'created_at': None} for r in output_cur.fetchall()]
```
```javascript
// Frontend: Hide timestamp when null
const dateText = item.created_at ? new Date(item.created_at).toLocaleString() : '';
itemDiv.innerHTML = `
    <h6>${item.url}</h6>
    ${dateText ? `<small>${dateText}</small>` : ''}  // Only render if available
`;
```
- **Location**: backend/main.py (lines 333-361), frontend/js/app.js (lines 312-322)

### OpenAI httpx Compatibility
- **Error**: `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`
- **Cause**: OpenAI 1.35.0 incompatible with httpx >= 0.26.0
- **Solution**: Pin httpx==0.25.2 in requirements.txt

### Beslist.nl AWS WAF Challenge and User Agent Whitelisting
- **Problem**: Scraper returns "scraping_failed" for all URLs, but pages load fine in browser
- **Symptoms**:
  - `curl https://www.beslist.nl/...` returns AWS WAF "Human Verification" challenge page
  - Same URL with user agent `"Beslist script voor SEO"` returns actual HTML content
  - Without correct user agent: `<title>Human Verification</title>` and AWS WAF JavaScript challenge
  - With correct user agent: `<title>Ellen boren goedkoop kopen? | Beste aanbiedingen | beslist.nl</title>`
- **Root Cause**: Beslist.nl uses AWS WAF (Web Application Firewall) with:
  1. **User agent whitelisting**: Only allows specific user agents to bypass bot protection
  2. **JavaScript challenge**: Presents CAPTCHA/challenge for unrecognized bots
- **Whitelist Details**:
  - **User Agent**: `"Beslist script voor SEO"` (whitelisted)
  - **IP Address**: 87.212.193.148 (whitelisted, but user agent is primary authentication)
- **Testing**:
```bash
# Without user agent (gets WAF challenge)
curl https://www.beslist.nl/products/... | head -c 200
# Returns: <!DOCTYPE html><html lang="en"><head><title>Human Verification</title>

# With whitelisted user agent (gets actual page)
curl -A "Beslist script voor SEO" https://www.beslist.nl/products/... | head -c 200
# Returns: <!DOCTYPE html><html lang=nl-NL><head><title>Ellen boren goedkoop kopen?
```
- **Solution**: Ensure scraper uses correct user agent `"Beslist script voor SEO"`
- **Verification**: Check `USER_AGENT` constant in backend/scraper_service.py (line 11)
- **Important**: User agent authentication works regardless of IP address (confirmed working from 94.142.210.226, not just 87.212.193.148)
- **Location**: backend/scraper_service.py (line 11, 87)
- **Date**: 2025-10-21

### AI Generating Long Hyperlink Text
- **Problem**: AI generates very long anchor text (e.g., full product names with specifications like "Beeztees kattentuigje Hearts zwart 120 x 1 cm")
- **Cause**: Prompt instructions were vague about link text length
- **Solution**: Update GPT prompt with explicit constraints: "KORTE, heldere omschrijving (max 3-5 woorden)" with concrete example
- **Example**: "Beeztees kattentuigje Hearts zwart 120 x 1 cm" → "Beeztees kattentuigje Hearts"
- **Location**: backend/gpt_service.py - both system message and user prompt

### Browser Cache Not Showing Updated JavaScript
- **Issue**: JavaScript changes not visible in browser after editing
- **Cause**: Browser caches static files (CSS/JS) aggressively
- **Solution**: Hard refresh to bypass cache
  - Windows/Linux: Ctrl + Shift + R or Ctrl + F5
  - Mac: Cmd + Shift + R

### Browser Auto-Linking HTML Tags in Template Literals
- **Problem**: When inserting HTML content via template literals, browser auto-links HTML tags (e.g., `</div>` becomes a clickable link)
- **Cause**: Inserting raw HTML with `<a href>` tags directly into template literals like `${content}` causes browser to parse ALL text including the subsequent HTML tags as potential URLs
- **Solution**: Create DOM structure first with empty placeholders, then insert HTML content separately via `innerHTML`
- **Example**:
```javascript
// ❌ Wrong: Browser auto-links HTML tags
html += `<div>${content}</div>`;

// ✅ Correct: Insert HTML separately
const div = document.createElement('div');
div.innerHTML = content;
```
- **Location**: frontend/js/app.js - refreshStatus() function

### Windows File Paths Not Accessible from Docker Container
- **Problem**: Docker container cannot access Windows file paths like `C:/Users/...` or `/mnt/c/Users/...`
- **Cause**: Container has isolated filesystem, Windows paths are not mounted by default
- **Solution**: Copy file into container using `docker cp`, then run script
- **Example**:
```bash
# Copy CSV from Windows to container
docker cp /mnt/c/Users/JoepvanSchagen/Downloads/file.csv content_top_app:/app/file.csv

# Run Python script in container
docker-compose exec app python -m backend.import_content
```
- **Location**: CSV import workflow for bulk content upload

### Cloudflare Rate Limit Testing with Whitelisted IP
- **Problem**: Need to determine optimal scraping rate for whitelisted IP (87.212.193.148)
- **Testing Methodology**: Progressive speed testing from conservative (1.0-1.3s) to aggressive (0s burst mode)
- **Test Results**:
  - 1.0-1.3s delay: 100% success (10 URLs)
  - 0.5-0.7s delay: 100% success (10 URLs)
  - 0.3-0.5s delay: 100% success (10 URLs)
  - 0.1-0.3s delay: 100% success (10 URLs)
  - 0.05s delay: 100% success (15 URLs)
  - 0.02s delay: 100% success (15 URLs)
  - 0.01s delay: 100% success (15 URLs)
  - 0s delay (burst mode): 100% success (15 URLs)
- **Key Finding**: Whitelisted IP has NO rate limiting from Cloudflare, even at burst mode
- **Recommended Delays**:
  - **Optimized Mode** (default): 0.2-0.3s delay (~3-5 URLs/sec) - balanced speed with minimal risk
  - **Conservative Mode**: 0.5-0.7s delay (~2 URLs/sec) with 1 worker only - maximum safety for cautious operation
- **Implementation**: Two modes available via `conservative_mode` parameter and frontend checkbox
- **Location**: backend/scraper_service.py (lines 70-82), backend/main.py (conservative_mode enforcement)

### Custom User Agent for Scraper Identification
- **Problem**: Need to identify scraper traffic in server logs for debugging and traffic analysis
- **Solution**: Set custom user agent string that describes the scraper purpose
- **Implementation**: Define `USER_AGENT` constant at top of scraper service with descriptive string
- **Example**: `USER_AGENT = "Beslist script voor SEO"` instead of generic browser user agent
- **Benefits**:
  - Easier to filter and analyze scraper traffic in server logs
  - Clear identification for IT/operations teams
  - Distinguishes scraper from regular browser traffic
  - Helps with debugging rate limiting or blocking issues
- **Location**: backend/scraper_service.py (line 11)

## Git Commands
```bash
# SSH Setup
ssh-keygen -t ed25519 -C "your@email.com"  # Generate SSH key
cat ~/.ssh/id_ed25519.pub                   # Display public key (add to GitHub)
ssh -T git@github.com                       # Test GitHub connection

# Repository Setup
git init                                    # Initialize repository
git remote add origin git@github.com:user/repo.git
git branch -M main                          # Rename branch to main
git push -u origin main                     # Push to GitHub

# Configuration
git config user.name "username"
git config user.email "email@example.com"
```

## Project Patterns

### No Build Tools Benefits
- Edit HTML/CSS/JS → Save → Refresh browser
- No npm install delays
- No webpack configuration
- No node_modules folder (saves 500MB+)
- Works identically on any machine with Docker

### Real-time Progress Tracking with Polling
- **Pattern**: JavaScript polls API endpoint every 2 seconds for status updates
- **Benefit**: Live progress updates without WebSockets complexity
- **Example**: Poll `/api/status`, update progress bar, auto-stop when complete
```javascript
pollInterval = setInterval(updateJobStatus, 2000);
if (status === 'completed') clearInterval(pollInterval);
```

### Multi-Stage Docker Builds
- **Pattern**: Separate builder stage (with gcc, build tools) from runtime stage
- **Benefit**: Smaller final image (build dependencies not included)
- **Example**: Builder installs Python packages, final stage only copies venv
```dockerfile
FROM python:3.11-slim as builder
RUN apt-get install gcc && pip install -r requirements.txt

FROM python:3.11-slim
COPY --from=builder /opt/venv /opt/venv
```

### Environment Variable Management
- **Pattern**: Use python-dotenv for configuration
- **Benefit**: Secure secrets, reusable configuration, safe for version control
- **Example**: Load from .env file at startup
```python
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Use environment variables
api_key = os.getenv("OPENAI_API_KEY")
```

### Choosing Synchronous vs Async Endpoints in FastAPI
- **Pattern**: Use synchronous endpoints when working with synchronous database drivers
- **Use Case**: Endpoints that perform database operations with psycopg2 (synchronous driver)
- **Rule of Thumb**:
  - **Use `def` (sync)**: When using synchronous libraries (psycopg2, most database drivers)
  - **Use `async def`**: When using async-compatible libraries (httpx, aiofiles, asyncpg)
- **Why It Matters**: Async endpoints with sync operations block the event loop, causing hangs and deadlocks
- **Implementation**:
```python
# ✅ Correct: Sync endpoint with sync database driver
@app.post("/api/process-urls")
def process_urls(batch_size: int = 10):
    conn = get_db_connection()  # psycopg2 - synchronous
    # ... database operations ...
    return_db_connection(conn)
    return {"status": "success"}

# ✅ Also correct: Async endpoint with async operations
@app.get("/api/external-data")
async def fetch_external():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com")
    return response.json()

# ❌ Wrong: Async endpoint with sync database
@app.post("/api/process-urls")
async def process_urls():
    conn = get_db_connection()  # Blocks event loop!
```
- **Migration Path**: If you need async with databases:
  1. Switch to async driver (asyncpg for PostgreSQL)
  2. Update all database calls to use `await`
  3. Update connection pool to async pool
- **Performance Note**: Sync endpoints are perfectly fine for most use cases and often simpler to reason about
- **Location**: backend/main.py - all endpoints (converted to sync on 2025-10-23)
- **Date**: 2025-10-23

### Debugging Connection Pool Issues with Detailed Logging
- **Pattern**: Add detailed logging at each connection lifecycle step to identify pool exhaustion or blocking
- **Use Case**: Debugging why database connections hang, aren't returned, or pool is exhausted
- **Implementation**:
```python
def get_db_connection():
    """Get connection from pool"""
    pool = _get_pg_pool()
    print(f"[POOL] Getting PG connection...")
    conn = pool.getconn()
    print(f"[POOL] Got PG connection")
    return conn

def return_db_connection(conn):
    """Return connection to pool"""
    if conn:
        pool = _get_pg_pool()
        print(f"[POOL] Returning PG connection...")
        pool.putconn(conn)
        print(f"[POOL] Returned PG connection")
```
- **Benefits**:
  - Quickly identify where connections get stuck (e.g., "Getting..." but never "Got...")
  - See if connections are being returned (look for "Returned" logs)
  - Track connection lifecycle across requests
  - Diagnose pool exhaustion (multiple "Getting..." with no "Got...")
- **Debugging Workflow**:
  1. Add detailed logs to all connection get/return functions
  2. Run failing request
  3. Check logs for incomplete lifecycles
  4. Identify where connection is stuck or not returned
- **Example Debug Output**:
```
[POOL] Getting PG connection...
[POOL] Got PG connection
[ENDPOINT] Processing 2 URLs...
[POOL] Getting Redshift connection...
[POOL] Got Redshift connection
[ENDPOINT] Inserting 2 content records...
[ENDPOINT] Content inserts complete
[POOL] Returned Redshift connection
[POOL] Returned PG connection
```
- **Location**: backend/database.py (lines 44-98)
- **Date**: 2025-10-23

### Custom Slash Commands for Permission Management
- **Pattern**: Create markdown files in .claude/commands/ for frequently used operations
- **Use Case**: Quick toggles for Claude Code settings without manual file editing
- **Benefit**: Simple one-command access to complex configuration changes
- **Implementation**:
  1. Create `.claude/commands/` directory
  2. Add markdown files with plain text instructions (e.g., `skip-permissions.md`)
  3. Claude Code executes the instructions when command is invoked
- **Example Commands**:
  - `/skip-permissions`: Set `defaultMode` to `bypassPermissions` in `.claude/settings.local.json`
  - `/restore-permissions`: Set `defaultMode` back to `default`
- **Benefits**:
  - No need to remember file paths or JSON syntax
  - Consistent execution across team members
  - Self-documenting through command names
- **Location**: `.claude/commands/*.md`

### Project Separation Strategy
- **Pattern**: Separate distinct projects into independent repositories
- **Benefit**: Clean git history, independent versioning, easier management
- **Example**: content_top (SEO) and theme_ads (Google Ads) as separate repos
- **Implementation**:
  1. Identify files by project domain
  2. Clean backend to remove cross-project dependencies
  3. Update docker-compose and .gitignore
  4. Create new repository for separated project
  5. Copy files and create independent git history

### Parallel URL Processing with ThreadPoolExecutor
- **Pattern**: Process multiple URLs concurrently using Python's ThreadPoolExecutor
- **Benefit**: Significant speed improvement for I/O-bound tasks (scraping + AI)
- **Implementation**: Each worker gets own DB connection, configurable 1-10 workers
```python
with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
    results = list(executor.map(process_single_url, urls))
```

### Handling Hybrid Database Schema Differences (Timestamps)
- **Problem**: Hybrid architecture (PostgreSQL + Redshift) where output table exists in both databases, but Redshift table lacks created_at column
- **Use Case**: Displaying recent results with timestamps when Redshift is primary output destination
- **Solution**: Query local PostgreSQL for recent results with timestamps as fallback
- **Implementation**:
  1. Check if output connection is Redshift or PostgreSQL
  2. For Redshift: Query local PostgreSQL connection separately for timestamp data
  3. Handle gracefully when timestamps unavailable (set to None)
  4. Frontend conditionally displays timestamps only when available
- **Benefits**:
  - Works with schema differences between databases
  - Graceful degradation when timestamps unavailable
  - No need to modify Redshift schema
  - Users see timestamps when possible, clean UI when not
- **Example**:
```python
# Always query local PostgreSQL for timestamps
try:
    local_conn = get_db_connection()
    local_cur = local_conn.cursor()
    local_cur.execute("SELECT url, content, created_at FROM pa.content_urls_joep ORDER BY created_at DESC LIMIT 5")
    recent_rows = local_cur.fetchall()
    recent = [{'url': r['url'], 'content': r['content'], 'created_at': r['created_at'].isoformat() if r.get('created_at') else None} for r in recent_rows]
except Exception as e:
    # Fallback to output connection without timestamps
    output_cur.execute("SELECT url, content FROM pa.content_urls_joep LIMIT 5")
    recent = [{'url': r['url'], 'content': r['content'], 'created_at': None} for r in output_cur.fetchall()]
```
- **Location**: backend/main.py (lines 333-361)

### Conditional UI Element Display Based on Data Availability
- **Pattern**: Hide UI elements when data is unavailable instead of showing placeholder text like "N/A"
- **Use Case**: Timestamps, optional metadata, or any field that may not always be present
- **Benefits**:
  - Cleaner user interface
  - Avoids confusing users with "N/A" or "null" text
  - Dynamic layout adjusts to available data
- **Implementation**:
```javascript
// Check for data availability
const dateText = item.created_at ? new Date(item.created_at).toLocaleString() : '';

// Conditionally render element
itemDiv.innerHTML = `
    <h6 style="${dateText ? 'max-width: 85%;' : ''}">${item.url}</h6>
    ${dateText ? `<small>${dateText}</small>` : ''}
`;
```
- **Alternative Approaches**:
  - CSS display: none (requires extra DOM elements)
  - React conditional rendering (not applicable for vanilla JS)
- **Location**: frontend/js/app.js (lines 312-322)

### Database Cleanup and State Reset Workflow
- **Pattern**: When removing bad AI-generated results, follow 4-step process to ensure clean state
- **Use Case**: Removing results with quality issues (e.g., long hyperlinks) and reprocessing
- **Steps**:
  1. Re-add URLs to pending queue: `INSERT INTO pa.jvs_seo_werkvoorraad ... ON CONFLICT (url) DO NOTHING`
  2. Remove from tracking table: `DELETE FROM pa.jvs_seo_werkvoorraad_kopteksten_check WHERE url IN (...)`
  3. Delete bad results: `DELETE FROM pa.content_urls_joep WHERE url IN (...)`
  4. Reset kopteksten flag: `UPDATE pa.jvs_seo_werkvoorraad SET kopteksten = 0 WHERE url IN (...)`
- **Benefit**: Ensures URLs can be reprocessed without duplicates or state conflicts
- **Important**: Use transactions (BEGIN/COMMIT) to ensure atomicity

### Database Query Performance - Avoiding NOT IN with Large Datasets
- **Problem**: Query timeout on status endpoint with 75,858 URLs (30+ seconds → timeout)
- **Cause**: `NOT IN (SELECT url FROM table)` performs poorly on large datasets (75k+ rows)
- **Solution**: Replace with `LEFT JOIN ... WHERE IS NULL` pattern
- **Performance**: Query time reduced from 30+ seconds to <100ms
- **Example**:
```sql
-- ❌ Slow: NOT IN subquery (75k rows = timeout)
SELECT COUNT(*) FROM pa.jvs_seo_werkvoorraad
WHERE url NOT IN (SELECT url FROM pa.jvs_seo_werkvoorraad_kopteksten_check);

-- ✅ Fast: LEFT JOIN pattern (<100ms)
SELECT COUNT(*)
FROM pa.jvs_seo_werkvoorraad w
LEFT JOIN pa.jvs_seo_werkvoorraad_kopteksten_check c ON w.url = c.url
WHERE c.url IS NULL;
```
- **Additional Optimization**: Add index on frequently filtered columns (e.g., `CREATE INDEX idx_kopteksten_check_status ON pa.jvs_seo_werkvoorraad_kopteksten_check(status)`)
- **Location**: backend/main.py - `/api/status` endpoint

### CSV Export with Proper Encoding and Formatting
- **Pattern**: Export database content to CSV with UTF-8 encoding and proper newline handling
- **Use Case**: Exporting AI-generated content that contains HTML, special characters, and multiline text
- **Implementation**:
  1. Add UTF-8 BOM (`\ufeff`) for Excel compatibility
  2. Strip newlines from content fields to prevent row breaks: `content.replace('\n', ' ').replace('\r', ' ')`
  3. Use `csv.QUOTE_ALL` to properly escape special characters
  4. Use `BytesIO` for binary output with UTF-8 encoding
  5. Set proper content type: `text/csv; charset=utf-8`
- **Benefits**:
  - No empty rows in exported CSV
  - Proper UTF-8 character display (fixes "geÃ¯" → "geï")
  - Excel opens file correctly without import wizard
- **Example**:
```python
from io import StringIO, BytesIO
import csv

output = BytesIO()
output.write('\ufeff'.encode('utf-8'))  # UTF-8 BOM

text_output = StringIO()
writer = csv.writer(text_output, quoting=csv.QUOTE_ALL, lineterminator='\n')
writer.writerow(['url', 'content'])

for row in rows:
    content = row['content'].replace('\n', ' ').replace('\r', ' ') if row['content'] else ''
    writer.writerow([row['url'], content])

output.write(text_output.getvalue().encode('utf-8'))
```
- **Location**: backend/main.py - `/api/export/csv` endpoint

### CSV Import for Bulk Content Upload
- **Pattern**: Import pre-generated content from CSV with semicolon delimiters and UTF-8 BOM
- **Use Case**: Bulk upload of AI-generated content (e.g., 19,791 items) from external sources
- **Implementation**:
  1. Read CSV with UTF-8-sig encoding (auto-strips BOM)
  2. Use semicolon (`;`) as delimiter for compatibility
  3. Extract `url` and `content_top` columns
  4. Insert into three tables atomically:
     - `pa.jvs_seo_werkvoorraad` - mark as processed (`kopteksten = 1`)
     - `pa.content_urls_joep` - store generated content
     - `pa.jvs_seo_werkvoorraad_kopteksten_check` - track as success
  5. Use `ON CONFLICT DO NOTHING` to skip duplicates
  6. Commit every 100 rows for progress tracking
- **Benefits**:
  - Handles large files (19k+ rows) efficiently
  - Transactional safety with periodic commits
  - Progress reporting during import
  - Skips duplicates automatically
- **Example**:
```python
import csv

with open(csv_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        url = row['url'].strip()
        content = row['content_top'].strip()

        # Insert into work queue (mark as processed)
        cur.execute("INSERT INTO pa.jvs_seo_werkvoorraad (url, kopteksten) VALUES (%s, 1) ON CONFLICT (url) DO UPDATE SET kopteksten = 1", (url,))

        # Insert content
        cur.execute("INSERT INTO pa.content_urls_joep (url, content) VALUES (%s, %s) ON CONFLICT DO NOTHING", (url, content))

        # Track as success
        cur.execute("INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url, status) VALUES (%s, 'success') ON CONFLICT DO NOTHING", (url,))
```
- **Location**: backend/import_content.py

### Hybrid Database Architecture (Local PostgreSQL + Cloud Redshift)
- **Pattern**: Split database responsibilities between local PostgreSQL and cloud Redshift
- **Use Case**: Large-scale data processing where some tables benefit from cloud storage
- **Architecture**:
  - **Local PostgreSQL**: Fast tracking tables (processing status, temporary data)
  - **Redshift**: Persistent data tables (work queue, generated content)
- **Implementation**:
  1. Create separate connection functions: `get_db_connection()` (local), `get_redshift_connection()` (cloud), `get_output_connection()` (smart router)
  2. Route operations based on table purpose: tracking → local, data → Redshift
  3. Handle schema differences (e.g., Redshift table has no `created_at` column)
  4. Sync operations across both databases (delete from both, update in Redshift + track locally)
- **Benefits**:
  - Local tracking is fast (no network latency)
  - Centralized data in Redshift (accessible to other systems)
  - Can scale independently (add Redshift replicas without affecting local operations)
  - Redshift optimized for large datasets (166K+ URLs)
- **Environment Variables**:
  ```bash
  # Redshift configuration
  USE_REDSHIFT_OUTPUT=true
  REDSHIFT_HOST=production-redshift.amazonaws.com
  REDSHIFT_PORT=5439
  REDSHIFT_DB=database_name
  REDSHIFT_USER=username
  REDSHIFT_PASSWORD=password
  ```
- **Important**: Redshift credentials should be in `.gitignore` (use separate config file)
- **Location**: backend/database.py (lines 12-29), backend/main.py (throughout)

### Hyperlink Validation with Status Code Checking
- **Pattern**: Validate hyperlinks in generated content by checking HTTP status codes (301/404)
- **Use Case**: Quality control for AI-generated content - detect broken product links
- **Implementation**:
  1. Extract all `<a href>` tags from HTML content using BeautifulSoup
  2. Prepend base domain (`https://www.beslist.nl`) to relative URLs
  3. Check HTTP status with `requests.head()` (faster than GET)
  4. Parallel processing with ThreadPoolExecutor for speed
  5. If broken links found (301/404), auto-reset content to pending for regeneration
  6. Store validation results in JSONB column for audit trail
  7. Skip URLs already validated (LEFT JOIN check)
  8. Reset validation history when needed via DELETE endpoint
- **Benefits**:
  - Automated quality control for product links
  - Parallel validation speeds up large batches
  - Historical tracking of broken links
  - Auto-recovery workflow (reset to pending)
  - Incremental validation - only checks unvalidated URLs
  - Can reset and re-validate all URLs when needed
- **Example**:
```python
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor

def validate_content_links(content):
    soup = BeautifulSoup(content, 'html.parser')
    links = [link['href'] for link in soup.find_all('a', href=True) if link['href'].startswith('/')]

    broken_links = []
    for link in links:
        full_url = 'https://www.beslist.nl' + link
        response = requests.head(full_url, allow_redirects=False, timeout=10)
        if response.status_code in [301, 404]:
            broken_links.append({'url': link, 'status_code': response.status_code})

    return {'broken_links': broken_links, 'has_broken_links': len(broken_links) > 0}

# Parallel validation
with ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(validate_single_content, content_items))
```
- **Location**: backend/link_validator.py, backend/main.py - `/api/validate-links` endpoint

### CloudFront WAF Blocking Bot Traffic
- **Problem**: Website returns HTTP 403/405 errors for certain URLs when scraped
- **Cause**: CloudFront (AWS CDN) Web Application Firewall detecting automated traffic
- **Symptoms**:
  - Some category pages (e.g., `/products/accessoires/`) blocked regardless of User-Agent
  - Residential IP addresses more likely to be blocked than datacenter IPs
- **Troubleshooting**:
  1. Check public IP: `curl -s https://api.ipify.org`
  2. Test URL directly: `curl -I -A "User-Agent" "https://example.com"`
  3. Verify IP details: `curl -s https://ipinfo.io/YOUR_IP`
- **Solutions**:
  - Whitelist scraper IP in CloudFront WAF rules
  - Use slower request rates to avoid rate limiting
  - Contact IT department to adjust WAF settings
  - Consider using datacenter IPs instead of residential
- **Example**: IP `87.212.193.148` (Odido Netherlands residential FTTH) blocked by beslist.nl CloudFront

### VPN Routing Bypass for Whitelisted IP (Windows + WSL2/Docker)
- **Problem**: Company VPN routes all traffic through different IP, but scraper needs to use whitelisted IP (87.212.193.148) for beslist.nl
- **Scenario**:
  - Without VPN: Machine uses 87.212.193.148 (whitelisted)
  - With VPN: All traffic routes through 94.142.210.226 (not whitelisted)
  - Need: VPN connected for work (Redshift access), but scraper uses whitelisted IP
- **Failed Approaches**:
  1. OpenVPN client-side routing (`route X.X.X.X net_gateway`) - Error: "option 'route' cannot be used in this context [PUSH-OPTIONS]"
  2. OpenVPN `route-nopull` - `net_gateway` keyword doesn't work client-side
  3. OpenVPN `pull-filter ignore "redirect-gateway"` - VPN still captured CloudFront traffic
  4. Privoxy on Windows - Proxy itself routes through VPN
  5. Docker `network_mode: "host"` - Still uses VPN routing
- **Working Solution**: Windows Static Route with Lower Metric
  ```cmd
  # Step 1: Find your default gateway (before/during VPN)
  route print 0.0.0.0
  # Look for physical adapter (Ethernet/Wi-Fi), note Gateway IP (e.g., 192.168.1.1)

  # Step 2: Add persistent route with interface specification (as Administrator)
  route delete 65.9.0.0
  route add -p 65.9.0.0 mask 255.255.0.0 192.168.1.1 metric 1 if 10
  # Replace 192.168.1.1 with your gateway
  # Replace 10 with your Wi-Fi/Ethernet interface number from 'route print'

  # Step 3: Verify route is active
  route print 65.9.0.0
  # Should show metric 1 in Active Routes

  # Step 4: Restart WSL2 to pick up new routing
  # In PowerShell: wsl --shutdown
  # Then restart Docker Desktop
  ```
- **Why It Works**:
  - Windows routing is hierarchical: lower metric = higher priority
  - VPN routes typically have metric 25-50
  - Our route with metric 1 takes precedence for CloudFront IPs (65.9.0.0/16)
  - WSL2 and Docker inherit Windows routing table
  - Route is persistent (`-p` flag) - survives reboots
  - Interface specification (`if 10`) ensures it binds to physical adapter
- **Verification**:
  ```bash
  # From WSL2/Docker
  curl https://api.ipify.org          # Should show whitelisted IP
  curl https://www.beslist.nl/health  # Should show same IP
  ```
- **Result**: VPN stays connected, Redshift accessible, beslist.nl sees whitelisted IP (87.212.193.148)

### OpenVPN Split Tunneling Limitations on Windows Client
- **Problem**: Cannot configure OpenVPN split tunneling from client-side config file
- **Root Cause**: OpenVPN server pushes routes that override client-side directives
- **Why Client-Side Routes Fail**:
  1. `route X.X.X.X net_gateway` requires server push context - error: "cannot be used in this context [PUSH-OPTIONS]"
  2. `net_gateway` keyword only works in server-pushed routes, not client config
  3. `route-nopull` removes ALL routes including necessary internal network routes
  4. `pull-filter` can filter server options but Windows VPN adapter still captures traffic at OS level
- **Key Learning**: For corporate VPNs, split tunneling must be configured at:
  - **Server level** (requires admin/IT): Server pushes specific routes instead of redirect-gateway
  - **OS routing level** (can do yourself): Add Windows static routes with lower metric (see VPN Routing Bypass pattern above)
- **Alternative if Server-Side Split Tunneling Available**:
  - Server config: `push "route 10.0.0.0 255.0.0.0"` instead of `push "redirect-gateway def1"`
  - Client automatically gets split tunnel without config changes

### Privoxy Proxy Configuration for Docker/WSL2 Access
- **Problem**: Docker containers in WSL2 cannot connect to Privoxy running on Windows localhost
- **Cause**: Privoxy listens on 127.0.0.1:8118 by default, which only accepts local connections
- **Solution**: Configure Privoxy to accept connections from WSL2 network
  1. Edit Privoxy config file (usually `C:\Program Files\Privoxy\config.txt`)
  2. Change: `listen-address  127.0.0.1:8118`
  3. To: `listen-address  0.0.0.0:8118` (all interfaces) OR `listen-address  172.21.160.1:8118` (WSL2 gateway only)
  4. Restart Privoxy service
- **Finding WSL2 Gateway IP**: `ip route | grep default | awk '{print $3}'` (from WSL2, returns Windows host IP like 172.21.160.1)
- **Docker Proxy Config**:
  ```python
  session.proxies = {
      'http': 'http://172.21.160.1:8118',
      'https': 'http://172.21.160.1:8118'
  }
  ```
- **Note**: In this project, we ultimately used Windows static routing instead of Privoxy (more reliable)

### WSL2 IP Gateway Discovery
- **Problem**: Need to access Windows services (like Privoxy) from Docker containers running in WSL2
- **Solution**: Windows host is accessible via WSL2's default gateway IP
- **Command**: `ip route | grep default | awk '{print $3}'`
- **Example Output**: `172.21.160.1` (this is the Windows host IP from WSL2 perspective)
- **Common Use Cases**:
  - Connecting to Windows-hosted proxy servers
  - Accessing Windows file shares from containers
  - Connecting to Windows-hosted databases or services
- **Important**: This IP changes if network configuration changes, so don't hardcode in committed code

### Batch Database Operations for Performance
- **Problem**: Each URL processing makes 2 Redshift calls (INSERT content + UPDATE werkvoorraad), causing connection overhead
- **Impact**: With parallel workers, this creates many simultaneous Redshift connections (e.g., 10 workers × 2 calls = 20 connections)
- **Solution**: Batch Redshift operations after parallel processing completes
- **Implementation**:
  1. Modify worker function to return tuple: `(result_dict, redshift_operations)`
  2. Workers collect operations in list instead of executing: `redshift_ops.append(('insert_content', url, content))`
  3. After all workers complete, execute all operations in single transaction
  4. Use single Redshift connection for entire batch
- **Benefits**:
  - Reduces Redshift connections from N×2 (per URL) to 1 (per batch)
  - Improves throughput by 15-20% with parallel workers
  - Reduces connection overhead and network latency
  - Single transaction ensures atomicity for entire batch
- **Example**:
```python
# Worker function returns operations instead of executing
def process_single_url(url):
    redshift_ops = []
    # ... processing logic ...
    redshift_ops.append(('insert_content', url, content))
    redshift_ops.append(('update_werkvoorraad', url))
    return (result, redshift_ops)

# Batch execution after parallel processing
with ThreadPoolExecutor(max_workers=3) as executor:
    result_tuples = list(executor.map(process_single_url, urls))

# Collect all operations
all_redshift_ops = []
for result, ops in result_tuples:
    all_redshift_ops.extend(ops)

# Execute in single transaction
output_conn = get_output_connection()
output_cur = output_conn.cursor()
for op in all_redshift_ops:
    if op[0] == 'insert_content':
        output_cur.execute("INSERT INTO pa.content_urls_joep ...")
    elif op[0] == 'update_werkvoorraad':
        output_cur.execute("UPDATE pa.jvs_seo_werkvoorraad ...")
output_conn.commit()
```
- **Important Note (2025-10-23)**: Use individual `execute()` loops for Redshift, NOT `executemany()`
  - Redshift `executemany()` blocks indefinitely and never releases connections
  - PostgreSQL `executemany()` works fine
  - See "Redshift executemany() Blocking Indefinitely" error section for details
- **Location**: backend/main.py - `process_single_url()`, `process_urls()` endpoint

### Conservative Mode Pattern with ThreadPoolExecutor
- **Problem**: Need to pass additional parameters to worker functions when using ThreadPoolExecutor.map()
- **Use Case**: Conservative mode flag needs to be passed to each worker alongside the URL
- **Solution**: Use `functools.partial` to bind parameters before passing to executor
- **Implementation**:
```python
from functools import partial
from concurrent.futures import ThreadPoolExecutor

# Bind conservative_mode parameter to function
process_func = partial(process_single_url, conservative_mode=True)

# Pass partially-applied function to executor
with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
    results = list(executor.map(process_func, urls))
```
- **Benefits**:
  - Clean parameter passing without changing function signature
  - Worker function receives both url (from map) and conservative_mode (from partial)
  - No need for lambda or wrapper functions
- **Alternative Approaches Rejected**:
  - Lambda functions: More verbose and harder to read
  - Wrapper functions: Unnecessary code duplication
  - Tuple unpacking: Requires restructuring URL list
- **Location**: backend/main.py - `process_urls()` endpoint (lines 216-218)

### CSS Theme Override Pattern with Custom Properties
- **Problem**: Need to override Bootstrap default colors consistently across entire UI
- **Use Case**: Apply custom brand colors (#059CDF blue, #9C3095 purple, #A0D168 green) to match company branding
- **Solution**: CSS custom properties (CSS variables) with !important overrides
- **Implementation**:
```css
/* Define custom color palette */
:root {
    --color-primary: #059CDF;   /* Blue */
    --color-info: #9C3095;      /* Purple/Magenta */
    --color-success: #A0D168;   /* Green */
}

/* Override Bootstrap classes */
.bg-primary { background-color: var(--color-primary) !important; }
.btn-primary { background-color: var(--color-primary); border-color: var(--color-primary); }
.text-primary { color: var(--color-primary) !important; }

/* Include hover states (20% darker) */
.btn-primary:hover { background-color: #0480b3; border-color: #0480b3; }
```
- **Benefits**:
  - Single source of truth for color values (CSS variables)
  - No need to modify Bootstrap source files
  - Easy to maintain and update colors
  - Supports hover states and all Bootstrap color classes
  - !important ensures overrides work everywhere
- **Coverage**: Primary, Info, Success colors for buttons, badges, alerts, backgrounds, text, progress bars
- **Location**: frontend/css/style.css (lines 4-148)
- **Documentation**: ARCHITECTURE.md includes full color codes, usage map, and rationale

### Database Deduplication Strategy
- **Problem**: Content table had 48,846 duplicate records (108,722 total → 59,876 unique URLs)
- **Use Case**: After bulk imports or if multiple generation runs created duplicate content
- **Solution**: Use temporary table with ROW_NUMBER() window function to deduplicate
- **Implementation**:
```sql
-- Create temp table with deduplicated data
CREATE TEMP TABLE content_deduped AS
SELECT url, content
FROM (
    SELECT url, content,
           ROW_NUMBER() OVER (PARTITION BY url ORDER BY content) as rn
    FROM pa.content_urls_joep
)
WHERE rn = 1;

-- Replace original table
DELETE FROM pa.content_urls_joep;
INSERT INTO pa.content_urls_joep (url, content)
SELECT url, content FROM content_deduped;
```
- **Benefits**:
  - Handles large datasets efficiently (100K+ records)
  - Single transaction ensures data integrity
  - Window function picks one record per URL (randomly if no timestamp)
  - Works on Redshift without created_at column
- **Script**: `backend/deduplicate_content.py`
- **Result**: Removed 48,846 duplicates, 100% clean (0 duplicates remaining)

### Werkvoorraad Synchronization Pattern
- **Problem**: Content exists but werkvoorraad table not updated (URLs marked pending but have content)
- **Use Case**: After bulk imports, manual content additions, or interrupted processing
- **Solution**: Use SQL JOIN to update werkvoorraad table based on content table
- **Implementation**:
```sql
-- Update werkvoorraad table
UPDATE pa.jvs_seo_werkvoorraad_shopping_season w
SET kopteksten = 1
FROM pa.content_urls_joep c
WHERE w.url = c.url AND w.kopteksten = 0;

-- Add tracking records
INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url, status)
SELECT c.url, 'success'
FROM pa.content_urls_joep c
LEFT JOIN pa.jvs_seo_werkvoorraad_kopteksten_check k ON c.url = k.url
WHERE k.url IS NULL
ON CONFLICT (url) DO UPDATE SET status = 'success';
```
- **Benefits**:
  - Efficient single-query update for thousands of URLs
  - Synchronizes both werkvoorraad and tracking tables
  - Prevents duplicate content generation
- **Script**: `backend/sync_werkvoorraad.py`
- **Result**: Synchronized 17,672 URLs, 0 overlaps remaining

### Link Validation Performance Analysis
- **Conservative Mode**: 0.5-0.7s delay per link check
  - 100 items with ~350 links = ~3m52s (~2.3s per item)
  - Rate: ~1,552 items/hour
  - Use case: Maximum caution, avoiding any rate limit concerns
- **Optimized Mode**: No delay between checks
  - Estimated 5-10x faster than conservative
  - With 5 workers: ~60K items in ~1 hour
  - Rate: ~60,000 items/hour (38x faster)
- **Recommendation**: Use optimized mode for link validation
  - Link validation just checks HTTP status (HEAD requests)
  - Much lighter than content scraping
  - Whitelisted IP has no rate limits
  - Conservative mode unnecessary for validation workloads

### Connection Pooling with psycopg2.pool.ThreadedConnectionPool
- **Problem**: Each worker creates/closes database connections for every URL processed
- **Impact**: Connection overhead of 50-200ms per URL adds up significantly
- **Solution**: Implement connection pooling to reuse connections across requests
- **Implementation**:
```python
from psycopg2 import pool

# Create connection pools (global, initialized on first use)
_pg_pool = None
_redshift_pool = None

def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=os.getenv("DATABASE_URL"),
            cursor_factory=RealDictCursor
        )
    return _pg_pool

def get_db_connection():
    """Get connection from pool"""
    return _get_pg_pool().getconn()

def return_db_connection(conn):
    """Return connection to pool"""
    if conn:
        _get_pg_pool().putconn(conn)
```
- **Benefits**:
  - 30-50% faster per URL (eliminates connection overhead)
  - Reduces network latency and handshake time
  - Better resource utilization (reuse existing connections)
  - Automatic connection management (pool handles lifecycle)
- **Configuration**: Pool size 2-10 connections per database (PostgreSQL + Redshift)
- **Important**: Always return connections to pool with `return_db_connection(conn)` in finally blocks
- **Location**: backend/database.py (lines 6-67), backend/main.py (all connection usage updated)

### Redshift COPY Command for Bulk Inserts
- **Problem**: Using executemany() for Redshift bulk inserts causes multiple network round-trips
- **Impact**: Batch operations take longer than necessary, especially for large batches
- **Solution**: Use COPY command which is 5-10x faster for bulk data loads
- **Implementation**:
```python
from io import StringIO

# Prepare data buffer
buffer = StringIO()
for url, content in insert_content_data:
    # Escape tabs and newlines
    content_escaped = content.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
    buffer.write(f"{url}\t{content_escaped}\n")
buffer.seek(0)

# Use COPY command (Redshift only)
if use_redshift:
    output_cur.copy_from(buffer, 'pa.content_urls_joep', columns=['url', 'content'], sep='\t')
else:
    # Fallback to executemany for PostgreSQL
    output_cur.executemany("INSERT INTO pa.content_urls_joep (url, content) VALUES (%s, %s)", insert_content_data)
```
- **Benefits**:
  - 20-30% faster for Redshift batch operations
  - Reduces network round-trips from N to 1 per batch
  - More efficient for large datasets (100+ rows)
  - Automatically falls back to executemany() for PostgreSQL
- **Performance**: COPY is 5-10x faster than INSERT for bulk operations in Redshift
- **Location**: backend/main.py (lines 260-275)

### Three-State URL Tracking in Redshift
- **Pattern**: Use tri-state flag instead of boolean for better tracking granularity
- **Use Case**: Need to distinguish between "successfully processed with content" vs "processed but no usable content" vs "not yet processed"
- **Implementation**:
  - `kopteksten = 0`: Pending (not yet processed)
  - `kopteksten = 1`: Successfully processed with content (has entry in content_urls_joep table)
  - `kopteksten = 2`: Processed without content (skipped, failed, no products, AI errors, etc.)
- **Benefits**:
  - Query for problematic URLs: `WHERE kopteksten = 2` shows all non-productive URLs
  - Better analytics: Can calculate success rate, skip rate, etc.
  - Clear distinction between "has content" and "tried but failed"
  - Prevents re-processing of legitimately empty pages
- **Redshift Operations**:
  - Success: `('update_werkvoorraad_success', url)` → sets kopteksten=1
  - Processed without content: `('update_werkvoorraad_processed', url)` → sets kopteksten=2
  - 503 errors: No Redshift update → stays kopteksten=0 for retry
- **Location**: backend/main.py (lines 73-135 for logic, 267-308 for batch execution)
- **Date**: 2025-10-22

### Distinguishing Scraping Failure Types for Retry Logic
- **Pattern**: Return different indicators from scraper for retriable vs non-retriable failures
- **Use Case**: Need to stop batch immediately on rate limiting (503) but mark other failures as processed
- **Implementation**:
  - **503 errors** (rate limiting): Return `{'error': '503'}` - triggers immediate batch stop
  - **Other failures** (timeout, network error): Return `None` - marked as processed (kopteksten=2)
  - **Success**: Return dict with scraped data
- **Benefits**:
  - Batch stops immediately on first 503 (not after 3 consecutive failures)
  - Non-retriable failures (timeout, connection error) don't stay in pending forever
  - Clear signal to calling code about failure type
  - Prevents wasting API calls when rate limited
- **Processing Logic**:
```python
scraped_data = scrape_product_page(url)
if scraped_data and scraped_data.get('error') == '503':
    # Rate limited - keep pending, stop batch
    result["reason"] = "rate_limited_503"
    rate_limited = True
    break
elif not scraped_data:
    # Other failure - mark as processed (kopteksten=2)
    result["reason"] = "scraping_failed"
    redshift_ops.append(('update_werkvoorraad_processed', url))
```
- **Location**: backend/scraper_service.py (returns {'error': '503'}), backend/main.py (lines 73-87, 256-260)
- **Date**: 2025-10-22

### Database Synchronization Pattern for Hybrid Architecture
- **Pattern**: Periodic sync script to ensure consistency between local and cloud databases
- **Use Case**: Hybrid architecture (local PostgreSQL + Redshift) where local writes may not complete in cloud due to network issues or interruptions
- **Problem**: Local content exists but cloud flags (kopteksten) not updated, causing mismatch between source of truth
- **Implementation**:
  1. Identify "source of truth" table (e.g., local content table with actual data)
  2. Identify "tracking" table (e.g., cloud flags indicating processing state)
  3. Create sync script that queries source table and updates tracking table
  4. Use batch updates (1000 rows) for performance on large datasets
  5. Make idempotent (safe to run multiple times, only updates stale records)
- **Benefits**:
  - Recovers from interrupted batch operations
  - Maintains data consistency across hybrid architecture
  - Can run safely anytime without duplicating work
  - Prevents progress stalls due to filtering mismatches
  - Provides one-time fix for accumulated inconsistencies
- **Example**:
```python
# Sync script structure
def sync_flags():
    # 1. Get source of truth
    local_cur.execute("SELECT url FROM pa.content_urls_joep")
    urls_with_content = [row['url'] for row in local_cur.fetchall()]

    # 2. Check cloud for stale records
    output_cur.execute("""
        SELECT COUNT(*) FROM pa.jvs_seo_werkvoorraad_shopping_season
        WHERE url IN (%s) AND kopteksten = 0
    """, urls_with_content)

    # 3. Batch update cloud flags
    for batch in chunks(urls_with_content, 1000):
        output_cur.execute("""
            UPDATE pa.jvs_seo_werkvoorraad_shopping_season
            SET kopteksten = 1
            WHERE url IN (%s) AND kopteksten = 0
        """, batch)
        output_conn.commit()
```
- **When to Run**: After interrupted sessions, network issues, or when progress stalls unexpectedly
- **Location**: backend/sync_redshift_flags.py (created 2025-10-22)
- **Date**: 2025-10-22

### Auto-Stop on Consecutive Scraping Failures
- **Pattern**: Track consecutive failures and stop batch processing after threshold
- **Use Case**: Detecting rate limiting (503 errors) and preventing wasted processing time
- **Implementation**:
```python
consecutive_failures = 0
for result in results:
    if result['status'] == 'failed' and result.get('reason') == 'scraping_failed':
        consecutive_failures += 1
        if consecutive_failures >= 3:
            print(f"[RATE LIMIT DETECTED] Stopping batch - {consecutive_failures} consecutive scraping failures")
            break
    else:
        consecutive_failures = 0  # Reset on success
```
- **Benefits**:
  - Prevents marking thousands of URLs incorrectly during rate limiting
  - Saves API costs (OpenAI) by stopping early
  - Clear signal to user that system is rate limited
  - Automatic recovery when resumed later
- **Threshold**: 3 consecutive failures (configurable)
- **Location**: backend/main.py - `process_urls()` endpoint (lines 242-256)
- **Date**: 2025-10-21

### CSV Upload with Relative URL Conversion
- **Pattern**: Handle CSV files with relative URLs by converting to absolute URLs
- **Use Case**: Importing URL lists where some URLs are relative (/products/...) instead of absolute (https://...)
- **Implementation**:
```python
import csv
from io import StringIO

# Parse CSV with auto-detected delimiter
csvfile = StringIO(file_content.decode('utf-8-sig'))
dialect = csv.Sniffer().sniff(csvfile.read(1024), delimiters=',;\t')
csvfile.seek(0)
reader = csv.reader(csvfile, dialect)

# Convert relative URLs to absolute
base_url = 'https://www.beslist.nl'
urls = []
for row in reader:
    if row and row[0].strip():
        url = row[0].strip()
        # Convert relative to absolute
        if url.startswith('/'):
            url = base_url + url
        urls.append(url)
```
- **Benefits**:
  - Handles both relative and absolute URLs seamlessly
  - Auto-detects CSV delimiter (comma, semicolon, tab)
  - Handles UTF-8 BOM encoding
  - Skips empty rows automatically
- **Batch Checking**: For Redshift compatibility (no ON CONFLICT), use batch checking:
  - Query existing URLs in batches of 500
  - Filter duplicates in Python
  - Insert only new URLs
- **Location**: backend/main.py - `/api/upload-urls` endpoint (lines 463-542)
- **Date**: 2025-10-21

### Content Generation Performance Optimizations
- **Problem**: Processing 131K URLs at ~4-10 seconds per URL would take 18-46 days
- **Goal**: Reduce processing time to 3-9 days (2.8-6x faster)
- **Optimizations Implemented**:
  1. **Reduced scraping delay** (0.5-1s → 0.05-0.1s): Whitelisted IP doesn't need aggressive rate limiting
  2. **Reduced AI max_tokens** (500 → 300): Content is max 100 words (~130 tokens), so 300 is sufficient
  3. **Batch local PostgreSQL commits**: Changed from 3-5 commits per URL to 1 commit per URL (all operations in single transaction at end)
  4. **Switch to lxml parser**: BeautifulSoup now uses lxml instead of html.parser (2-3x faster HTML parsing)
  5. **Use executemany() for Redshift**: Batch all INSERTs and UPDATEs using cursor.executemany() instead of loop
- **Performance Impact**:
  - Scraping delay: Save ~0.5-0.9s per URL (10-20% speedup)
  - AI tokens: Save ~0.5-1s per URL (10-15% speedup)
  - Local DB batching: Save ~0.2-0.4s per URL (5-10% speedup)
  - lxml parser: Save ~0.3-0.5s per URL (5-8% speedup)
  - executemany(): Save ~0.1-0.2s per batch (marginal but helpful)
  - **Total: 30-50% faster per URL** (4-10s → 2.5-7s per URL)
- **Combined with parallel workers**: Original default of 3 workers can be increased to 5-7 for linear speedup
- **Expected Results**:
  - Before: ~120-300 URLs/hour with 3 workers
  - After: ~350-840 URLs/hour with 3 workers, or ~580-1,400 URLs/hour with 5 workers
  - 131K URLs: 18-46 days → 5-15 days (with 3 workers) or 4-9 days (with 5 workers)
- **Files Modified**:
  - `backend/scraper_service.py`: Adjusted delay to 0.2-0.3s (balanced for Cloudflare), switched to lxml parser
  - `backend/gpt_service.py`: Reduced max_tokens from 500 to 300
  - `backend/main.py`: Refactored process_single_url() to batch local commits, added executemany() for Redshift
- **Location**: backend/scraper_service.py (lines 70-72, 102), backend/gpt_service.py (line 89), backend/main.py (lines 52-145, 208-243)
- **Note on Scraping Delay**: Initial attempt at 0.05-0.1s was too aggressive, causing Cloudflare HTTP 202 (queuing) responses even with whitelisted IP. Adjusted to 0.2-0.3s as sweet spot between speed and avoiding rate limits.

---
_Last updated: 2025-10-21_
