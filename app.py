
import hashlib
import secrets
import sqlite3
from typing import Literal

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field, HttpUrl
from fastapi.responses import FileResponse


DATABASE = Path(__file__).parent / "firstvalue.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    with sqlite3.connect(DATABASE) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tests (
                id TEXT PRIMARY KEY,
                owner_token_hash TEXT NOT NULL,
                product_name TEXT NOT NULL,
                task TEXT NOT NULL,
                product_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        connection.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                id TEXT PRIMARY KEY,
                test_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (test_id) REFERENCES tests(id)
            )
        """)

    yield


app = FastAPI(
    title="FirstValue Link",
    version="0.2.0",
    lifespan=lifespan
)


class TestCreate(BaseModel):
    product_name: str = Field(min_length=2, max_length=100)
    task: str = Field(min_length=10, max_length=300)
    product_url: HttpUrl


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "FirstValue Link"
    }


@app.post("/api/tests", status_code=201)
def create_test(data: TestCreate):
    test_id = secrets.token_urlsafe(12)
    owner_token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(
        owner_token.encode("utf-8")
    ).hexdigest()

    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            """
            INSERT INTO tests (
                id,
                owner_token_hash,
                product_name,
                task,
                product_url,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                test_id,
                token_hash,
                data.product_name,
                data.task,
                str(data.product_url),
                created_at
            )
        )

    return {
        "test_id": test_id,
        "owner_token": owner_token,
        "message": "Test created successfully"
    }

@app.get("/api/tests/{test_id}")
def get_test(test_id: str):

    with sqlite3.connect(DATABASE) as connection:
        test = connection.execute(
            """
            SELECT product_name, task, product_url, created_at
            FROM tests
            WHERE id = ?
            """,
            (test_id,)
        ).fetchone()

    if test is None:
        raise HTTPException(
            status_code=404,
            detail="Test not found"
        )

    return {
        "test_id": test_id,
        "product_name": test[0],
        "task": test[1],
        "product_url": test[2],
        "created_at": test[3]
    }

class ParticipantResponseCreate(BaseModel):
    outcome: Literal["completed", "stuck", "gave_up"]
    comment: str | None = Field(default=None, max_length=500)


@app.post("/api/tests/{test_id}/responses", status_code=201)
def create_participant_response(
    test_id: str,
    data: ParticipantResponseCreate
):
    response_id = secrets.token_urlsafe(12)
    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DATABASE) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        test = connection.execute(
            "SELECT id FROM tests WHERE id = ?",
            (test_id,)
        ).fetchone()

        if test is None:
            raise HTTPException(
                status_code=404,
                detail="Test not found"
            )

        connection.execute(
            """
            INSERT INTO responses (
                id,
                test_id,
                outcome,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                response_id,
                test_id,
                data.outcome,
                data.comment,
                created_at
            )
        )

    return {
        "response_id": response_id,
        "test_id": test_id,
        "message": "Feedback submitted successfully"
    }

@app.get("/api/tests/{test_id}/responses")
def get_participant_responses(
    test_id: str,
    x_owner_token: str | None = Header(
        default=None,
        alias="X-Owner-Token"
    )
):
    if not x_owner_token:
        raise HTTPException(
            status_code=401,
            detail="Owner token required"
        )

    token_hash = hashlib.sha256(
        x_owner_token.encode("utf-8")
    ).hexdigest()

    with sqlite3.connect(DATABASE) as connection:
        owner = connection.execute(
            """
            SELECT owner_token_hash
            FROM tests
            WHERE id = ?
            """,
            (test_id,)
        ).fetchone()

        if owner is None:
            raise HTTPException(
                status_code=404,
                detail="Test not found"
            )

        if not secrets.compare_digest(
            owner[0],
            token_hash
        ):
            raise HTTPException(
                status_code=403,
                detail="Invalid owner token"
            )

        rows = connection.execute(
            """
            SELECT id, outcome, comment, created_at
            FROM responses
            WHERE test_id = ?
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (test_id,)
        ).fetchall()

    responses = [
        {
            "response_id": row[0],
            "outcome": row[1],
            "comment": row[2],
            "created_at": row[3]
        }
        for row in rows
    ]

    return {
        "test_id": test_id,
        "responses": responses
    }

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(
        Path(__file__).parent / "index.html"
    )

@app.get("/test/{test_id}", include_in_schema=False)
def participant_page(test_id: str):
    return FileResponse(
        Path(__file__).parent / "tester.html"
    )


@app.get("/dashboard/{test_id}", include_in_schema=False)
def owner_dashboard(test_id: str):
    return FileResponse(
        Path(__file__).parent / "dashboard.html"
    )
