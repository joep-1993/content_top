# CLAUDE.md

This project is **Content Top** - an SEO content generation system.

## Tech Stack
- **Backend**: FastAPI with auto-reload
- **Frontend**: Static files with Bootstrap CDN (no build tools)
- **Database**: PostgreSQL in Docker
- **AI**: OpenAI API for content generation

## Development Workflow
1. Run `docker-compose up` to start everything
2. Edit files directly - they auto-reload
3. Access frontend at http://localhost:8001/static/index.html

## Important Notes
- **No Build Tools**: Edit HTML/CSS/JS directly
- **Docker First**: Everything runs in containers
- **Simple Scale**: Designed for small teams (1-10 users)

## File Locations
- API: `backend/main.py`
- AI Service: `backend/gpt_service.py`
- Scraper: `backend/scraper_service.py`
- Database: `backend/database.py`
- Frontend: `frontend/index.html`
- App Logic: `frontend/js/app.js`

## What It Does
Processes URLs from database, scrapes product information, generates AI-powered SEO content, and saves results.

---
_Project: Content Top | SEO Content Generation_
