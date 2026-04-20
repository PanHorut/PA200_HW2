# PA200 Homework 2 - Todo App

A simple task manager web application built with Flask and PostgreSQL, designed for deployment on Azure PaaS services.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The app runs at http://localhost:8000 using SQLite by default.


## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────────┐
│   Browser   │────>│  Azure App       │────>│  PostgreSQL        │
│             │     │  Service (F1)    │     │  Flexible Server   │
└──────┬──────┘     └──────────────────┘     └────────────────────┘
       │
       │  static assets (CSS/JS/images)
       ▼
┌──────────────────┐
│  Azure Blob      │
│  Storage         │
│  ├─ static/      │  (public)
│  └─ uploads/     │  (private, SAS tokens)
└──────────────────┘
```

## Tech Stack

- **Backend**: Python 3.12, Flask, SQLAlchemy
- **Database**: PostgreSQL (Azure Flexible Server)
- **Storage**: Azure Blob Storage
- **Hosting**: Azure App Service (Free tier)
- **CI/CD**: GitHub Actions
