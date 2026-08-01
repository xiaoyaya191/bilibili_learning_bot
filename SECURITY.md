# Security Policy

## Reporting a Vulnerability

If you find a security issue, please do NOT open a public issue.
Contact the maintainers via private channels.

## Data Protection

- API keys are stored in `Data/config.json` (local only)
- B站 cookies are stored in `Data/bilibili_cookies.json` (local only)
- Export backups mask sensitive data via `sanitize_config_for_export()`
- Factory reset (`R` command) clears all local data including cookies/config/logs
