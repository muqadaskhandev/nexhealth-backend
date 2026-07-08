# NexHealth Backend

Python **FastAPI** backend providing authentication, user management, and secure
session handling for the NexHealth React app.

- **Framework:** FastAPI (async) + SQLAlchemy 2.0 + Alembic
- **Database:** plain PostgreSQL — local Postgres in development, **AWS RDS
  (Postgres) in production**. No vendor lock-in; the same schema/migrations run
  on both.
- **Auth:** email + password (Argon2id), plus config-driven OAuth2/OIDC SSO for
  **Google, Azure (Microsoft), and Okta**.
- **Sessions:** short-lived access JWT + rotating refresh token, both in
  **httpOnly, Secure cookies**, with server-side revocation and CSRF protection.

---

## Why these security choices

| Concern | Approach |
|---|---|
| Password storage | Argon2id (memory-hard); opportunistic rehash on login |
| Token theft via XSS | Access + refresh tokens live in **httpOnly** cookies — unreadable by JS |
| CSRF | Double-submit: a non-httpOnly `csrf_token` cookie must be echoed in the `X-CSRF-Token` header on unsafe methods |
| Refresh-token replay | Rotation on every refresh; reuse of a revoked token revokes the **whole family** (theft detection) |
| Immediate logout | Every request checks the session (`sid`) is still live, so logout / password-change / deactivation take effect at once |
| Brute force | Per-account lockout after 5 failures + per-IP rate limits on auth routes |
| Account enumeration | Uniform errors on login; `forgot-password` always returns success |
| At-rest token leak | Only SHA-256 **hashes** of refresh/reset tokens are stored |
| OAuth | Authorization-code + **PKCE**, `state` (CSRF), `nonce`, and full id_token signature/issuer/audience verification |
| Transport | `Secure` cookies + HSTS in production; strict security headers |

Production config is validated at startup (`validate_for_production`) — the app
refuses to boot with a weak `JWT_SECRET` or non-Secure cookies.

---

## Quick start (Docker — recommended)

```bash
cd backend
cp .env.example .env          # fill in secrets; generate JWT_SECRET (below)
docker-compose up --build     # starts Postgres + API, runs migrations + seed
```

API is then at http://localhost:8000 (docs at `/docs`).

Generate a strong secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Quick start (local, no Docker)

Requires a running PostgreSQL and Python 3.11+.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # point DATABASE_URL at your Postgres

alembic upgrade head          # create schema
python -m seed                # locations + demo users
uvicorn app.main:app --reload # http://localhost:8000
```

### Seeded demo accounts
| Email | Password | Role | Locations |
|---|---|---|---|
| `admin@betterdental.com` | `ChangeMe123!` | admin | all 5 |
| `dr.riviera@betterdental.com` | `Demo1234!` | member | Brooklyn, Sausalito |

(Change these before any real deployment.)

---

## Running with the frontend

The Vite dev server proxies `/api` and `/health` to `http://localhost:8000`
(see `frontend/vite.config.ts`), so the browser sees a single origin and auth
cookies stay first-party. From the `frontend/` directory:

```bash
cd frontend
npm install        # first time only
npm run dev        # React app on http://localhost:5173
```

Log in with a seeded account, or configure SSO (below).

---

## API surface

### Auth (`/api/auth`)
| Method | Path | Notes |
|---|---|---|
| GET  | `/providers` | Which SSO buttons to show |
| POST | `/login` | email + password → sets session cookies |
| POST | `/refresh` | rotates the refresh token |
| POST | `/logout` | revokes the session, clears cookies |
| GET  | `/me` | current user + locations + active location |
| POST | `/forgot-password` | emails a reset link (logged in dev) |
| POST | `/reset-password` | consume token, set new password |
| POST | `/change-password` | authenticated password change |

### SSO (`/api/auth/sso`)
| Method | Path |
|---|---|
| GET | `/{provider}/login` (google \| azure \| okta) |
| GET | `/{provider}/callback` |

### Locations (`/api/locations`)
| Method | Path | Notes |
|---|---|---|
| GET  | `` | locations the user may access |
| POST | `/switch` | switch active location (membership-enforced) |

### Users — admin only (`/api/users`)
| Method | Path |
|---|---|
| GET | `` (list) |
| POST | `` (invite/create) |
| PATCH | `/{id}` (role, status, locations) |
| POST | `/{id}/send-reset` |

---

## SSO setup

For each provider, register this redirect URI:

```
{BACKEND_URL}/api/auth/sso/{provider}/callback
# dev: http://localhost:8000/api/auth/sso/google/callback
```

Then set the client id/secret in `.env`:

- **Google** — `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- **Azure** — `AZURE_TENANT_ID` (or `common`), `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
- **Okta** — `OKTA_DOMAIN` (e.g. `https://dev-123.okta.com`), `OKTA_CLIENT_ID`, `OKTA_CLIENT_SECRET`

A provider with no credentials is simply hidden from the login page.

New SSO users are provisioned as `member` with no locations until an admin
assigns them (tighten `sso_callback` in `app/routers/sso.py` to deny-unknown if
you require pre-provisioning).

---

## Production (AWS RDS) notes

1. `DATABASE_URL=postgresql+asyncpg://USER:PASS@your-rds-endpoint:5432/nexhealth`
   (use TLS to RDS).
2. `ENVIRONMENT=production`, `COOKIE_SECURE=true`, strong `JWT_SECRET`.
3. If the SPA and API are on different subdomains, set `COOKIE_DOMAIN=.your.com`
   and `COOKIE_SAMESITE=none`, and list the SPA origin in `CORS_ORIGINS`.
4. Run `alembic upgrade head` on deploy. Don't run `seed.py` in production.
5. Wire `_deliver_reset_email` (in `app/routers/auth.py`) to SES/SendGrid.

## Project layout

```
backend/
  app/
    config.py            # env-driven settings + prod validation
    database.py          # async engine + session
    core/                # security (Argon2/JWT), cookies, deps (authN/authZ/CSRF)
    models/              # User, Location, UserLocation, RefreshToken, ResetToken
    schemas/             # Pydantic request/response models
    services/            # auth_service, user_service, oauth (OIDC)
    routers/             # auth, sso, locations, users
    main.py              # app wiring, CORS, security headers, rate limiter
  alembic/               # migrations (0001_initial)
  seed.py                # demo locations + users
  docker-compose.yml     # local Postgres + API
```
