# Thema Ads Script

Legacy script for Google Ads automation. Now uses environment variables for security.

## Setup

1. **Copy the example environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your credentials:**
   - Add your Google Ads OAuth credentials
   - Add Azure credentials (if using email features)
   - Update file paths if needed

3. **Install dependencies:**
   ```bash
   pip install -r ../requirements.txt
   ```

4. **Run the script:**
   ```bash
   python thema_ads
   ```

## Security

- ✅ All secrets are loaded from `.env` file
- ✅ `.env` file is in `.gitignore` (not committed to Git)
- ✅ `.env.example` provides template without real values

## Migration Notes

This script has been refactored to use environment variables instead of hardcoded credentials:
- `refresh_token` → `GOOGLE_REFRESH_TOKEN`
- `developer_token` → `GOOGLE_DEVELOPER_TOKEN`
- `login_customer_id` → `GOOGLE_LOGIN_CUSTOMER_ID`
- `mail_*` variables → `MAIL_*` environment variables
- File paths can be configured via env vars or use defaults

The script validates all required variables on startup and will fail with a clear error message if any are missing.
