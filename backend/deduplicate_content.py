"""
Deduplicate URLs in pa.content_urls_joep
Keeps one record per URL (randomly selected since no timestamp available)
"""

from backend.database import get_output_connection

def main():
    print("="*70)
    print("CONTENT DEDUPLICATION SCRIPT")
    print("="*70)
    print("\nThis script will:")
    print("1. Find duplicate URLs in pa.content_urls_joep")
    print("2. Keep one record per URL (random selection)")
    print("3. Delete all duplicate records")
    print("\nWARNING: This will permanently delete duplicate records!")
    print("="*70)

    input("\nPress Enter to continue or Ctrl+C to cancel...")

    try:
        output_conn = get_output_connection()
        output_cur = output_conn.cursor()

        print("\nStep 1: Analyzing duplicates...")

        # Count duplicates
        output_cur.execute("""
            SELECT COUNT(*) as dupe_count
            FROM (
                SELECT url
                FROM pa.content_urls_joep
                GROUP BY url
                HAVING COUNT(*) > 1
            ) dupes
        """)
        dupe_urls = output_cur.fetchone()['dupe_count']

        output_cur.execute("""
            SELECT SUM(count - 1) as total_dupes
            FROM (
                SELECT url, COUNT(*) as count
                FROM pa.content_urls_joep
                GROUP BY url
                HAVING COUNT(*) > 1
            ) dupes
        """)
        total_extra = output_cur.fetchone()['total_dupes']

        print(f"  URLs with duplicates: {dupe_urls}")
        print(f"  Extra records to remove: {total_extra}")

        if dupe_urls == 0:
            print("\n✓ No duplicates found!")
            return

        print("\nStep 2: Creating temporary table with unique URLs...")

        # Create temp table with deduplicated data using ROW_NUMBER
        output_cur.execute("""
            CREATE TEMP TABLE content_deduped AS
            SELECT url, content
            FROM (
                SELECT url, content,
                       ROW_NUMBER() OVER (PARTITION BY url ORDER BY content) as rn
                FROM pa.content_urls_joep
            )
            WHERE rn = 1
        """)

        output_cur.execute("SELECT COUNT(*) as count FROM content_deduped")
        unique_count = output_cur.fetchone()['count']
        print(f"  ✓ Created temp table with {unique_count} unique URLs")

        print("\nStep 3: Deleting all records from original table...")
        output_cur.execute("DELETE FROM pa.content_urls_joep")
        deleted = output_cur.rowcount
        print(f"  ✓ Deleted {deleted} records")

        print("\nStep 4: Inserting deduplicated data back...")
        output_cur.execute("""
            INSERT INTO pa.content_urls_joep (url, content)
            SELECT url, content
            FROM content_deduped
        """)
        inserted = output_cur.rowcount
        print(f"  ✓ Inserted {inserted} unique records")

        output_conn.commit()
        print("\nStep 5: Dropping temporary table...")
        output_cur.execute("DROP TABLE content_deduped")

        print("\nStep 6: Final verification...")

        output_cur.execute("SELECT COUNT(*) as count FROM pa.content_urls_joep")
        final_count = output_cur.fetchone()['count']

        output_cur.execute("""
            SELECT COUNT(*) as dupe_count
            FROM (
                SELECT url
                FROM pa.content_urls_joep
                GROUP BY url
                HAVING COUNT(*) > 1
            ) dupes
        """)
        remaining_dupes = output_cur.fetchone()['dupe_count']

        print(f"\nFinal counts:")
        print(f"  Total records: {final_count}")
        print(f"  Remaining duplicates: {remaining_dupes}")
        print(f"  Records removed: {deleted - inserted}")

        if remaining_dupes == 0:
            print("\n✅ Deduplication successful!")
        else:
            print(f"\n⚠️  Still {remaining_dupes} duplicate URLs remaining")

        output_cur.close()
        output_conn.close()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("\nRolling back changes...")
        try:
            output_conn.rollback()
        except:
            pass

if __name__ == "__main__":
    main()
