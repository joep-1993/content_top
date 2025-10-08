from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from datetime import datetime
from io import StringIO, BytesIO
import csv
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from backend.database import get_db_connection, get_output_connection
from backend.scraper_service import scrape_product_page, sanitize_content
from backend.gpt_service import generate_product_content, check_content_has_valid_links
from backend.link_validator import validate_content_links

app = FastAPI(title="Content Top - SEO Content Generation", version="1.0.0")

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
        "project": "content_top",
        "description": "SEO Content Generation API",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "content_top"}

@app.post("/api/generate")
async def generate_text(prompt: str):
    """Example endpoint for AI generation"""
    from backend.gpt_service import simple_completion
    try:
        result = simple_completion(prompt)
        return {"response": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def process_single_url(url: str):
    """Process a single URL - runs in thread pool"""
    result = {"url": url, "status": "pending"}
    conn = None

    try:
        # Use local PostgreSQL for tracking
        conn = get_db_connection()
        cur = conn.cursor()

        # Add to tracking table (local)
        cur.execute("""
            INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url, status)
            VALUES (%s, 'pending')
        """, (url,))
        conn.commit()

        # Scrape the URL
        scraped_data = scrape_product_page(url)

        if not scraped_data:
            # Update status to failed (local)
            cur.execute("""
                UPDATE pa.jvs_seo_werkvoorraad_kopteksten_check
                SET status = 'failed', skip_reason = 'scraping_failed'
                WHERE url = %s
            """, (url,))
            conn.commit()
            result["status"] = "failed"
            result["reason"] = "scraping_failed"
            return result

        # Check if products found
        if not scraped_data['products'] or len(scraped_data['products']) == 0:
            # Update status to skipped (local)
            cur.execute("""
                UPDATE pa.jvs_seo_werkvoorraad_kopteksten_check
                SET status = 'skipped', skip_reason = 'no_products_found'
                WHERE url = %s
            """, (url,))
            conn.commit()
            result["status"] = "skipped"
            result["reason"] = "no_products_found"
            return result

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
                # Update status to failed (local)
                cur.execute("""
                    UPDATE pa.jvs_seo_werkvoorraad_kopteksten_check
                    SET status = 'failed', skip_reason = 'no_valid_links'
                    WHERE url = %s
                """, (url,))
                conn.commit()
                result["status"] = "failed"
                result["reason"] = "no_valid_links"
                return result

            # Write to Redshift tables
            output_conn = get_output_connection()
            output_cur = output_conn.cursor()
            try:
                # Insert content to Redshift
                output_cur.execute("""
                    INSERT INTO pa.content_urls_joep (url, content)
                    VALUES (%s, %s)
                """, (url, sanitized))

                # Update werkvoorraad in Redshift
                output_cur.execute("""
                    UPDATE pa.jvs_seo_werkvoorraad
                    SET kopteksten = 1
                    WHERE url = %s
                """, (url,))

                output_conn.commit()
            finally:
                output_cur.close()
                output_conn.close()

            # Update status to success (local tracking)
            cur.execute("""
                UPDATE pa.jvs_seo_werkvoorraad_kopteksten_check
                SET status = 'success'
                WHERE url = %s
            """, (url,))

            conn.commit()
            result["status"] = "success"
            result["content_preview"] = ai_content[:100] + "..."
            return result

        except Exception as e:
            # Update status to failed (local tracking)
            cur.execute("""
                UPDATE pa.jvs_seo_werkvoorraad_kopteksten_check
                SET status = 'failed', skip_reason = %s
                WHERE url = %s
            """, (f"ai_generation_error: {str(e)}", url))
            conn.commit()
            result["status"] = "failed"
            result["reason"] = f"ai_generation_error: {str(e)}"
            return result

    except Exception as e:
        result["status"] = "failed"
        result["reason"] = f"error: {str(e)}"
        return result
    finally:
        if conn:
            cur.close()
            conn.close()

@app.post("/api/process-urls")
async def process_urls(batch_size: int = 2, parallel_workers: int = 1):
    """
    Process batch of URLs for SEO content generation.
    Fetches specified number of URLs, scrapes content, generates AI text, and saves to database.
    Supports parallel processing with configurable workers.
    """
    try:
        # Validate parameters
        if batch_size < 1:
            raise HTTPException(status_code=400, detail="Batch size must be at least 1")

        if parallel_workers < 1 or parallel_workers > 10:
            raise HTTPException(status_code=400, detail="Parallel workers must be between 1 and 10")

        # Get unprocessed URLs from Redshift
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        # Get local tracking
        local_conn = get_db_connection()
        local_cur = local_conn.cursor()
        local_cur.execute("SELECT url FROM pa.jvs_seo_werkvoorraad_kopteksten_check")
        processed_urls = [row['url'] for row in local_cur.fetchall()]
        local_cur.close()
        local_conn.close()

        # Get unprocessed URLs from Redshift
        if processed_urls:
            placeholders = ','.join(['%s'] * len(processed_urls))
            output_cur.execute(f"""
                SELECT url FROM pa.jvs_seo_werkvoorraad
                WHERE url NOT IN ({placeholders})
                LIMIT %s
            """, (*processed_urls, batch_size))
        else:
            output_cur.execute("""
                SELECT url FROM pa.jvs_seo_werkvoorraad
                LIMIT %s
            """, (batch_size,))

        rows = output_cur.fetchall()
        output_cur.close()
        output_conn.close()

        if not rows:
            return {
                "status": "complete",
                "message": "No URLs to process",
                "processed": 0
            }

        urls = [row['url'] for row in rows]

        # Process URLs in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            results = list(executor.map(process_single_url, urls))

        processed_count = sum(1 for r in results if r['status'] == 'success')

        return {
            "status": "success",
            "processed": processed_count,
            "total_attempted": len(urls),
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
async def get_status():
    """Get processing status and counts"""
    try:
        # Get counts from Redshift
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        # Get total URLs from Redshift
        output_cur.execute("SELECT COUNT(*) as total FROM pa.jvs_seo_werkvoorraad")
        total = output_cur.fetchone()['total']

        # Get processed URLs (successful) from Redshift
        output_cur.execute("SELECT COUNT(*) as processed FROM pa.jvs_seo_werkvoorraad WHERE kopteksten = 1")
        processed = output_cur.fetchone()['processed']

        # Get local tracking for stats
        conn = get_db_connection()
        cur = conn.cursor()

        # Get skipped URLs
        cur.execute("""
            SELECT COUNT(*) as skipped
            FROM pa.jvs_seo_werkvoorraad_kopteksten_check
            WHERE status = 'skipped'
        """)
        skipped = cur.fetchone()['skipped']

        # Get failed URLs
        cur.execute("""
            SELECT COUNT(*) as failed
            FROM pa.jvs_seo_werkvoorraad_kopteksten_check
            WHERE status = 'failed'
        """)
        failed = cur.fetchone()['failed']

        # Get pending URLs (not yet attempted) - combine Redshift and local
        cur.execute("SELECT COUNT(*) as tracked FROM pa.jvs_seo_werkvoorraad_kopteksten_check")
        tracked = cur.fetchone()['tracked']
        pending = total - tracked

        # Get recent results from Redshift (no created_at column in Redshift)
        output_cur.execute("""
            SELECT url, content
            FROM pa.content_urls_joep
            LIMIT 5
        """)
        recent_rows = output_cur.fetchall()
        # Add None for created_at to match expected format
        recent = [{'url': r['url'], 'content': r['content'], 'created_at': None} for r in recent_rows]

        cur.close()
        conn.close()
        output_cur.close()
        output_conn.close()

        return {
            "total_urls": total,
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
            "pending": pending,
            "recent_results": recent
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/export/csv")
async def export_csv():
    """Export all generated content as CSV"""
    try:
        conn = get_output_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT url, content
            FROM pa.content_urls_joep
            ORDER BY created_at DESC
        """)
        rows = cur.fetchall()

        cur.close()
        conn.close()

        # Create CSV in memory with UTF-8 BOM for proper Excel compatibility
        output = BytesIO()
        output.write('\ufeff'.encode('utf-8'))  # UTF-8 BOM

        text_output = StringIO()
        writer = csv.writer(text_output, quoting=csv.QUOTE_ALL, lineterminator='\n')
        writer.writerow(['url', 'content'])

        for row in rows:
            # Replace newlines in content with spaces to prevent row breaks
            content = row['content'].replace('\n', ' ').replace('\r', ' ') if row['content'] else ''
            writer.writerow([row['url'], content])

        # Write CSV text to output with UTF-8 encoding
        output.write(text_output.getvalue().encode('utf-8'))

        # Return as downloadable file
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=content_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/export/json")
async def export_json():
    """Export all generated content as JSON"""
    try:
        conn = get_output_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT url, content
            FROM pa.content_urls_joep
        """)
        rows = cur.fetchall()

        cur.close()
        conn.close()

        # Convert to JSON-serializable format
        data = []
        for row in rows:
            data.append({
                'url': row['url'],
                'content': row['content'],
                'created_at': row['created_at'].isoformat() if row['created_at'] else None
            })

        # Return as downloadable file
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        return StreamingResponse(
            iter([json_str]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=content_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-urls")
async def upload_urls(file: UploadFile = File(...)):
    """Upload a text file with URLs (one per line) to add to the work queue"""
    try:
        # Read file content
        content = await file.read()
        urls = content.decode('utf-8').strip().split('\n')

        # Filter empty lines
        urls = [url.strip() for url in urls if url.strip()]

        if not urls:
            raise HTTPException(status_code=400, detail="No URLs found in file")

        # Insert URLs into database (ignore duplicates)
        conn = get_db_connection()
        cur = conn.cursor()

        added_count = 0
        duplicate_count = 0

        for url in urls:
            try:
                cur.execute("""
                    INSERT INTO pa.jvs_seo_werkvoorraad (url)
                    VALUES (%s)
                    ON CONFLICT (url) DO NOTHING
                """, (url,))

                if cur.rowcount > 0:
                    added_count += 1
                else:
                    duplicate_count += 1

            except Exception as e:
                # Skip invalid URLs
                continue

        conn.commit()
        cur.close()
        conn.close()

        return {
            "status": "success",
            "total_urls": len(urls),
            "added": added_count,
            "duplicates": duplicate_count,
            "message": f"Added {added_count} new URLs, {duplicate_count} duplicates skipped"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/result/{url:path}")
async def delete_result(url: str):
    """Delete a result and reset the URL back to pending state"""
    try:
        # Delete from Redshift output table and update werkvoorraad
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        # Delete content
        output_cur.execute("""
            DELETE FROM pa.content_urls_joep
            WHERE url = %s
        """, (url,))

        # Reset kopteksten flag in werkvoorraad
        output_cur.execute("""
            UPDATE pa.jvs_seo_werkvoorraad
            SET kopteksten = 0
            WHERE url = %s
        """, (url,))

        output_conn.commit()
        output_cur.close()
        output_conn.close()

        # Delete from local tracking table
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM pa.jvs_seo_werkvoorraad_kopteksten_check
            WHERE url = %s
        """, (url,))
        conn.commit()
        cur.close()
        conn.close()

        return {
            "status": "success",
            "message": f"Result deleted and URL reset to pending",
            "url": url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def validate_single_content(content_data: tuple) -> dict:
    """Validate links in a single content item - runs in thread pool"""
    content_url, content = content_data

    # Validate links in content
    validation_result = validate_content_links(content)

    # Add the content URL to the result
    validation_result['content_url'] = content_url

    return validation_result

@app.post("/api/validate-links")
async def validate_links(batch_size: int = 10, parallel_workers: int = 3):
    """
    Validate hyperlinks in generated content.
    Checks if links return 301 or 404, and moves content back to pending if broken links found.
    Supports parallel processing with configurable workers.
    """
    try:
        # Validate parameters
        if batch_size < 1:
            raise HTTPException(status_code=400, detail="Batch size must be at least 1")

        if parallel_workers < 1 or parallel_workers > 10:
            raise HTTPException(status_code=400, detail="Parallel workers must be between 1 and 10")

        # Get content from Redshift
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        # Get local PostgreSQL connection for validation tracking
        conn = get_db_connection()
        cur = conn.cursor()

        # Get validated URLs from local tracking
        cur.execute("SELECT content_url FROM pa.link_validation_results")
        validated_urls = [row['content_url'] for row in cur.fetchall()]

        # Get content to validate from Redshift (exclude already validated)
        if validated_urls:
            placeholders = ','.join(['%s'] * len(validated_urls))
            output_cur.execute(f"""
                SELECT url, content
                FROM pa.content_urls_joep
                WHERE url NOT IN ({placeholders})
                LIMIT %s
            """, (*validated_urls, batch_size))
        else:
            output_cur.execute("""
                SELECT url, content
                FROM pa.content_urls_joep
                LIMIT %s
            """, (batch_size,))

        rows = output_cur.fetchall()

        if not rows:
            output_cur.close()
            output_conn.close()
            cur.close()
            conn.close()
            return {
                "status": "complete",
                "message": "No content to validate",
                "validated": 0,
                "moved_to_pending": 0
            }

        # Prepare content items for parallel validation
        content_items = [(row['url'], row['content']) for row in rows]

        # Process validations in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            validation_results = list(executor.map(validate_single_content, content_items))

        results = []
        moved_to_pending = 0

        # Process validation results and update database
        for validation_result in validation_results:
            content_url = validation_result['content_url']

            # Save validation results
            cur.execute("""
                INSERT INTO pa.link_validation_results
                (content_url, total_links, broken_links, valid_links, broken_link_details)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                content_url,
                validation_result['total_links'],
                len(validation_result['broken_links']),
                validation_result['valid_links'],
                json.dumps(validation_result['broken_links'])
            ))

            # If broken links found, move back to pending
            if validation_result['has_broken_links']:
                # Delete from output table (Redshift or PostgreSQL)
                output_cur.execute("""
                    DELETE FROM pa.content_urls_joep
                    WHERE url = %s
                """, (content_url,))

                # Delete from tracking table
                cur.execute("""
                    DELETE FROM pa.jvs_seo_werkvoorraad_kopteksten_check
                    WHERE url = %s
                """, (content_url,))

                # Reset kopteksten flag
                cur.execute("""
                    UPDATE pa.jvs_seo_werkvoorraad
                    SET kopteksten = 0
                    WHERE url = %s
                """, (content_url,))

                moved_to_pending += 1

            results.append({
                'url': content_url,
                'total_links': validation_result['total_links'],
                'broken_links_count': len(validation_result['broken_links']),
                'broken_links': validation_result['broken_links'],
                'moved_to_pending': validation_result['has_broken_links']
            })

        conn.commit()
        output_conn.commit()

        cur.close()
        conn.close()
        output_cur.close()
        output_conn.close()

        return {
            "status": "success",
            "validated": len(rows),
            "moved_to_pending": moved_to_pending,
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/validation-history")
async def get_validation_history(limit: int = 20):
    """Get history of link validation results"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                content_url,
                total_links,
                broken_links,
                valid_links,
                broken_link_details,
                validated_at
            FROM pa.link_validation_results
            ORDER BY validated_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "status": "success",
            "results": rows
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/validation-history/reset")
async def reset_validation_history():
    """Reset all validation history - allows re-validation of all URLs"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Get count before deletion
        cur.execute("SELECT COUNT(*) as count FROM pa.link_validation_results")
        count = cur.fetchone()['count']

        # Delete all validation history
        cur.execute("DELETE FROM pa.link_validation_results")
        conn.commit()

        cur.close()
        conn.close()

        return {
            "status": "success",
            "message": f"Reset validation history for {count} URLs",
            "cleared_count": count
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
