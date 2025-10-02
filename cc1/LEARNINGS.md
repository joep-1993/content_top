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

# Thema Ads Optimized
./docker-run.sh setup          # Setup environment and directories
./docker-run.sh build          # Build Docker image
./docker-run.sh dry-run        # Test run (no changes)
./docker-run.sh run            # Production run
./docker-run.sh logs           # View logs
./docker-run.sh clean          # Cleanup Docker resources

# Thema Ads Web Interface (Quick Start)
./start-thema-ads.sh           # Build, start, and initialize everything
```

## Common Issues & Solutions

### Port Conflicts
- FastAPI on 8001 (not 8000) to avoid conflicts
- PostgreSQL on 5433 (not 5432) for same reason

### CORS Errors
- Check `allow_origins` in main.py
- For dev: use `["*"]`
- For production: specify exact frontend URL

### Database Connection
- Wait for PostgreSQL to fully start
- Check DATABASE_URL in .env
- Run `docker-compose logs db` to debug

### Google Ads API Version Compatibility
- **Error**: `501 GRPC target method can't be resolved`
- **Cause**: Using outdated Google Ads API version (v16)
- **Solution**: Upgrade to google-ads>=25.1.0 (currently v28.0.0)

### Google Ads OAuth Credentials Mismatch
- **Error**: `unauthorized_client: Unauthorized`
- **Cause**: Refresh token must match the exact client_id/client_secret used to generate it
- **Solution**: Ensure client_id and client_secret match the ones used to create the refresh_token

### Google Ads API Parameter Changes
- **Error**: `mutate_ad_group_ads() got an unexpected keyword argument 'partial_failure'`
- **Cause**: Google Ads API v28+ removed 'partial_failure' parameter
- **Solution**: Remove partial_failure parameter from all mutate operations

### Empty List Conditional Bug
- **Error**: Operations silently skipped even though data exists
- **Cause**: Empty lists evaluate to False in Python conditionals (e.g., `if new_ads and label_ops:`)
- **Solution**: Check only the required condition (e.g., `if new_ads:`), not empty supporting lists

### Module Import Errors in Docker
- **Error**: `ModuleNotFoundError: No module named 'database'`
- **Cause**: Relative imports don't work when running as module in Docker container
- **Solution**: Use absolute imports (e.g., `from backend.database import get_db_connection`)

### OpenAI httpx Compatibility
- **Error**: `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`
- **Cause**: OpenAI 1.35.0 incompatible with httpx >= 0.26.0
- **Solution**: Pin httpx==0.25.2 in requirements.txt

### Empty CSV Rows Causing Job Failures
- **Error**: `Error in query: unexpected input 1.` when starting Thema Ads job
- **Cause**: CSV contained empty rows with blank customer_id or ad_group_id fields
- **Solution**: Skip rows during CSV parsing where customer_id or ad_group_id is empty
```python
if not customer_id or not ad_group_id:
    continue  # Skip empty rows
```

### Customer IDs with Dashes Breaking Google Ads API
- **Error**: `Error in query: unexpected input 1.` when querying ad groups
- **Cause**: Customer IDs formatted as "123-456-7890" instead of "1234567890"
- **Solution**: Automatically strip dashes from customer_id during CSV parsing
```python
customer_id = row['customer_id'].strip().replace('-', '')
```

### CSV Encoding Issues
- **Error**: `'utf-8' codec can't decode byte 0xe8 in position X: invalid continuation byte`
- **Cause**: CSV file exported from Excel or other tools using non-UTF-8 encoding (Windows-1252, ISO-8859-1)
- **Solution**: Try multiple encodings in fallback order
```python
encodings = ['utf-8', 'utf-8-sig', 'windows-1252', 'iso-8859-1', 'latin1']
for encoding in encodings:
    try:
        decoded = contents.decode(encoding)
        break
    except UnicodeDecodeError:
        continue
```

### Large CSV Upload Timeouts
- **Error**: Connection timeout during upload, "Failed to load jobs list (request timed out)"
- **Cause**: Individual row-by-row database inserts extremely slow for large files (100k+ rows)
- **Solution**: Use batch inserts with executemany() and dynamic timeouts
```python
# Batch insert instead of loop
input_values = [(job_id, item['customer_id'], ...) for item in input_data]
cur.executemany("INSERT INTO table VALUES (%s, %s, ...)", input_values)

# Dynamic timeout on frontend based on file size
baseTimeout = 120000  # 2 minutes
extraTimeout = Math.floor(fileSize / (5 * 1024 * 1024)) * 30000  # +30s per 5MB
uploadTimeout = Math.min(baseTimeout + extraTimeout, 600000)  # Max 10 min
```
- **Performance**: Batch inserts are 100-1000x faster than individual inserts for large datasets

### GitHub Push Protection Blocking Secrets
- **Error**: `Push cannot contain secrets` - Google OAuth tokens, Azure secrets detected
- **Cause**: Hardcoded credentials in thema_ads script were committed to git history
- **Solution**:
  1. Remove files with secrets: `git rm --cached thema_ads_project/thema_ads`
  2. Add to .gitignore: `thema_ads_project/thema_ads` and `*.xlsx`
  3. Refactor script to use environment variables from .env file
  4. Amend commit to exclude sensitive files
```bash
# Remove from git tracking
git rm --cached path/to/secret-file

# Add to .gitignore
echo "path/to/secret-file" >> .gitignore

# Amend commit
git add .gitignore
git commit --amend --no-edit
```

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

### Async/Parallel Processing for Performance
- **Pattern**: Use asyncio with semaphore-controlled concurrency
- **Benefit**: 20-50x speedup vs sequential processing
- **Example**: Process 10 customers in parallel, each with batched operations
```python
semaphore = asyncio.Semaphore(10)
tasks = [process_customer(cid, data) for cid, data in grouped]
results = await asyncio.gather(*tasks)
```

### Batch API Operations
- **Pattern**: Collect operations in memory, execute in single API call
- **Benefit**: Reduce API calls from 6 per item to 1 per 1000 items
- **Example**: Create 1000 ads in one mutate_ad_group_ads() call
- **Limit**: Google Ads API supports up to 10,000 operations per request

### Idempotent Processing with Label-Based Tracking
- **Pattern**: Label processed items and skip them on subsequent runs
- **Benefit**: Prevent duplicate processing, enable safe re-runs, resume after failures
- **Example**: Label ad groups with "SD_DONE" after processing, skip any with this label
```python
# Prefetch ad group labels
ag_labels_map = await prefetch_ad_group_labels(client, customer_id, ad_groups, "SD_DONE")

# Skip already processed
for inp, ag_resource in zip(inputs, ad_group_resources):
    if ag_labels_map.get(ag_resource, False):
        logger.info(f"Skipping {inp.ad_group_id} - already has SD_DONE label")
        continue
    # ... process ad group ...
    # After processing, label it
    await label_ad_groups_batch(client, customer_id, [(ag_resource, sd_done_label)])
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

### Prefetch Strategy for Bulk Operations
- **Pattern**: Load all required data upfront in 2-3 queries instead of N queries
- **Benefit**: Eliminate redundant API calls, enable better caching
- **Example**: Fetch all labels, all existing ads for customer before processing

### Real-time Progress Tracking with Polling
- **Pattern**: JavaScript polls API endpoint every 2 seconds for status updates
- **Benefit**: Live progress updates without WebSockets complexity
- **Example**: Poll `/api/thema-ads/jobs/{id}`, update progress bar, auto-stop when complete
```javascript
pollInterval = setInterval(updateJobStatus, 2000);
if (status === 'completed') clearInterval(pollInterval);
```

### State Persistence for Resumable Jobs
- **Pattern**: Store job state in PostgreSQL with granular item tracking
- **Benefit**: Resume from exact point after crash or pause, zero data loss
- **Example**: Track job status + individual item status (pending/processing/completed/failed)
```sql
-- Job tracks overall progress
thema_ads_jobs: id, status, total, processed, successful, failed

-- Items track individual ad groups
thema_ads_job_items: id, job_id, customer_id, ad_group_id, status, error_message
```

### Flexible CSV Column Handling
- **Pattern**: Parse CSV by column names (not positions); make columns optional
- **Benefit**: Users can provide minimal CSV (2 cols) or full CSV (4+ cols); extra columns ignored; column order doesn't matter
- **Example**: Accept both minimal and full formats
```csv
# Minimal (fetches campaign info at runtime)
customer_id,ad_group_id
1234567890,9876543210

# Full (faster, no API calls needed)
customer_id,campaign_id,campaign_name,ad_group_id
1234567890,5555,My Campaign,9876543210

# Extra columns ignored (status, budget, etc.)
customer_id,campaign_id,campaign_name,ad_group_id,status,budget
```

### Defer Expensive Operations from Upload to Execution
- **Pattern**: Don't fetch external data during file upload; defer to job execution
- **Benefit**: Fast uploads (no timeouts), better error handling, users can upload large files quickly
- **Example**: Campaign info can be provided in CSV or fetched when job starts, not during upload
```python
# During upload: just parse and store
item = {
    'customer_id': customer_id,
    'ad_group_id': ad_group_id,
    'campaign_id': row.get('campaign_id'),  # Optional
    'campaign_name': row.get('campaign_name')  # Optional
}

# During job execution: fetch missing data if needed
if not item['campaign_id']:
    campaign_info = fetch_from_google_ads_api(customer_id, ad_group_id)
```

### Environment Variable Management for Legacy Scripts
- **Pattern**: Refactor hardcoded credentials to use python-dotenv
- **Benefit**: Secure secrets, reusable configuration, safe for version control, prevents accidental exposure
- **Example**: Load from .env file at script startup
```python
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Use environment variables instead of hardcoded values
refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
developer_token = os.getenv("GOOGLE_DEVELOPER_TOKEN")
client_id = os.getenv("GOOGLE_CLIENT_ID")

# Validate required variables
required = ["GOOGLE_REFRESH_TOKEN", "GOOGLE_DEVELOPER_TOKEN", "GOOGLE_CLIENT_ID"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
```

---
_Last updated: 2025-10-02_
