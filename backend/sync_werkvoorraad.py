"""
Synchronize werkvoorraad table with content_urls_joep
Marks URLs as processed (kopteksten=1) if they already have content
"""

from backend.database import get_db_connection, get_output_connection

def main():
    print("="*70)
    print("WERKVOORRAAD SYNCHRONIZATION SCRIPT")
    print("="*70)
    print("\nThis script will:")
    print("1. Find URLs in pa.content_urls_joep that have kopteksten=0")
    print("2. Update pa.jvs_seo_werkvoorraad_shopping_season to set kopteksten=1")
    print("3. Add tracking records to pa.jvs_seo_werkvoorraad_kopteksten_check")
    print("\nWARNING: Close all browser tabs and stop all processing before running!")
    print("="*70)

    input("\nPress Enter to continue or Ctrl+C to cancel...")

    try:
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        print("\nStep 1: Updating werkvoorraad table (this may take a few minutes)...")

        # Use efficient UPDATE with JOIN
        output_cur.execute("""
            UPDATE pa.jvs_seo_werkvoorraad_shopping_season w
            SET kopteksten = 1
            FROM pa.content_urls_joep c
            WHERE w.url = c.url AND w.kopteksten = 0
        """)

        updated_count = output_cur.rowcount
        output_conn.commit()
        print(f"  ✓ Updated {updated_count} URLs in werkvoorraad table")

        output_cur.close()
        output_conn.close()

        print("\nStep 2: Updating local tracking table...")

        # Update local PostgreSQL tracking
        local_conn = get_db_connection()
        local_cur = local_conn.cursor()

        # Get URLs from content table that aren't tracked yet
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        output_cur.execute("SELECT url FROM pa.content_urls_joep")
        content_urls = [row['url'] for row in output_cur.fetchall()]

        output_cur.close()
        output_conn.close()

        print(f"  Found {len(content_urls)} URLs with content")
        print(f"  Adding/updating tracking records...")

        # Batch insert/update
        batch_size = 1000
        inserted = 0

        for i in range(0, len(content_urls), batch_size):
            batch = content_urls[i:i+batch_size]

            for url in batch:
                local_cur.execute("""
                    INSERT INTO pa.jvs_seo_werkvoorraad_kopteksten_check (url, status)
                    VALUES (%s, 'success')
                    ON CONFLICT (url) DO UPDATE SET status = 'success', skip_reason = NULL
                """, (url,))

            local_conn.commit()
            inserted += len(batch)

            if inserted % 10000 == 0:
                print(f"    Progress: {inserted}/{len(content_urls)}")

        print(f"  ✓ Processed {len(content_urls)} tracking records")

        local_cur.close()
        local_conn.close()

        print("\nStep 3: Verification...")

        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        output_cur.execute("SELECT COUNT(*) as count FROM pa.content_urls_joep")
        content_count = output_cur.fetchone()['count']

        output_cur.execute("SELECT COUNT(*) as count FROM pa.jvs_seo_werkvoorraad_shopping_season WHERE kopteksten = 0")
        pending_count = output_cur.fetchone()['count']

        output_cur.execute("SELECT COUNT(*) as count FROM pa.jvs_seo_werkvoorraad_shopping_season WHERE kopteksten = 1")
        processed_count = output_cur.fetchone()['count']

        output_cur.close()
        output_conn.close()

        print(f"\nFinal counts:")
        print(f"  URLs with content: {content_count}")
        print(f"  Processed (kopteksten=1): {processed_count}")
        print(f"  Pending (kopteksten=0): {pending_count}")
        print(f"  Mismatch: {content_count - processed_count} URLs")

        if content_count - processed_count == 0:
            print("\n✅ All URLs synchronized successfully!")
        else:
            print(f"\n⚠️  Still {content_count - processed_count} URLs with content but not marked as processed")
            print("    This might be normal if content exists outside the werkvoorraad table")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
