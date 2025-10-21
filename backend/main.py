from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from datetime import datetime
from io import StringIO, BytesIO
import csv
import json
import os
import asyncio
import tempfile
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from backend.database import get_db_connection, get_output_connection, return_db_connection, return_output_connection
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

def process_single_url(url: str, conservative_mode: bool = False):
    """Process a single URL - runs in thread pool
    Returns tuple: (result_dict, redshift_operations)

    Args:
        url: URL to process
        conservative_mode: If True, use conservative scraping rate (max 2 URLs/sec)
    """
    result = {"url": url, "status": "pending"}
    redshift_ops = []  # Store Redshift operations to batch later
    conn = None
    final_status = None
    final_reason = None

    try:
        # Scrape the URL first (no DB operations yet)
        scraped_data = scrape_product_page(url, conservative_mode=conservative_mode)

        if not scraped_data:
            final_status = 'failed'
            final_reason = 'scraping_failed'
            result["status"] = "failed"
            result["reason"] = "scraping_failed"
            # DO NOT mark as processed in Redshift - keep in pending for retry
            # Scraping failures (503, timeouts, access denied) should be retried later
        elif not scraped_data['products'] or len(scraped_data['products']) == 0:
            final_status = 'skipped'
            final_reason = 'no_products_found'
            result["status"] = "skipped"
            result["reason"] = "no_products_found"
            # Mark as processed in Redshift to avoid re-fetching
            redshift_ops.append(('update_werkvoorraad', url))
        else:
            # Generate AI content
            try:
                print(f"[DEBUG] Generating AI content for {url[:80]}... with {len(scraped_data['products'])} products")
                ai_content = generate_product_content(
                    scraped_data['h1_title'],
                    scraped_data['products']
                )
                print(f"[DEBUG] AI content generated, length: {len(ai_content)}")

                # Sanitize content for SQL
                sanitized = sanitize_content(ai_content)

                # Check if content has valid links
                has_valid_links = check_content_has_valid_links(ai_content)
                print(f"[DEBUG] Generated content for {url[:80]}... - Has valid links: {has_valid_links}")
                print(f"[DEBUG] Content preview: {ai_content[:200]}...")

                if not has_valid_links:
                    final_status = 'failed'
                    final_reason = 'no_valid_links'
                    result["status"] = "failed"
                    result["reason"] = "no_valid_links"
                    # Mark as processed in Redshift to avoid re-fetching
                    redshift_ops.append(('update_werkvoorraad', url))
                else:
                    # Collect Redshift operations for batch execution
                    redshift_ops.append(('insert_content', url, sanitized))
                    redshift_ops.append(('update_werkvoorraad', url))

                    final_status = 'success'
                    result["status"] = "success"
                    result["content_preview"] = ai_content[:100] + "..."

            except Exception as e:
                final_status = 'failed'
                final_reason = f"ai_generation_error: {str(e)}"
                result["status"] = "failed"
                result["reason"] = f"ai_generation_error: {str(e)}"
                # Mark as processed in Redshift to avoid re-fetching
                redshift_ops.append(('update_werkvoorraad', url))

        # Single DB transaction at the end with final status
        conn = get_db_connection()
        cur = conn.cursor()

        if final_reason:
            cur.execute("""
                INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url, status, skip_reason)
                VALUES (%s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, skip_reason = EXCLUDED.skip_reason
            """, (url, final_status, final_reason))
        else:
            cur.execute("""
                INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url, status)
                VALUES (%s, %s)
                ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, skip_reason = NULL
            """, (url, final_status))

        conn.commit()
        print(f"[PROCESSING] {url} - Status: {final_status}" + (f" - Reason: {final_reason}" if final_reason else ""))
        return (result, redshift_ops)

    except Exception as e:
        result["status"] = "failed"
        result["reason"] = f"error: {str(e)}"
        # Try to record error in DB
        try:
            if not conn:
                conn = get_db_connection()
                cur = conn.cursor()
            cur.execute("""
                INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url, status, skip_reason)
                VALUES (%s, 'failed', %s)
                ON CONFLICT (url) DO UPDATE SET status = 'failed', skip_reason = EXCLUDED.skip_reason
            """, (url, f"error: {str(e)}"))
            conn.commit()
        except:
            pass  # If DB fails, just return the result
        return (result, redshift_ops)
    finally:
        if conn:
            cur.close()
            return_db_connection(conn)  # Return connection to pool instead of closing

@app.post("/api/process-urls")
async def process_urls(batch_size: int = 2, parallel_workers: int = 1, conservative_mode: bool = False):
    """
    Process batch of URLs for SEO content generation.
    Fetches specified number of URLs, scrapes content, generates AI text, and saves to database.
    Supports parallel processing with configurable workers.

    Args:
        batch_size: Number of URLs to process
        parallel_workers: Number of parallel workers (1-10), ignored if conservative_mode is True
        conservative_mode: If True, use conservative scraping rate (max 2 URLs/sec) with 1 worker. Default: False
    """
    try:
        # Validate parameters
        if batch_size < 1:
            raise HTTPException(status_code=400, detail="Batch size must be at least 1")

        if parallel_workers < 1 or parallel_workers > 10:
            raise HTTPException(status_code=400, detail="Parallel workers must be between 1 and 10")

        # Conservative mode always uses 1 worker for maximum safety
        if conservative_mode:
            parallel_workers = 1

        # Get unprocessed URLs from Redshift
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        # Get successfully processed URLs from local tracking
        local_conn = get_db_connection()
        local_cur = local_conn.cursor()
        local_cur.execute("""
            SELECT url FROM pa.jvs_seo_werkvoorraad_kopteksten_check
            WHERE status = 'success'
        """)
        successfully_processed_urls = set(row['url'] for row in local_cur.fetchall())
        local_cur.close()
        return_db_connection(local_conn)

        # Fetch URLs from Redshift - get 2x batch_size to account for filtering
        output_cur.execute("""
            SELECT url FROM pa.jvs_seo_werkvoorraad_shopping_season
            WHERE kopteksten = 0
            LIMIT %s
        """, (batch_size * 2,))

        all_rows = output_cur.fetchall()
        # Filter out successfully processed URLs
        rows = [row for row in all_rows if row['url'] not in successfully_processed_urls][:batch_size]
        output_cur.close()
        return_output_connection(output_conn)  # Return to pool

        if not rows:
            return {
                "status": "complete",
                "message": "No URLs to process",
                "processed": 0
            }

        urls = [row['url'] for row in rows]

        # Process URLs in parallel using ThreadPoolExecutor
        # Use partial to bind conservative_mode parameter
        process_func = partial(process_single_url, conservative_mode=conservative_mode)
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            result_tuples = list(executor.map(process_func, urls))

        # Separate results and Redshift operations
        results = []
        all_redshift_ops = []
        for result, ops in result_tuples:
            results.append(result)
            all_redshift_ops.extend(ops)

        # Batch execute all Redshift operations using executemany() for better performance
        if all_redshift_ops:
            output_conn = get_output_connection()
            output_cur = output_conn.cursor()
            try:
                # Separate operations by type for batch execution
                insert_content_data = []
                update_werkvoorraad_urls = []

                for op in all_redshift_ops:
                    if op[0] == 'insert_content':
                        _, url, content = op
                        insert_content_data.append((url, content))
                    elif op[0] == 'update_werkvoorraad':
                        _, url = op
                        update_werkvoorraad_urls.append((url,))

                # Use COPY for Redshift (5-10x faster) or executemany for PostgreSQL
                use_redshift = os.getenv("USE_REDSHIFT_OUTPUT", "false").lower() == "true"

                if insert_content_data:
                    if use_redshift:
                        # Use COPY command for Redshift (much faster for bulk inserts)
                        buffer = StringIO()
                        for url, content in insert_content_data:
                            # Escape tabs and newlines in content
                            content_escaped = content.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
                            buffer.write(f"{url}\t{content_escaped}\n")
                        buffer.seek(0)
                        output_cur.copy_from(buffer, 'pa.content_urls_joep', columns=['url', 'content'], sep='\t')
                    else:
                        # Use executemany for PostgreSQL
                        output_cur.executemany("""
                            INSERT INTO pa.content_urls_joep (url, content)
                            VALUES (%s, %s)
                        """, insert_content_data)

                # Batch UPDATE using executemany()
                if update_werkvoorraad_urls:
                    output_cur.executemany("""
                        UPDATE pa.jvs_seo_werkvoorraad_shopping_season
                        SET kopteksten = 1
                        WHERE url = %s
                    """, update_werkvoorraad_urls)

                output_conn.commit()
            finally:
                output_cur.close()
                return_output_connection(output_conn)  # Return to pool

        processed_count = sum(1 for r in results if r['status'] == 'success')
        skipped_count = sum(1 for r in results if r['status'] == 'skipped')
        failed_count = sum(1 for r in results if r['status'] == 'failed')

        print(f"[BATCH COMPLETE] Processed: {processed_count}/{len(urls)} | Skipped: {skipped_count} | Failed: {failed_count}")

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
        output_cur.execute("SELECT COUNT(*) as total FROM pa.jvs_seo_werkvoorraad_shopping_season")
        total = output_cur.fetchone()['total']

        # Get processed URLs (actual content records in Redshift)
        output_cur.execute("SELECT COUNT(*) as processed FROM pa.content_urls_joep")
        processed = output_cur.fetchone()['processed']

        # Get local tracking for skipped/failed stats
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

        # Get pending URLs directly from Redshift (URLs with kopteksten=0)
        output_cur.execute("SELECT COUNT(*) as pending FROM pa.jvs_seo_werkvoorraad_shopping_season WHERE kopteksten = 0")
        pending = output_cur.fetchone()['pending']

        # Get recent results from the output database (Redshift or PostgreSQL)
        # Note: Redshift table may not have id or created_at columns, so we just get 5 rows
        try:
            output_cur.execute("""
                SELECT url, content
                FROM pa.content_urls_joep
                LIMIT 5
            """)
            recent_rows = output_cur.fetchall()
            recent = [{'url': r['url'], 'content': r['content'], 'created_at': None} for r in recent_rows]
        except Exception as e:
            print(f"[DEBUG] Failed to get recent results: {e}")
            recent = []

        cur.close()
        return_db_connection(conn)
        output_cur.close()
        return_output_connection(output_conn)

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
        return_db_connection(conn)

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
        return_db_connection(conn)

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

        # Insert URLs into Redshift work queue
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        added_count = 0
        duplicate_count = 0

        for url in urls:
            try:
                output_cur.execute("""
                    INSERT INTO pa.jvs_seo_werkvoorraad_shopping_season (url, kopteksten)
                    VALUES (%s, 0)
                    ON CONFLICT (url) DO NOTHING
                """, (url,))

                if output_cur.rowcount > 0:
                    added_count += 1
                else:
                    duplicate_count += 1

            except Exception as e:
                # Skip invalid URLs
                continue

        output_conn.commit()
        output_cur.close()
        return_output_connection(output_conn)

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
            UPDATE pa.jvs_seo_werkvoorraad_shopping_season
            SET kopteksten = 0
            WHERE url = %s
        """, (url,))

        output_conn.commit()
        output_cur.close()
        return_output_connection(output_conn)

        # Delete from local tracking table
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM pa.jvs_seo_werkvoorraad_kopteksten_check
            WHERE url = %s
        """, (url,))
        conn.commit()
        cur.close()
        return_db_connection(conn)

        return {
            "status": "success",
            "message": f"Result deleted and URL reset to pending",
            "url": url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def validate_single_content(content_data: tuple, conservative_mode: bool = False) -> dict:
    """Validate links in a single content item - runs in thread pool

    Args:
        content_data: Tuple of (content_url, content)
        conservative_mode: If True, use conservative rate (max 2 URLs/sec)
    """
    content_url, content = content_data

    # Validate links in content
    validation_result = validate_content_links(content, conservative_mode=conservative_mode)

    # Add the content URL to the result
    validation_result['content_url'] = content_url

    return validation_result

@app.post("/api/validate-links")
async def validate_links(batch_size: int = 10, parallel_workers: int = 3, conservative_mode: bool = False):
    """
    Validate hyperlinks in generated content.
    Checks if links return 301 or 404, and moves content back to pending if broken links found.
    Supports parallel processing with configurable workers.

    Args:
        batch_size: Number of content items to validate
        parallel_workers: Number of parallel workers (1-10), ignored if conservative_mode is True
        conservative_mode: If True, use conservative rate (max 2 URLs/sec) with 1 worker. Default: False
    """
    try:
        # Validate parameters
        if batch_size < 1:
            raise HTTPException(status_code=400, detail="Batch size must be at least 1")

        if parallel_workers < 1 or parallel_workers > 10:
            raise HTTPException(status_code=400, detail="Parallel workers must be between 1 and 10")

        # Conservative mode always uses 1 worker for maximum safety
        if conservative_mode:
            parallel_workers = 1

        # Get content from Redshift
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        # Get local PostgreSQL connection for validation tracking
        conn = get_db_connection()
        cur = conn.cursor()

        # Get validated URLs efficiently using a set for O(1) lookup
        cur.execute("SELECT content_url FROM pa.link_validation_results")
        validated_urls_set = set(row['content_url'] for row in cur.fetchall())

        # Fetch more content than needed, filter in Python (faster than NOT IN)
        output_cur.execute("""
            SELECT url, content
            FROM pa.content_urls_joep
            LIMIT %s
        """, (batch_size * 3 if validated_urls_set else batch_size,))

        all_rows = output_cur.fetchall()
        # Filter out already validated URLs in Python
        rows = [row for row in all_rows if row['url'] not in validated_urls_set][:batch_size]

        if not rows:
            output_cur.close()
            return_output_connection(output_conn)
            cur.close()
            return_db_connection(conn)
            return {
                "status": "complete",
                "message": "No content to validate",
                "validated": 0,
                "moved_to_pending": 0
            }

        # Prepare content items for parallel validation
        content_items = [(row['url'], row['content']) for row in rows]

        # Process validations in parallel using ThreadPoolExecutor
        # Use partial to bind conservative_mode parameter
        validate_func = partial(validate_single_content, conservative_mode=conservative_mode)
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            validation_results = list(executor.map(validate_func, content_items))

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
                    UPDATE pa.jvs_seo_werkvoorraad_shopping_season
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
        return_db_connection(conn)
        output_cur.close()
        return_output_connection(output_conn)

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
        return_db_connection(conn)

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
        return_db_connection(conn)

        return {
            "status": "success",
            "message": f"Reset validation history for {count} URLs",
            "cleared_count": count
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
