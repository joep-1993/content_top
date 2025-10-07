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

### Database Schema Column Missing
- **Error**: `column "status" does not exist`
- **Cause**: Schema changes applied to wrong database (postgres vs content_top)
- **Solution**: Check DATABASE_URL in docker-compose.yml, apply schema to correct database
- **Command**: `docker-compose exec -T db psql -U postgres -d content_top < backend/schema.sql`

### OpenAI httpx Compatibility
- **Error**: `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`
- **Cause**: OpenAI 1.35.0 incompatible with httpx >= 0.26.0
- **Solution**: Pin httpx==0.25.2 in requirements.txt

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
- **Benefits**:
  - Automated quality control for product links
  - Parallel validation speeds up large batches
  - Historical tracking of broken links
  - Auto-recovery workflow (reset to pending)
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

---
_Last updated: 2025-10-07_
