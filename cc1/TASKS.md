# TASKS
_Active task tracking. Update when: starting work, completing tasks, finding blockers._

## Current Sprint
_Active tasks for immediate work_

## In Progress
_Tasks currently being worked on_

## Completed
_Finished tasks (move here when done)_

- [x] Fix Recent Results timestamps showing N/A by querying local PostgreSQL and conditionally hiding timestamps in frontend when unavailable #claude-session:2025-10-20
- [x] Add conservative mode to link validator (0.5-0.7s delay per link check, forced 1 worker, checkbox UI) #claude-session:2025-10-17
- [x] Create deduplication utility script removing 48,846 duplicate records (108,722→59,876 unique URLs) #claude-session:2025-10-17
- [x] Create werkvoorraad synchronization utility script updating 17,672 URLs from pending to processed #claude-session:2025-10-17
- [x] Fix date display showing "1-1-1970, 01:00:00" to show "N/A" when created_at is null #claude-session:2025-10-17
- [x] Update ARCHITECTURE.md with UI theme documentation (color codes, usage map, conservative mode) #claude-session:2025-10-17
- [x] Customize UI theme with brand colors (#059CDF blue, #9C3095 purple, #A0D168 green) using CSS custom properties #claude-session:2025-10-17
- [x] Add conservative mode option for cautious scraping (0.5-0.7s delay, forced 1 worker, checkbox UI) #claude-session:2025-10-17
- [x] Optimize scraper delay from 0.5-0.7s to 0.2-0.3s based on rate limit testing (2-3x speed improvement) #claude-session:2025-10-17
- [x] Conduct comprehensive rate limit testing showing NO rate limiting even at 0s delay with whitelisted IP (87.212.193.148) #claude-session:2025-10-17
- [x] Create comprehensive ARCHITECTURE.md documenting system design, technology choices, and architectural decisions for future reference #claude-session:2025-10-16
- [x] Update scraper user agent from generic Chrome UA to 'Beslist script voor SEO' for better traffic identification in server logs #claude-session:2025-10-16
- [x] Create /skip-permissions and /restore-permissions slash commands for quick permission mode toggling #claude-session:2025-10-16
- [x] Switch input table to pa.jvs_seo_werkvoorraad_shopping_season (updated all 6 references in backend/main.py, reset tracking table with 72,992 URLs ready for processing) #claude-session:2025-10-15
- [x] Optimize content generation performance (30-50% faster: 0.2-0.3s delay, lxml parser, 300 max_tokens, batched commits, executemany) #claude-session:2025-10-10
- [x] Fix URL filtering to allow failed/skipped URL retries (filter only successful, add ON CONFLICT handling) #claude-session:2025-10-10
- [x] Fix Recent Results font size issue (replace Bootstrap .small with explicit font-size) #claude-session:2025-10-10
- [x] Add manual URL input field to Upload URLs (textarea with uploadManualUrls function) #claude-session:2025-10-10
- [x] Configure VPN split tunneling to bypass scraper traffic to whitelisted IP (87.212.193.148) #claude-session:2025-10-10
- [x] Integrate Redshift for output tables (pa.jvs_seo_werkvoorraad, pa.content_urls_joep) with hybrid architecture #claude-session:2025-10-08
- [x] Clean up 1,903 URLs with numeric-only link text from Redshift, reset to pending #claude-session:2025-10-08
- [x] Remove batch size upper limit for link validation (batch_size: min 1, no max) #claude-session:2025-10-07
- [x] Remove batch size upper limit for SEO content generation (now unlimited) #claude-session:2025-10-07
- [x] Implement hyperlink validation feature with parallel processing (301/404 detection, auto-reset to pending) #claude-session:2025-10-07
- [x] Create CSV import script for pre-generated content (19,791 items imported) #claude-session:2025-10-07
- [x] Change frontend port from 8001 to 8003 (avoid port conflicts) #claude-session:2025-10-07
- [x] Reorganize frontend UI (Link Validation moved between SEO Generation and Status) #claude-session:2025-10-07
- [x] Optimize slow database queries in status endpoint (NOT IN → LEFT JOIN, add status index) #claude-session:2025-10-04
- [x] Fix CSV export formatting (UTF-8 encoding, newline removal, proper quoting) #claude-session:2025-10-04
- [x] Fix HTML rendering bug causing browser to auto-link HTML tags #claude-session:2025-10-04
- [x] Fix AI prompt to generate shorter hyperlink text #claude-session:2025-10-04
- [x] Display full URLs in frontend Recent Results #claude-session:2025-10-04
- [x] Add contract/collapse button for expanded content #claude-session:2025-10-04
- [x] Add parallel processing with configurable workers (1-10) #claude-session:2025-10-03
- [x] Add upload URLs functionality with duplicate detection #claude-session:2025-10-03
- [x] Add export functionality (CSV/JSON) #claude-session:2025-10-03
- [x] Add delete result and reset to pending functionality #claude-session:2025-10-03
- [x] Track skipped/failed URLs separately from pending #claude-session:2025-10-03
- [x] Add expandable full content view in Recent Results #claude-session:2025-10-03
- [x] Separate content_top and theme_ads into independent repositories #claude-session:2025-10-03
- [x] Create frontend interface on http://localhost:8001/static/index.html with batch processing #claude-session:2025-10-03
- [x] Add "Process All URLs" button with progress tracking and stop functionality #claude-session:2025-10-03
- [x] Clean backend/main.py to only include SEO content generation endpoints #claude-session:2025-10-03
- [x] Update docker-compose.yml to remove theme_ads dependencies #claude-session:2025-10-03
- [x] Update CLAUDE.md to reflect content_top as SEO-only project #claude-session:2025-10-03
- [x] Initialize project from template #claude-session:2025-09-30

## Blocked
_Tasks waiting on dependencies_

---

## Task Tags Guide
- `#priority:` high | medium | low
- `#estimate:` estimated time (5m, 1h, 2d)
- `#blocked-by:` what's blocking this task
- `#claude-session:` date when Claude worked on this
