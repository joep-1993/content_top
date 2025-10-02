from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
import os
import csv
import io
from datetime import datetime
from typing import Dict, List
from backend.database import get_db_connection
from backend.scraper_service import scrape_product_page, sanitize_content
from backend.gpt_service import generate_product_content, check_content_has_valid_links
from backend.thema_ads_service import thema_ads_service

app = FastAPI(title="test2", version="1.0.0")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
def read_root():
    return {
        "status": "running",
        "project": "test2",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "backend"}

@app.post("/api/generate")
async def generate_text(prompt: str):
    """Example endpoint for AI generation"""
    from backend.gpt_service import simple_completion
    try:
        result = simple_completion(prompt)
        return {"response": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/process-urls")
async def process_urls():
    """
    Process batch of URLs for SEO content generation.
    Fetches 2 URLs at a time, scrapes content, generates AI text, and saves to database.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Get 2 unprocessed URLs
        cur.execute("""
            SELECT url FROM pa.jvs_seo_werkvoorraad
            WHERE url NOT IN (SELECT url FROM pa.jvs_seo_werkvoorraad_kopteksten_check)
            LIMIT 2
        """)
        rows = cur.fetchall()

        if not rows:
            return {
                "status": "complete",
                "message": "No URLs to process",
                "processed": 0
            }

        results = []
        processed_count = 0

        for row in rows:
            url = row['url']

            # Add to tracking table
            cur.execute("""
                INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url)
                VALUES (%s)
            """, (url,))
            conn.commit()

            # Scrape the URL
            scraped_data = scrape_product_page(url)

            if not scraped_data:
                results.append({
                    "url": url,
                    "status": "failed",
                    "reason": "scraping_failed"
                })
                continue

            # Check if products found
            if not scraped_data['products'] or len(scraped_data['products']) == 0:
                results.append({
                    "url": url,
                    "status": "skipped",
                    "reason": "no_products_found"
                })
                continue

            # Generate AI content
            try:
                ai_content = generate_product_content(
                    scraped_data['h1_title'],
                    scraped_data['products']
                )

                # Sanitize content for SQL
                sanitized = sanitize_content(ai_content)

                # Check if content has valid links
                if not check_content_has_valid_links(ai_content):
                    # Remove from check table if invalid
                    cur.execute("""
                        DELETE FROM pa.jvs_seo_werkvoorraad_kopteksten_check
                        WHERE url = %s
                    """, (url,))
                    conn.commit()

                    results.append({
                        "url": url,
                        "status": "failed",
                        "reason": "no_valid_links"
                    })
                    continue

                # Write to output table
                cur.execute("""
                    INSERT INTO pa.content_urls_joep (url, content)
                    VALUES (%s, %s)
                """, (url, sanitized))

                # Update werkvoorraad
                cur.execute("""
                    UPDATE pa.jvs_seo_werkvoorraad
                    SET kopteksten = 1
                    WHERE url = %s
                """, (url,))

                conn.commit()
                processed_count += 1

                results.append({
                    "url": url,
                    "status": "success",
                    "content_preview": ai_content[:100] + "..."
                })

            except Exception as e:
                results.append({
                    "url": url,
                    "status": "failed",
                    "reason": f"ai_generation_error: {str(e)}"
                })

        cur.close()

        return {
            "status": "success",
            "processed": processed_count,
            "total_attempted": len(rows),
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

@app.get("/api/status")
async def get_status():
    """Get processing status and counts"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Get total URLs
        cur.execute("SELECT COUNT(*) as total FROM pa.jvs_seo_werkvoorraad")
        total = cur.fetchone()['total']

        # Get processed URLs
        cur.execute("SELECT COUNT(*) as processed FROM pa.jvs_seo_werkvoorraad WHERE kopteksten = 1")
        processed = cur.fetchone()['processed']

        # Get pending URLs
        cur.execute("""
            SELECT COUNT(*) as pending FROM pa.jvs_seo_werkvoorraad
            WHERE url NOT IN (SELECT url FROM pa.jvs_seo_werkvoorraad_kopteksten_check)
        """)
        pending = cur.fetchone()['pending']

        # Get recent results
        cur.execute("""
            SELECT url, content, created_at
            FROM pa.content_urls_joep
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "total_urls": total,
            "processed": processed,
            "pending": pending,
            "recent_results": recent
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Thema Ads Endpoints ====================

def convert_scientific_notation(value: str) -> str:
    """Convert scientific notation to regular number string.
    Handles both period and comma decimal separators (e.g., 1.76256E+11 or 1,76256E+11).
    """
    if not value:
        return value

    value = value.strip()

    # Check if it's in scientific notation (e.g., 1.76256E+11 or 1,76256E+11)
    if 'E' in value.upper():
        try:
            # Replace comma with period for locales that use comma as decimal separator
            value_normalized = value.replace(',', '.')
            # Convert to float, then to int, then to string (removes scientific notation)
            return str(int(float(value_normalized)))
        except (ValueError, OverflowError):
            # If conversion fails, return original value
            return value

    return value


@app.post("/api/thema-ads/upload")
async def upload_csv(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """
    Upload CSV file with customer_id and ad_group_id columns.
    Creates a new job and automatically starts processing.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        logger.info(f"Receiving file upload: {file.filename}")
        contents = await file.read()
        logger.info(f"File size: {len(contents)} bytes")

        # Try multiple encodings to decode the file
        decoded = None
        encodings = ['utf-8', 'utf-8-sig', 'windows-1252', 'iso-8859-1', 'latin1']
        for encoding in encodings:
            try:
                decoded = contents.decode(encoding)
                logger.info(f"Successfully decoded file using encoding: {encoding}")
                break
            except UnicodeDecodeError:
                continue

        if decoded is None:
            raise HTTPException(
                status_code=400,
                detail="Unable to decode file. Please ensure it's a valid CSV file saved with UTF-8 or Windows-1252 encoding."
            )

        # Auto-detect delimiter (comma or semicolon)
        sample = decoded[:1024]  # Check first 1KB
        delimiter = ';' if ';' in sample.split('\n')[0] else ','
        logger.info(f"Using delimiter: '{delimiter}'")

        csv_reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)

        # Parse CSV data
        input_data = []
        headers_seen = None
        for row_num, row in enumerate(csv_reader):
            if headers_seen is None:
                headers_seen = list(row.keys())
                logger.info(f"CSV headers found: {headers_seen}")

            if 'customer_id' in row and 'ad_group_id' in row:
                # Convert scientific notation to regular numbers (Excel export issue)
                customer_id = convert_scientific_notation(row['customer_id'])
                ad_group_id = convert_scientific_notation(row['ad_group_id'])

                # Remove dashes from customer_id (Google Ads API requirement)
                customer_id = customer_id.strip().replace('-', '')
                ad_group_id = ad_group_id.strip()

                # Skip empty rows
                if not customer_id or not ad_group_id:
                    continue

                item = {
                    'customer_id': customer_id,
                    'ad_group_id': ad_group_id
                }

                # Add optional campaign info if provided
                if 'campaign_id' in row and row['campaign_id'].strip():
                    campaign_id = convert_scientific_notation(row['campaign_id'])
                    item['campaign_id'] = campaign_id.strip()
                if 'campaign_name' in row and row['campaign_name'].strip():
                    item['campaign_name'] = row['campaign_name'].strip()

                input_data.append(item)

        logger.info(f"Parsed {len(input_data)} rows from CSV")

        if not input_data:
            error_msg = f"CSV must contain 'customer_id' and 'ad_group_id' columns. Found headers: {headers_seen}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )

        # Create job
        logger.info("Creating job in database...")
        job_id = thema_ads_service.create_job(input_data)
        logger.info(f"Job created with ID: {job_id}")

        # Automatically start the job
        if background_tasks:
            background_tasks.add_task(thema_ads_service.process_job, job_id)
            logger.info(f"Job {job_id} queued for automatic processing")

        return {
            "job_id": job_id,
            "total_items": len(input_data),
            "status": "processing"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thema-ads/jobs/{job_id}/start")
async def start_job(job_id: int, background_tasks: BackgroundTasks):
    """Start processing a job in the background."""
    try:
        job = thema_ads_service.get_job_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job['status'] == 'running':
            raise HTTPException(status_code=400, detail="Job is already running")

        # Run job in background
        background_tasks.add_task(thema_ads_service.process_job, job_id)

        return {"status": "started", "job_id": job_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thema-ads/jobs/{job_id}/pause")
async def pause_job(job_id: int):
    """Pause a running job."""
    try:
        job = thema_ads_service.get_job_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        thema_ads_service.pause_job(job_id)

        return {"status": "paused", "job_id": job_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thema-ads/jobs/{job_id}/resume")
async def resume_job(job_id: int, background_tasks: BackgroundTasks):
    """Resume a paused job."""
    try:
        job = thema_ads_service.get_job_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job['status'] not in ('paused', 'failed'):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume job with status '{job['status']}'"
            )

        # Run job in background
        background_tasks.add_task(thema_ads_service.process_job, job_id)

        return {"status": "resumed", "job_id": job_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/thema-ads/jobs/{job_id}")
async def get_job_status(job_id: int):
    """Get detailed status of a specific job."""
    try:
        job = thema_ads_service.get_job_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return job

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/thema-ads/jobs")
async def list_jobs(limit: int = 20):
    """List all jobs."""
    try:
        jobs = thema_ads_service.list_jobs(limit)
        return {"jobs": jobs}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/thema-ads/jobs/{job_id}")
async def delete_job(job_id: int):
    """Delete a job and all its associated data."""
    try:
        job = thema_ads_service.get_job_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Don't allow deleting running jobs
        if job['status'] == 'running':
            raise HTTPException(
                status_code=400,
                detail="Cannot delete a running job. Please pause it first."
            )

        thema_ads_service.delete_job(job_id)

        return {"status": "deleted", "job_id": job_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/thema-ads/jobs/{job_id}/failed-items-csv")
async def download_failed_items(job_id: int):
    """Download CSV of failed items for a job."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Get failed items
        cur.execute("""
            SELECT customer_id, campaign_id, campaign_name, ad_group_id, error_message
            FROM thema_ads_job_items
            WHERE job_id = %s AND status = 'failed'
            ORDER BY customer_id, ad_group_id
        """, (job_id,))

        failed_items = cur.fetchall()
        cur.close()
        conn.close()

        if not failed_items:
            raise HTTPException(status_code=404, detail="No failed items found for this job")

        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(['customer_id', 'campaign_id', 'campaign_name', 'ad_group_id', 'error_message'])

        # Write data
        for item in failed_items:
            writer.writerow([
                item['customer_id'],
                item['campaign_id'] or '',
                item['campaign_name'] or '',
                item['ad_group_id'],
                item['error_message'] or ''
            ])

        # Prepare response
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=job_{job_id}_failed_items.csv"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
