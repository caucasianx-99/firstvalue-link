
# FirstValue Link

A lightweight beta feedback tool for early-stage SaaS founders.

FirstValue Link helps founders discover whether new users can complete a specific task in their product.

## Features

- Create beta tests with a product URL and task
- Generate shareable tester links
- Collect participant outcomes:
  - Completed
  - Stuck
  - Gave up
- Collect optional written feedback
- Store test data and responses in SQLite
- View feedback through a private founder dashboard
- Protect dashboard access with an owner token

## Tech Stack

- Python
- FastAPI
- SQLite
- HTML, CSS, JavaScript
- Uvicorn

## Run Locally

1. Create a virtual environment:

   py -m venv .venv

2. Install dependencies:

   .\.venv\Scripts\python.exe -m pip install -r requirements.txt

3. Start the development server:

   .\.venv\Scripts\python.exe -m uvicorn app:app --reload

4. Open:

   http://127.0.0.1:8000

## How It Works

1. A founder creates a test.
2. FirstValue Link generates a tester link and an owner token.
3. A participant opens the link and attempts the task.
4. The participant submits feedback.
5. The founder reviews responses in the dashboard.

## Current Status

Local MVP prototype.

The basic end-to-end workflow has been tested locally.

The application is not yet production-ready.
Security hardening, rate limiting, deployment configuration,
and real-user validation are still required.

## Security Notes

- Never commit the local SQLite database.
- Never publish owner tokens.
- Keep environment variables and secrets outside Git.
- Do not expose the development server publicly.
