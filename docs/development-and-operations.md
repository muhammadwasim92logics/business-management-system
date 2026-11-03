# Development and operations

## Prerequisites

- Windows for the supplied PowerShell and batch launchers.
- Python compatible with Django 4.2.
- Internet access for dependency installation and for browser-loaded CSS/JavaScript/fonts from the CDNs currently referenced in shared templates.
- A writable project directory. SQLite, media, logs, and backup paths are local filesystem paths.

The supplied launch scripts expect a Windows virtual environment at `.venv\Scripts\python.exe`.

## Install and run

From the project root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py runserver 127.0.0.1:8000
```

If PowerShell refuses to activate the virtual environment, either use an approved local execution policy or call the environment interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/>. The root redirects to the dashboard; sign in at `/auth/login/` or create an account at `/auth/signup/`. Account creation uses Django's built-in user creation form. The command `createsuperuser` is available for Django admin access.

### Windows launchers

| Script | Behavior |
|---|---|
| `run.ps1` | Creates `.venv` if absent, activates it, upgrades pip, installs requirements, runs migrations, opens the local URL, and starts `runserver`. |
| `start_gbms.ps1` | Performs the same setup, registers/overwrites the `GBMS Notification Checks` hourly Windows scheduled task, opens the local URL, and starts `runserver`. |
| `run.bat` | Launches `start_gbms.ps1` using hidden PowerShell. Despite the filename, it delegates to the starter that registers the notification task. |
| `start_gbms.bat` | Also launches `start_gbms.ps1` in hidden PowerShell. |
| `start_gbms_hidden.vbs` | Hidden-window launcher used by the desktop shortcut workflow. |
| `CreateDesktopShortcut.ps1` | Creates/replaces a `GBMS.lnk` shortcut on the Windows desktop; uses the icon assets where available. |
| `run_notification_checks.ps1` | Runs `.venv\Scripts\python.exe manage.py check_notifications` from the project root. |

The starters install dependencies and run migrations each time they are launched. `start_gbms.ps1` schedules notification checks hourly, starting at the configured task start time in the script. It does not configure a production web server.

## Database and migrations

The default database engine is SQLite and the configured file is `db.sqlite3` in the project root. An existing `db.sqlite3` is present in this workspace; treat its contents as private operational data. Do not overwrite or migrate a valuable database without a separate backup.

Useful commands:

```powershell
python manage.py showmigrations
python manage.py migrate
python manage.py makemigrations
python manage.py sqlmigrate customers 0001
```

There are app migrations for customers, cylinders, deliveries, earnings, FBR, notifications, payments, products, and suppliers. Apply migrations after installing/updating the application. Review generated migrations and back up live data before applying schema changes.

### Optional data commands

```powershell
python manage.py create_walkin_customer
python manage.py add_products
python manage.py assign_invoice_numbers
python manage.py check_notifications
```

- `create_walkin_customer` creates a default walk-in customer if one is not already present.
- `add_products` adds a fixed catalog of product names with default zero prices and nonzero initial stock when those names do not already exist. **Run only against a disposable/development database unless those initial quantities are intended.**
- `assign_invoice_numbers` fills missing delivery FBR invoice numbers. Review the current data and command source before running on production.
- `check_notifications` creates notifications for matching rule conditions; it is safe to run on demand but persists new records.

These commands modify database state. Run them intentionally.

## Tests and checks

The project uses Django `TestCase` tests in app-local `tests.py` files. Run the full suite with:

```powershell
python manage.py check
python manage.py test
```

Run focused app tests while iterating:

```powershell
python manage.py test apps.deliveries
python manage.py test apps.customers
python manage.py test apps.products
python manage.py test apps.suppliers
python manage.py test apps.fbr
python manage.py test apps.notifications
```

The current tests cover account CSRF/session behavior, customer and delivery ledger/accounting behavior, stock and factory fills, supplier purchase flows, FBR report calculations and number assignment, notification/backup behavior, earnings operations, and dashboard summaries. Use the test output as the baseline for any behavior changes.

## Configuration reference

The active Django configuration is [`config/settings.py`](../config/settings.py). It loads a root `.env` file if present (without overwriting variables already set by the process) and otherwise reads environment variables directly. UTF-8 and Windows PowerShell UTF-16 `.env` files are supported. Start from [`.env.example`](../.env.example); never commit the real `.env`.

| Setting/concern | Current implementation | Before deployment |
|---|---|---|
| Django secret | `DJANGO_SECRET_KEY`, falling back to legacy `SECRET_KEY`. If absent, a random development key is generated only while debug mode is enabled; sessions will not survive an application restart unless a key is configured. | Set a newly generated secret outside source control. `DEBUG=false` without a secret fails during startup. Rotate exposed values. |
| Debugging | `DJANGO_DEBUG` (or legacy `DEBUG`), defaulting to `true` for local development | Set `DJANGO_DEBUG=false` in production. |
| Hosts | `DJANGO_ALLOWED_HOSTS` (or legacy `ALLOWED_HOSTS`), comma-separated; defaults to local/test hosts | Set the exact production host names. |
| Database | SQLite file at project root | Choose and configure a production database deliberately; PostgreSQL driver availability alone does not enable PostgreSQL. |
| Time zone | `Asia/Karachi`, timezone support enabled | Confirm this matches the business's operating dates. |
| CSRF/Cookies | `DJANGO_CSRF_TRUSTED_ORIGINS` is comma-separated; defaults are local origins. Secure CSRF and session cookies follow `DEBUG`; session lifetime remains long-lived. | Configure HTTPS origins, secure cookies, session lifetime, and CSRF policy for the real deployment. |
| Email | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, and `EMAIL_BACKUP_TO`. Credentials default to empty; the backup recipient defaults to the non-deliverable reserved `example.invalid` domain. | Set private mail configuration and a real backup recipient through the secret store/environment before enabling email backups. |
| `.env` | Loaded from the project root through `python-dotenv`; process variables take precedence. | Keep `.env` local and untracked; never commit secrets. |
| Static/media | `static/`, `staticfiles/`, and `media/` paths are configured; development URL configuration serves files only when `DEBUG` is true | Configure production static collection/serving and private media storage explicitly. WhiteNoise is a dependency but is not configured in the inspected middleware. |
| CORS | `django-cors-headers` middleware is installed; no explicit cross-origin allowlist was found in the settings | Decide whether cross-origin access is needed and configure a narrow policy; do not assume the package implies permissive CORS. |
| `.env` package | `python-dotenv` is listed, but no settings loader is present | Do not treat it as active configuration. |

Do not copy local secret or mail settings into documentation, issue reports, sample files, screenshots, or commits. If an actual credential has been pushed to a remote, deleting it from the latest file alone is insufficient; rotate it and follow the host's secret-removal procedure.

## Dependencies and runtime integrations

`requirements.txt` lists:

| Dependency | Role in current project |
|---|---|
| Django | Web framework, ORM, auth, templates, management commands |
| Django REST Framework | Installed app; no DRF API views/routers found |
| django-cors-headers | Middleware is enabled; no explicit allow-origin policy found |
| openpyxl, ReportLab | Listed packages; no application call sites found in the inspected Python source |
| python-dotenv | Listed package; settings do not load `.env` |
| django-allauth | Listed package; not configured as an installed app or routed authentication workflow |
| psycopg2-binary | PostgreSQL driver; current database engine is SQLite |
| django-crispy-forms, crispy-bootstrap5 | Form rendering integration configured in settings |
| Pillow | Image library used by the desktop shortcut script if it must build an icon |
| whitenoise | Listed package; not configured in middleware/settings as the static-file server |

Shared templates reference Bootstrap 5, Font Awesome, Choices.js, Google Fonts, and Chart.js from external CDNs. They are not vendored in the repository; network access to those services affects page styling and JavaScript features.

## Backup and recovery

The notification UI provides an email backup action and a local ZIP download. The ZIP payload contains the SQLite database if it exists, all files under `media/`, and a metadata JSON file. The email action sends through the configured SMTP backend and is limited to one successful email backup per day.

Operational guidance:

1. Confirm backup success in the UI and notification list; a generated file is not proof of successful email delivery.
2. Store downloaded/emailed backups in access-controlled storage, separate from the machine running the application.
3. Test restore procedures on a separate copy before relying on a backup.
4. Protect database, media, `.env`, logs, and backup archives as confidential.
5. The current backup payload does not include source code or a general deployment configuration.

## Public repository and production readiness

The current workspace is **not ready to publish or deploy as-is**:

1. **Keep secrets external.** Django and SMTP secrets are read from environment configuration; the local `.env` is ignored. Set a unique secret key and private mail settings outside source control. Rotate credentials previously exposed in an earlier version or other remote.
2. **Do not publish local data.** The workspace contains `.env`, `db.sqlite3`, backup database files, `media/`, `logs/`, and `output.txt`. Inspect the exact Git staging set before every push; these files may contain credentials, customer information, financial records, and operational traces.
3. **Add repository hygiene before first Git initialization.** No `.gitignore` or `.git` directory was present in the inspected workspace. Define exclusions for virtual environments, secrets, databases, backups, media, logs, caches, and local generated files before staging.
4. **Replace development settings.** Disable debug mode; set host/CSRF policy; use secret management; configure HTTPS, secure cookies, and shorter session duration; select the production database and static/media strategy.
5. **Choose a production server and deployment design.** The included scripts use Django's development server. WSGI/ASGI modules exist, but no production server, container definition, reverse-proxy config, deployment workflow, or production-ready schedule service is supplied.
6. **Review access and request protections.** Some lookup routes are not login-decorated and several internal JSON write routes are CSRF-exempt. Decide intended exposure and harden accordingly before making the application internet-facing.
7. **Verify external dependencies and backups.** Confirm CDN availability/licensing policy, mail connectivity, a real `EMAIL_BACKUP_TO` recipient, backup delivery, and a tested restore process. The default backup address is intentionally non-deliverable.

The repository root is not currently a Git working tree, so documentation changes here are local files only. Create/initialize the intended GitHub repository and review the staging contents separately.

## Troubleshooting

| Symptom | Checks |
|---|---|
| `ModuleNotFoundError` while starting | Activate `.venv` or use its interpreter, then install `requirements.txt`. Confirm the same interpreter runs `manage.py`. |
| Missing database tables / `no such table` | From the project root, run `python manage.py showmigrations` and `python manage.py migrate` against the intended database. |
| Login redirects back to login | Confirm signup completed, the same database is used by the server, and session/cookie settings and browser cookies are not stale. |
| Port 8000 is occupied | Start `runserver` with a different local port, e.g. `python manage.py runserver 127.0.0.1:8001`; open that same port in the browser. |
| Static assets or interactive controls missing | Check the browser network for CDN failures and verify `static/` exists. The shared UI loads some libraries externally. For production, configure static collection and serving explicitly. |
| Backup email fails | Check network access and private SMTP configuration; use the UI's reported failure details without exposing credentials. A failed send is not a successful backup. |
| No scheduled notifications | Run `python manage.py check_notifications` manually, then verify the `GBMS Notification Checks` Windows scheduled task and its action path/interpreter. `run.ps1` does not register the task; `start_gbms.ps1` does. |
| Application uses unexpected data | Check `BASE_DIR` and the configured SQLite path in `config/settings.py`; the running process may be opening a different project copy/database. |
| FBR numbers appear unexpected | Review the registered `apps.fbr.signals` pre-save logic, `DeliveryInvoiceSequence`, selected report grouping, existing conflicts, and any prior use of `assign_invoice_numbers`. Back up before bulk operations. |
| Signup exists but admin access is unavailable | Create a Django superuser with `python manage.py createsuperuser`; application signup creates a normal user, not automatically a staff account. |
