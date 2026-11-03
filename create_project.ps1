# setup.ps1 - Complete GBMS Project Creator
# Run this file to create everything automatically

Write-Host "🏭 Creating Gas Business Management System..." -ForegroundColor Green
Write-Host "📁 Location: $PWD" -ForegroundColor Yellow

# ============================================
# CREATE ALL DIRECTORIES
# ============================================
$directories = @(
    "config",
    "apps/accounts",
    "apps/dashboard", 
    "apps/customers",
    "apps/products",
    "apps/deliveries",
    "apps/payments",
    "apps/cylinders",
    "static/css",
    "static/js",
    "static/img",
    "templates/accounts",
    "templates/dashboard",
    "templates/customers",
    "templates/products",
    "templates/deliveries",
    "templates/payments",
    "templates/cylinders",
    "media",
    "logs"
)

foreach ($dir in $directories) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Write-Host "  ✓ Created: $dir" -ForegroundColor Cyan
}

# Create __init__.py files
$initFiles = @(
    "apps/__init__.py",
    "apps/accounts/__init__.py",
    "apps/dashboard/__init__.py",
    "apps/customers/__init__.py",
    "apps/products/__init__.py",
    "apps/deliveries/__init__.py",
    "apps/payments/__init__.py",
    "apps/cylinders/__init__.py",
    "config/__init__.py"
)

foreach ($file in $initFiles) {
    New-Item -ItemType File -Force -Path $file | Out-Null
}

Write-Host "`n✅ Directory structure created!" -ForegroundColor Green
Write-Host "📝 Creating all files..." -ForegroundColor Yellow

# ============================================
# ROOT FILES
# ============================================

# requirements.txt
@"
Django>=4.2,<5
djangorestframework>=3.15
django-cors-headers>=3.14
openpyxl>=3.1
python-dotenv>=1.0
reportlab>=3.6
django-allauth>=0.53
psycopg2-binary>=2.9
django-crispy-forms>=2.0
crispy-bootstrap5>=0.7
Pillow>=10.0
whitenoise>=6.5
"@ | Out-File -FilePath "requirements.txt"

# .env
@"
SECRET_KEY=django-insecure-change-this-in-production-123456789
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
SESSION_INACTIVITY_TIMEOUT=5
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
"@ | Out-File -FilePath ".env"

# manage.py
@"
#!/usr/bin/env python
import os
import sys

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
"@ | Out-File -FilePath "manage.py"

# run.bat
@"
@echo off
echo Starting Gas Business Management System...
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
"@ | Out-File -FilePath "run.bat"

# run.ps1
@"
Write-Host "Starting Gas Business Management System..." -ForegroundColor Green
if (-not (Test-Path -Path .venv)) {
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
Write-Host "`nCreate a superuser account:" -ForegroundColor Yellow
python manage.py createsuperuser
Start-Process "http://127.0.0.1:8000/"
python manage.py runserver 127.0.0.1:8000
"@ | Out-File -FilePath "run.ps1"

# README.md
@"
# 🏭 Gas Business Management System

A comprehensive web-based management system for gas cylinder businesses.

## 🚀 Quick Start

### Windows
Double-click `run.bat` or run:
```powershell
.\run.ps1