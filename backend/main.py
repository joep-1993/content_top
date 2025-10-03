from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from backend.database import get_db_connection
from backend.scraper_service import scrape_product_page, sanitize_content
from backend.gpt_service import generate_product_content, check_content_has_valid_links

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
