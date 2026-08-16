# Security Policy

## Reporting a Vulnerability

If you find a security issue, please do NOT open a public issue.
Contact the maintainers via private channels.

## Data Protection

- API keys are stored in `%USERPROFILE%\BiliLearn\Data\config.json` by default (local only)
- B站 cookies are stored in `%USERPROFILE%\BiliLearn\Data\bilibili_cookies.json` by default (local only)
- Set `BILI_USER_DATA_DIR` before startup to use a different private-data root
- Export backups mask sensitive data via `sanitize_config_for_export()`
- Factory reset (`R` command) clears all local data including cookies/config/logs
