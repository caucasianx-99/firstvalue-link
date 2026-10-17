
import hashlib
import secrets
import sqlite3

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).parent
DATABASE = BASE_DIR / "firstvalue.db"

limiter = Limiter(
    key_func=get_remote_address
)


# ==========================================
# DATABASE INITIALIZATION
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    with sqlite3.connect(DATABASE) as connection:

        connection.execute("PRAGMA foreign_keys = ON")

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


# ==========================================
# FASTAPI APPLICATION
# ==========================================

app = FastAPI(
    title="FirstValue Link",
    description="Simple beta testing and feedback platform",
    version="0.4.0",
    lifespan=lifespan
)

app.state.limiter = limiter

app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler
)


# ==========================================
# REQUEST MODELS
# ==========================================

class TestCreate(BaseModel):

    product_name: str = Field(
        min_length=2,
        max_length=100
    )

    task: str = Field(
        min_length=10,
        max_length=300
    )

    product_url: HttpUrl


class ParticipantResponseCreate(BaseModel):

    outcome: Literal[
        "completed",
        "stuck",
        "gave_up"
    ]

    comment: str | None = Field(
        default=None,
        max_length=500
    )


# ==========================================
# HEALTH CHECK
# ==========================================

@app.get("/health")
def health_check():

    return {
        "status": "ok",
        "app": "FirstValue Link"
    }


# ==========================================
# CREATE TEST
# ==========================================

@app.post("/api/tests", status_code=201)
@limiter.limit("5/minute")
def create_test(
    request: Request,
    response: Response,
    data: TestCreate
):

    test_id = secrets.token_urlsafe(12)
    owner_token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(
        owner_token.encode("utf-8")
    ).hexdigest()

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

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

    # Prevent caching of the returned owner token.
    response.headers["Cache-Control"] = "no-store"

    return {
        "test_id": test_id,
        "owner_token": owner_token,
        "message": "Test created successfully"
    }


# ==========================================
# GET TEST INFORMATION
# ==========================================

@app.get("/api/tests/{test_id}")
def get_test(test_id: str):

    with sqlite3.connect(DATABASE) as connection:

        test = connection.execute(
            """
            SELECT
                product_name,
                task,
                product_url,
                created_at
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


# ==========================================
# SUBMIT PARTICIPANT FEEDBACK
# ==========================================

@app.post(
    "/api/tests/{test_id}/responses",
    status_code=201
)
@limiter.limit("15/minute")
def create_participant_response(
    test_id: str,
    request: Request,
    data: ParticipantResponseCreate
):

    response_id = secrets.token_urlsafe(12)

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

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


# ==========================================
# GET PRIVATE PARTICIPANT RESPONSES
# ==========================================

@app.get("/api/tests/{test_id}/responses")
@limiter.limit("10/minute")
def get_participant_responses(
    test_id: str,
    request: Request,
    response: Response,
    x_owner_token: str | None = Header(
        default=None,
        alias="X-Owner-Token"
    )
):

    # Owner token must be provided.
    if not x_owner_token:

        raise HTTPException(
            status_code=401,
            detail="Owner token required"
        )

    # Convert the submitted token to its SHA-256 hash.
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

        # Constant-time comparison of token hashes.
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
            SELECT
                id,
                outcome,
                comment,
                created_at
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

    # Private feedback must not be cached.
    response.headers["Cache-Control"] = "no-store"

    return {
        "test_id": test_id,
        "responses": responses
    }


# ==========================================
# HOME PAGE
# ==========================================

@app.get("/", include_in_schema=False)
def home():

    return FileResponse(
        BASE_DIR / "index.html"
    )


# ==========================================
# PARTICIPANT PAGE
# ==========================================

@app.get(
    "/test/{test_id}",
    include_in_schema=False
)
def participant_page(test_id: str):

    return FileResponse(
        BASE_DIR / "tester.html"
    )


# ==========================================
# FOUNDER DASHBOARD
# ==========================================

@app.get(
    "/dashboard/{test_id}",
    include_in_schema=False
)
def owner_dashboard(test_id: str):

    return FileResponse(
        BASE_DIR / "dashboard.html"
    )
