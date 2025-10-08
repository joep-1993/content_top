# TASKS
_Active task tracking. Update when: starting work, completing tasks, finding blockers._

## Current Sprint
_Active tasks for immediate work_

## In Progress
_Tasks currently being worked on_

## Completed
_Finished tasks (move here when done)_

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
