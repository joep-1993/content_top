# CLAUDE.md

This project uses the CC1 documentation system for knowledge management.

## Tech Stack
- **Backend**: FastAPI with auto-reload
- **Frontend**: Static files with Bootstrap CDN (no build tools)
- **Database**: PostgreSQL in Docker
- **AI**: OpenAI API configured in gpt_service.py

## Development Workflow
1. Run `docker-compose up` to start everything
2. Edit files directly - they auto-reload
3. Access at http://localhost:8001

## Important Notes
- **No Build Tools**: Edit HTML/CSS/JS directly
- **Docker First**: Everything runs in containers
- **Simple Scale**: Designed for small teams (1-10 users)

## CC1 Documentation
- `cc1/TASKS.md` - Current work tracking
- `cc1/LEARNINGS.md` - Knowledge capture
- `cc1/BACKLOG.md` - Future planning
- `cc1/PROJECT_INDEX.md` - Technical reference

## File Locations
- API: `backend/main.py`
- AI: `backend/gpt_service.py`
- UI: `frontend/index.html`
- Styles: `frontend/css/style.css`
- JS: `frontend/js/app.js`

---
_Template initialized: 2025-09-30_
