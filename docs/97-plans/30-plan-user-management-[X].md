# Plan 30 — User Management & Authentication

| Field | Value |
|-------|-------|
| **Status** | Complete |
| **Created** | 2026-03-21 |
| **Depends on** | Plan 28 (Mission Control Platform), Plan 29 (Frontend Design) |
| **Blocked by** | Nothing — P3 (Breaking Changes Are Free) applies |
| **Target** | models, schemas, services, repositories, API, CLI, config, dependencies, migrations |

---

## 1  Objective

Introduce persistent **User** and **API Key** models so Mission Control has proper identity, authentication, and authorization. Today the platform has a single shared `ADMIN_API_KEY` — if your key matches you're admin, otherwise you're an anonymous viewer. There is no User table, no login endpoint, no per-user API keys, and `MissionMember.user_id` is a bare string with no FK.

This plan delivers:

1. **User model** — persistent users stored in PostgreSQL
2. **API Key model** — per-user, named, revocable API keys with optional expiry
3. **Dual authentication** — JWT tokens for web sessions (frontend), API keys for programmatic access (CLI, integrations, service-to-service)
4. **System-level roles** — viewer, user, admin (replacing the BFA-era "trader" role)
5. **`get_current_user` dependency** — the central FastAPI dependency that resolves any auth method to a `User` object
6. **Auth API endpoints** — login, token refresh, API key management, password change
7. **Admin user management** — CRUD users, reset passwords, manage keys
8. **MissionMember FK** — wire `mission_members.user_id` as a foreign key to `users.id`
9. **Bootstrap CLI** — seed the first admin user from the command line

**Dev mode: breaking changes allowed.** P3 applies. The existing `AdminRole` type changes from `str` to `User`. No backward-compatibility shims.

---

## 2  Design Decisions

### D1: Admin-only user creation (no self-service signup)

**Decision**: Admins create users via the admin API or CLI. No public registration endpoint.

**Rationale**: Mission Control is a platform for a small operations team, not a SaaS product. Self-service signup would require email verification, abuse prevention, and onboarding flows that add complexity without value for the current use case. A feature flag `auth_allow_self_registration` is added (default `false`) for future enablement.

### D2: Both JWT and API key authentication

**Decision**: The `get_current_user` dependency accepts both `Authorization: Bearer <jwt>` and `X-API-Key` headers. JWT is for web sessions (frontend login). API keys are for programmatic access (CLI, integrations).

**Rationale**: Different clients have different needs. The frontend needs short-lived, refreshable tokens. The CLI and background services need long-lived, revocable keys. The auth spec (doc 05) explicitly describes both methods. Both resolve to the same `User` model object, so downstream code doesn't care which method was used.

### D3: Separate `api_keys` table (not inline on User)

**Decision**: API keys are stored in their own table with a FK to `users`. Users can have multiple named keys.

**Rationale**: Users need multiple keys for different contexts (CLI key, CI/CD key, personal key). Keys need independent lifecycle management (create, revoke, expire) and audit metadata (last used, created at). Inline storage on the User model would limit to one key and conflate user lifecycle with key lifecycle.

### D4: Prefix-narrowed API key lookup

**Decision**: Store the first 8 characters of the raw key as `key_prefix` (plaintext, indexed). When resolving an API key, query by prefix first, then bcrypt-verify only the matching candidates.

**Rationale**: Bcrypt verification is intentionally slow (~100ms per comparison). With N users having M keys, brute-force comparing every stored hash is O(N*M * 100ms). Prefix narrowing reduces this to O(1-2 * 100ms) — only the keys whose prefix matches are bcrypt-checked. The prefix is not secret (it's part of the key shown to the user at creation time).

### D5: AdminRole type change from `str` to `User`

**Decision**: The `AdminRole` annotated dependency changes from returning a role name string to returning a `User` object.

**Rationale**: All 15 existing admin endpoints use `_role: AdminRole` as a throwaway parameter — the underscore prefix means the value is unused. Changing the type from `str` to `User` is safe with zero endpoint modifications. Admin endpoints that want the user identity (e.g., audit logging) can now access it.

### D6: Legacy ADMIN_API_KEY fallback (via AuthService)

**Decision**: Legacy key resolution is encapsulated in `AuthService.resolve_legacy_key()` — not inline in the `get_current_user` dependency. The comparison uses `hmac.compare_digest()` (constant-time) instead of `==` to prevent timing attacks.

**Rationale**: Existing automation and CLI scripts use the shared admin key. This fallback ensures they continue working during the migration period. Once personal keys are issued, `ADMIN_API_KEY` can be removed from `.env`. Keeping the logic in `AuthService` (not the dependency) maintains the pattern that dependencies delegate to services.

### D7: Rename "trader" role to "user"

**Decision**: The `security.yaml` role hierarchy changes from `viewer(1) → trader(2) → admin(3)` to `viewer(1) → user(2) → admin(3)`.

**Rationale**: "trader" is a leftover from the BFA trading platform fork. Mission Control has no concept of trading. "user" is the correct name for standard platform access.

### D8: Authorization enforcement at the service layer

**Decision**: API endpoints extract the current user via `get_current_user` dependency and pass it to service methods as `requesting_user`. Service methods enforce authorization rules.

**Rationale**: This follows the architecture standard defined in doc 05-core-authentication.md. Authorization at the service layer ensures rules are enforced regardless of how the service is called — HTTP endpoint, background task, CLI, or internal API.

---

## 3  Database Models

### 3.1  `users` table

**File**: `modules/backend/models/user.py`

```
Table: users

| Column          | Type                             | Constraints                          |
|-----------------|----------------------------------|--------------------------------------|
| id              | String(36)                       | PK (UUIDMixin)                       |
| email           | String(200)                      | UNIQUE, NOT NULL, INDEXED            |
| display_name    | String(200)                      | NOT NULL                             |
| hashed_password | String(200)                      | NULLABLE (null = API-key-only user)  |
| system_role     | Enum(viewer/user/admin)          | NOT NULL, DEFAULT 'user', INDEXED    |
| is_active       | Boolean                          | NOT NULL, DEFAULT true               |
| is_service_account | Boolean                       | NOT NULL, DEFAULT false              |
| last_login_at   | DateTime                         | NULLABLE                             |
| created_at      | DateTime                         | NOT NULL (TimestampMixin)            |
| updated_at      | DateTime                         | NOT NULL (TimestampMixin)            |
```

**Enum**: `SystemRole(str, enum.Enum)` with values `VIEWER = "viewer"`, `USER = "user"`, `ADMIN = "admin"`. The `system_role` column stores the **string value** (not the enum member). The enum is used for type-safe comparisons in Python code. SQLAlchemy column: `mapped_column(String(20), default=SystemRole.USER.value)`.

**Helper method**: `has_role(minimum: str) -> bool` — reads role levels from `security.yaml` config via `get_app_config().security.roles` (do NOT hardcode a static level map). Returns `True` if the user's role level >= the minimum role level. If `minimum` is not a recognized role name, raise `ValueError(f"Unknown role: {minimum}")` — this is a programming error, not a user error. This ensures the model stays in sync if roles are added or reordered in config.

**Relationship**: `api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")` — one-to-many with cascade delete.

**Model pattern**: Extends `UUIDMixin, TimestampMixin, Base` (same as all existing models — see `models/mission.py` for reference).

### 3.2  `api_keys` table

**File**: `modules/backend/models/api_key.py`

```
Table: api_keys

| Column       | Type        | Constraints                                      |
|--------------|-------------|--------------------------------------------------|
| id           | String(36)  | PK (UUIDMixin)                                   |
| user_id      | String(36)  | FK → users.id ON DELETE CASCADE, NOT NULL, INDEXED |
| name         | String(100) | NOT NULL                                         |
| key_prefix   | String(8)   | NOT NULL, INDEXED                                |
| hashed_key   | String(200) | NOT NULL                                         |
| expires_at   | DateTime    | NULLABLE (null = no expiry)                      |
| revoked_at   | DateTime    | NULLABLE (null = not revoked)                    |
| scopes       | JSON        | NULLABLE (null = all scopes)                     |
| last_used_at | DateTime    | NULLABLE                                         |
| created_at   | DateTime    | NOT NULL (TimestampMixin)                        |
| updated_at   | DateTime    | NOT NULL (TimestampMixin)                        |

UniqueConstraint: (user_id, name) — name="uq_api_keys_user_name"
```

**`scopes`** is nullable JSON — when `null`, the key inherits all permissions of the user's role. When set, it's a list of scope strings (e.g., `["read:missions", "write:missions"]`). Scope enforcement is not implemented in this plan — the column is always `NULL` for now. No API endpoint should accept scope parameters yet. Adding the column now is cheap and avoids a future migration.

**Property**: `is_active -> bool` — returns `True` if `revoked_at is None` and (`expires_at is None` or `expires_at > utc_now()`).

**Relationship**: `user: Mapped["User"] = relationship("User", back_populates="api_keys")` — many-to-one back to User.

### 3.3  `models/__init__.py` update

Add imports and `__all__` entries for `User`, `SystemRole`, and `ApiKey`.

---

## 4  Migration

### 4.1  Alembic migration file

**File**: `modules/backend/migrations/versions/20260321_phase3_users_and_api_keys.py`

**Revision**: `phase3_001`, revises `phase2_002`.

**Upgrade operations** (in order):

1. Create `users` table with all columns, indexes on `email` and `system_role`.
2. Create `api_keys` table with FK to `users.id`, indexes on `user_id` and `key_prefix`, unique constraint on `(user_id, name)`.
3. **Data migration** (critical — must happen before FK constraint):
   - For each distinct `user_id` value in `mission_members` that does not already exist in `users`, insert a placeholder user row:
     - `id`: generate UUID
     - `email`: `{user_id}@placeholder.local`
     - `display_name`: the `user_id` value
     - `system_role`: `"user"`
     - `is_active`: `True`
     - `is_service_account`: `False`
     - `hashed_password`: `NULL`
     - `created_at`, `updated_at`: current UTC time
   - **Also check `missions.owner_id`**: for each distinct `owner_id` in `missions` not in `users`, insert the same placeholder row.
   - **Skip invalid rows**: If any `mission_members.user_id` is empty, null, or whitespace-only, log a warning and delete those rows (they are orphaned data). Fail the migration loudly if any are found rather than creating invalid placeholder users.
   - **UPDATE `mission_members.user_id`** to point to the new placeholder user UUIDs (the existing values are bare strings like `"herman"`, but the FK requires them to match a `users.id` UUID). Use a subquery: `UPDATE mission_members SET user_id = (SELECT id FROM users WHERE display_name = mission_members.user_id) WHERE EXISTS (SELECT 1 FROM users WHERE display_name = mission_members.user_id)`. The `WHERE EXISTS` guard prevents nulling out rows that don't have a matching placeholder.
   - **UPDATE `missions.owner_id`** similarly if needed.
4. Alter `mission_members.user_id`: change column type to `String(36)` if needed, add FK constraint `fk_mission_members_user_id` referencing `users.id` with `ON DELETE RESTRICT` (not CASCADE — deleting a user should not silently remove mission membership records; deactivation is the preferred path).

**Downgrade operations** (reverse order):

1. Drop FK constraint `fk_mission_members_user_id` from `mission_members`.
2. Drop `api_keys` table.
3. Drop `users` table.

### 4.2  Migration `env.py` update

**File**: `modules/backend/migrations/env.py`

Add import lines after the existing model imports:

```python
from modules.backend.models.user import User  # noqa: F401
from modules.backend.models.api_key import ApiKey  # noqa: F401
```

---

## 5  Configuration Changes

### 5.1  `config/settings/security.yaml`

Three changes:

1. **Rename `trader` role to `user`**:
```yaml
roles:
  viewer:
    level: 1
    description: "Read-only access"
  user:
    level: 2
    description: "Standard access to own resources"
  admin:
    level: 3
    description: "Full system access"
```

2. **Add `X-API-Key` to CORS allowed headers** (`Authorization` is already present):
```yaml
cors:
  allow_headers:
    - "Authorization"    # already exists
    - "Content-Type"
    - "X-Request-ID"
    - "X-Frontend-ID"
    - "X-API-Key"        # ADD THIS
```

3. **Update JWT audience** from BFA-era value:
```yaml
jwt:
  audience: "mission-control-api"
```

### 5.2  `config/settings/features.yaml`

Add under the `# Authentication` section:

```yaml
auth_allow_self_registration: false
```

### 5.3  `modules/backend/core/config_schema.py`

The `SecuritySchema.roles` field is `dict[str, RoleSchema] = Field(default_factory=dict)` — role definitions come from `security.yaml`, not from schema defaults, so no schema change is needed for the trader→user rename. Update `FeaturesSchema` to include `auth_allow_self_registration: bool = False`.

### 5.4  Config files that reference "trader"

Search for `trader` in all config and test files. Update any test assertions that check for the "trader" role to check for "user" instead.

### 5.5  JWT audience change impact

Changing `audience: "bff-api"` to `audience: "mission-control-api"` (already specified in §5.1 step 3) will invalidate all existing JWT tokens. This is expected — users must re-authenticate after deployment. Since we have no existing JWT users (only `ADMIN_API_KEY`), this is a no-op in practice.

---

## 6  Repository Layer

### 6.1  `UserRepository`

**File**: `modules/backend/repositories/user.py`

Extends `BaseRepository[User]` (see `repositories/base.py` for pattern).

Set `model = User`.

**Additional methods** (beyond inherited CRUD):

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_by_email` | `(email: str) -> User \| None` | `select(User).where(User.email == email)`, return `scalar_one_or_none()` |
| `get_active` | `(user_id: str) -> User \| None` | Filter by `id == user_id` AND `is_active == True` |
| `list_all` | `(limit: int, offset: int, role_filter: str \| None) -> list[User]` | Optional filter by `system_role == role_filter`. Order by `created_at DESC`. |
| `update_last_login` | `(user_id: str) -> None` | Set `last_login_at = utc_now()`, flush. |

### 6.2  `ApiKeyRepository`

**File**: `modules/backend/repositories/api_key.py`

Extends `BaseRepository[ApiKey]`.

Set `model = ApiKey`.

**Additional methods**:

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_by_prefix` | `(prefix: str) -> list[ApiKey]` | Select where `key_prefix == prefix` AND `revoked_at IS NULL` AND (`expires_at IS NULL` OR `expires_at > utc_now()`). Eagerly load `.user` relationship. Filtering for active keys here (not in the service) is intentional — reduces the number of bcrypt comparisons by excluding keys that can never match. |
| `list_by_user` | `(user_id: str) -> list[ApiKey]` | Select where `user_id == user_id`, order by `created_at DESC`. Include revoked keys (for display). |
| `revoke` | `(key_id: str) -> ApiKey` | Set `revoked_at = utc_now()`, flush, refresh, return. Raise `NotFoundError` if not found. |
| `revoke_all_by_user` | `(user_id: str) -> int` | Set `revoked_at = utc_now()` on all active keys for this user. Return count of revoked keys. Used by `UserService.deactivate_user()`. |
| `update_last_used` | `(key_id: str) -> None` | Set `last_used_at = utc_now()`, flush. |

---

## 7  Schema Layer

### 7.1  User schemas

**File**: `modules/backend/schemas/user.py`

```python
class UserCreate(BaseModel):
    """Schema for creating a user (admin endpoint)."""
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(..., max_length=200)   # from pydantic import EmailStr
    display_name: str = Field(..., min_length=1, max_length=200)
    password: str | None = Field(None, min_length=12)  # null = API-key-only user
    system_role: str = Field(default="user", pattern=r"^(viewer|user|admin)$")
    is_service_account: bool = False


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(None, min_length=1, max_length=200)
    system_role: str | None = Field(None, pattern=r"^(viewer|user|admin)$")
    is_active: bool | None = None


class UserResponse(BaseModel):
    """Schema for user API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    system_role: str
    is_active: bool
    is_service_account: bool
    last_login_at: str | None
    created_at: str
    updated_at: str


class UserBriefResponse(BaseModel):
    """Minimal user info for embedding in other responses."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    system_role: str
    is_service_account: bool
```

### 7.2  Auth schemas

**File**: `modules/backend/schemas/auth.py`

```python
class LoginRequest(BaseModel):
    """Email/password login."""
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """JWT token pair with user info."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenRefreshRequest(BaseModel):
    """Refresh token exchange."""
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class TokenRefreshResponse(BaseModel):
    """New JWT token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ApiKeyCreateRequest(BaseModel):
    """Create a new API key."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: int | None = Field(None, ge=1, le=365)


class ApiKeyCreateResponse(BaseModel):
    """API key creation result. The `key` field is shown ONCE."""
    id: str
    name: str
    key: str              # Full key — shown only at creation time
    key_prefix: str
    expires_at: str | None
    created_at: str


class ApiKeyResponse(BaseModel):
    """API key info (without the full key)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    expires_at: str | None
    revoked_at: str | None
    last_used_at: str | None
    created_at: str


class ChangePasswordRequest(BaseModel):
    """Change own password."""
    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12)


class ResetPasswordRequest(BaseModel):
    """Admin reset of another user's password."""
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(..., min_length=12)
```

---

## 8  Service Layer

### 8.1  `AuthService`

**File**: `modules/backend/services/auth.py`

Extends `BaseService`. Constructor initializes `UserRepository` and `ApiKeyRepository`.

| Method | Signature | Behaviour |
|--------|-----------|-----------|
| `login` | `(email: str, password: str) -> dict` | 1. Load user by email via `UserRepository.get_by_email()`. 2. If not found or `is_active == False`, raise `AuthenticationError("Invalid credentials")`. 3. If `hashed_password` is null, raise `AuthenticationError("Password login not configured")`. 4. Verify password via `security.verify_password()`. If mismatch, raise `AuthenticationError("Invalid credentials")`. 5. Create JWT tokens via `security.create_access_token({"sub": user.id, "role": user.system_role})` and `security.create_refresh_token({"sub": user.id})`. 6. Update `last_login_at` via repo. 7. Return `{"access_token": ..., "refresh_token": ..., "user": user}`. |
| `refresh_token` | `(refresh_token_str: str) -> dict` | 1. Decode token via `security.decode_token()`. 2. Verify `payload["type"] == "refresh"`. If not, raise `AuthenticationError`. 3. Load user by `payload["sub"]`. If not found or inactive, raise `AuthenticationError`. 4. Issue new token pair. 5. Return `{"access_token": ..., "refresh_token": ...}`. |
| `resolve_api_key` | `(raw_key: str) -> User` | 1. Extract prefix: `raw_key[:8]`. 2. Query `ApiKeyRepository.get_by_prefix(prefix)`. 3. For each candidate, call `security.verify_api_key(raw_key, candidate.hashed_key)`. 4. If match found: update `last_used_at`, load and return `candidate.user` (eagerly loaded or separate query). 5. If no match, raise `AuthenticationError("Invalid API key")`. 6. If matched but user `is_active == False`, raise `AuthenticationError("Account deactivated")`. |
| `resolve_jwt` | `(token: str) -> User` | 1. Decode via `security.decode_token()`. 2. Verify `payload["type"] == "access"`. 3. Load user by `payload["sub"]` via `UserRepository.get_active()`. 4. If not found or inactive, raise `AuthenticationError`. 5. Return user. |
| `create_api_key` | `(user_id: str, name: str, expires_in_days: int \| None, requesting_user: User) -> tuple[str, ApiKey]` | 1. Authorization: `requesting_user.id == user_id` or `requesting_user.has_role("admin")`. Else raise `AuthorizationError`. 2. Generate key via `security.generate_api_key()` → `(full_key, hashed_key)`. 3. Extract prefix: `full_key[:8]`. 4. Calculate `expires_at` from `expires_in_days` if provided. 5. Create `ApiKey` via repo. 6. Return `(full_key, api_key_record)`. |
| `list_api_keys` | `(user_id: str, requesting_user: User) -> list[ApiKey]` | Authorization: self or admin. Return `ApiKeyRepository.list_by_user(user_id)`. |
| `revoke_api_key` | `(key_id: str, requesting_user: User) -> ApiKey` | 1. Load key by ID. 2. Authorization: `key.user_id == requesting_user.id` or admin. 3. `ApiKeyRepository.revoke(key_id)`. |
| `resolve_legacy_key` | `(raw_key: str) -> User \| None` | 1. Load `ADMIN_API_KEY` from settings. 2. If not configured, return `None`. 3. Compare using `hmac.compare_digest()` (constant-time, NOT `==`). 4. If match, load first active admin user from DB. 5. Return user or `None`. |

**Important implementation notes for AuthService**:

- **Required imports**: `import asyncio`, `import hmac`, `from datetime import timedelta`, `from uuid import uuid4`. These are all stdlib — no new dependencies.
- **Bcrypt blocks the event loop**: All bcrypt operations (`verify_password`, `verify_api_key`, `hash_password`) are CPU-bound and take ~100ms. Wrap each call in `await asyncio.to_thread(security.verify_password, ...)` to avoid blocking the async event loop. This applies in `login()`, `resolve_api_key()`, `create_api_key()`, and `create_user()` (in UserService).
- **JWT `jti` claim**: Include a UUID `jti` (JWT ID) claim in all issued tokens via `create_access_token({"sub": user.id, "role": user.system_role, "jti": str(uuid4())})`. Not enforced in this plan (no token blacklist) but enables future token revocation without a schema migration.
- **`resolve_legacy_key` when no admin exists**: If `ADMIN_API_KEY` matches but no admin user exists in the DB (bootstrap not yet run), return `None` — the dependency will raise a generic `AuthenticationError("Authentication required")`. This is intentional: the key is valid but the system is not yet bootstrapped.
- **Audit logging**: Use `self._log_operation()` (inherited from `BaseService`) for login attempts, token refreshes, and key create/revoke events.

### 8.2  `UserService`

**File**: `modules/backend/services/user.py`

Extends `BaseService`. Constructor initializes `UserRepository` and `ApiKeyRepository` (needed for `deactivate_user` to revoke keys).

| Method | Signature | Behaviour |
|--------|-----------|-----------|
| `create_user` | `(email: str, display_name: str, password: str \| None, system_role: str, is_service_account: bool, requesting_user: User) -> User` | 1. Authorization: `requesting_user.has_role("admin")`. Else raise `AuthorizationError`. 2. Check `UserRepository.get_by_email(email)` — if result is not `None`, raise `ConflictError("Email already registered")`. 3. Hash password if provided via `await asyncio.to_thread(security.hash_password, password)`. 4. Create via repo. Return user. |
| `get_user` | `(user_id: str, requesting_user: User) -> User` | Self (`requesting_user.id == user_id`) or admin. Else raise `AuthorizationError`. Load via `UserRepository.get_by_id()`. |
| `list_users` | `(requesting_user: User, limit: int, offset: int) -> list[User]` | Admin only. `UserRepository.list_all(limit, offset)`. |
| `update_user` | `(user_id: str, requesting_user: User, display_name: str \| None, system_role: str \| None, is_active: bool \| None) -> User` | Admin can update any field. Non-admin can only update own `display_name`. If non-admin tries to change `system_role` or `is_active`, raise `AuthorizationError`. Update via `UserRepository.update()`. |
| `deactivate_user` | `(user_id: str, requesting_user: User) -> User` | Admin only. Cannot deactivate self (raise `ValidationError("Cannot deactivate own account")`). Set `is_active = False`. **Also revoke all of the user's active API keys** via `ApiKeyRepository.revoke_all_by_user(user_id)` — a deactivated user should have no valid credentials. |
| `change_password` | `(user_id: str, old_password: str, new_password: str, requesting_user: User) -> None` | Self only (`requesting_user.id == user_id`). Verify old password. Hash new password. Update `hashed_password`. |
| `admin_reset_password` | `(user_id: str, new_password: str, requesting_user: User) -> None` | Admin only. Hash new password. Update `hashed_password`. |

### 8.3  `BootstrapService`

**File**: `modules/backend/services/bootstrap.py`

Takes `AsyncSession` in `__init__` (consistent with `BaseService` pattern, which also receives session at construction time). Does NOT extend `BaseService` since it runs from CLI outside the FastAPI lifecycle, but follows the same constructor convention.

Constructor: `__init__(self, session: AsyncSession)` — stores session, initializes `UserRepository(session)` and `ApiKeyRepository(session)`.

| Method | Signature | Behaviour |
|--------|-----------|-----------|
| `bootstrap_admin` | `(email: str, display_name: str, password: str) -> tuple[User, str]` | 1. Check if any user with `system_role == "admin"` exists. If yes, raise `ConflictError("Admin user already exists. Use the admin API to create additional users.")`. 2. Create user with `system_role = "admin"`, `hashed_password = hash_password(password)`. 3. Generate API key via `security.generate_api_key()` → `(full_key, hashed_key)`. 4. Create `ApiKey` with `name = "bootstrap"`, `key_prefix = full_key[:8]`, `hashed_key`. 5. Flush (caller commits). 6. Return `(user, full_key)`. |

---

## 9  Dependency Injection

### 9.1  Changes to `modules/backend/core/dependencies.py`

This is the central pivot point. The file currently has `_resolve_role()`, `require_role()`, `require_admin()`, and `AdminRole`. All of these change.

**Add new functions and type aliases**:

```python
from modules.backend.models.user import User


async def get_current_user(
    db: DbSession,
    authorization: str | None = Header(None),
    api_key: str | None = Security(_api_key_header),
) -> User:
    """
    Resolve the current user from JWT or API key.

    Resolution order:
    1. Authorization: Bearer <jwt> → decode JWT → load user by 'sub' claim
    2. X-API-Key header → prefix lookup + bcrypt verify → load user
    3. X-API-Key matches legacy ADMIN_API_KEY → load first admin user from DB
    4. Else → raise AuthenticationError
    """
    from modules.backend.services.auth import AuthService

    auth_service = AuthService(db)

    # 1. Try JWT Bearer token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]  # Strip "Bearer " prefix
        return await auth_service.resolve_jwt(token)

    # 2. Try per-user API key
    if api_key:
        try:
            return await auth_service.resolve_api_key(api_key)
        except AuthenticationError:
            pass  # Fall through to legacy check

        # 3. Legacy ADMIN_API_KEY fallback (delegated to AuthService)
        user = await auth_service.resolve_legacy_key(api_key)
        if user:
            return user

    raise AuthenticationError("Authentication required")


async def get_optional_user(
    db: DbSession,
    authorization: str | None = Header(None),
    api_key: str | None = Security(_api_key_header),
) -> User | None:
    """Like get_current_user but returns None instead of raising."""
    try:
        return await get_current_user(db, authorization, api_key)
    except AuthenticationError:
        return None


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


async def require_admin(user: CurrentUser) -> User:
    """Require that the current user has admin role."""
    from modules.backend.core.exceptions import AuthorizationError
    if not user.has_role("admin"):
        raise AuthorizationError(
            f"Requires 'admin' role. Current role: '{user.system_role}'."
        )
    return user


AdminRole = Annotated[User, Depends(require_admin)]
```

**Remove**: The old `_resolve_role()` function, the old `require_role()` factory, and the old `require_admin()` function. They are fully replaced.

**Keep**: `DbSession`, `RequestId`, `get_request_id`, `get_event_bus`, `_api_key_header` — these are unchanged.

### 9.2  Impact on existing admin endpoints

**File**: `modules/backend/api/v1/endpoints/admin.py`

All 15 endpoints use `_role: AdminRole` as a parameter. Since `AdminRole` changes from `Annotated[str, ...]` to `Annotated[User, ...]`, the variable type changes from `str` to `User`. Because all endpoints use the `_` prefix (throwaway — the value is never referenced in the function body), **no endpoint code changes are required**. The type annotation change is transparent.

However, if any admin endpoint wants to log _who_ performed the action, it can now use `_role.email` or `_role.id`. This is optional and can be added incrementally.

### 9.3  New imports needed

The `dependencies.py` file needs these new imports:

```python
from modules.backend.core.exceptions import AuthenticationError
from modules.backend.models.user import User
```

---

## 10  API Endpoints

### 10.1  Auth router (new file)

**File**: `modules/backend/api/v1/endpoints/auth.py`

**Router**: `router = APIRouter()`, mounted at `/api/v1/auth` in `api/v1/__init__.py`.

| Method | Path | Auth | Request Body | Response | Description |
|--------|------|------|-------------|----------|-------------|
| POST | `/auth/login` | None | `LoginRequest` | `ApiResponse[LoginResponse]` | Validate email/password, return JWT pair + user info. Calls `AuthService.login()`. |
| POST | `/auth/refresh` | None | `TokenRefreshRequest` | `ApiResponse[TokenRefreshResponse]` | Exchange refresh token for new pair. Calls `AuthService.refresh_token()`. |
| GET | `/auth/me` | `CurrentUser` | — | `ApiResponse[UserResponse]` | Return current user info. Serialize the `User` model from the dependency. |
| POST | `/auth/api-keys` | `CurrentUser` | `ApiKeyCreateRequest` | `ApiResponse[ApiKeyCreateResponse]` | Create API key for self. Calls `AuthService.create_api_key(user_id=current_user.id, ...)`. |
| GET | `/auth/api-keys` | `CurrentUser` | — | `ApiResponse[list[ApiKeyResponse]]` | List own API keys. Calls `AuthService.list_api_keys(user_id=current_user.id, ...)`. |
| DELETE | `/auth/api-keys/{key_id}` | `CurrentUser` | — | `ApiResponse` | Revoke own API key. Calls `AuthService.revoke_api_key()`. |
| POST | `/auth/change-password` | `CurrentUser` | `ChangePasswordRequest` | `ApiResponse` | Change own password. Calls `UserService.change_password()`. |

**Endpoint implementation pattern** (follow existing patterns in `admin.py`):

```python
@router.post("/login", response_model=ApiResponse, summary="Login with email and password")
async def login(
    body: LoginRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Authenticate with email/password, receive JWT token pair."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    result = await service.login(email=body.email, password=body.password)

    return ApiResponse(
        success=True,
        data=LoginResponse(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            user=UserResponse.model_validate(result["user"]),
        ).model_dump(),
        metadata={"request_id": request_id},
    )
```

### 10.2  Admin user management endpoints (new file — NOT added to admin.py)

**File**: `modules/backend/api/v1/endpoints/admin_users.py`

Create a **separate** file for user management endpoints to prevent `admin.py` from growing unbounded (it already has 550+ lines with catalog, metrics, config, and health endpoints). The router is mounted at `/admin/users` in `__init__.py`. All endpoints require `AdminRole`.

| Method | Path (relative to `/admin/users`) | Request Body | Response | Description |
|--------|------|-------------|----------|-------------|
| POST | `/` | `UserCreate` | `ApiResponse[UserResponse]` | Create a new user. Calls `UserService.create_user(requesting_user=_role)`. |
| GET | `/` | — (query: `limit`, `offset`) | `ApiResponse[list[UserResponse]]` | List all users. Calls `UserService.list_users()`. |
| GET | `/{user_id}` | — | `ApiResponse[UserResponse]` | Get user detail. Calls `UserService.get_user()`. |
| PATCH | `/{user_id}` | `UserUpdate` | `ApiResponse[UserResponse]` | Update user. Calls `UserService.update_user()`. |
| DELETE | `/{user_id}` | — | `ApiResponse` | Deactivate user (soft delete). Calls `UserService.deactivate_user()`. |
| POST | `/{user_id}/reset-password` | `ResetPasswordRequest` | `ApiResponse` | Admin reset password. Calls `UserService.admin_reset_password()`. |
| POST | `/{user_id}/api-keys` | `ApiKeyCreateRequest` | `ApiResponse[ApiKeyCreateResponse]` | Create API key for any user. Calls `AuthService.create_api_key()`. |
| GET | `/{user_id}/api-keys` | — | `ApiResponse[list[ApiKeyResponse]]` | List any user's API keys. Calls `AuthService.list_api_keys()`. |
| DELETE | `/{user_id}/api-keys/{key_id}` | — | `ApiResponse` | Revoke any user's API key. Calls `AuthService.revoke_api_key()`. |

### 10.3  Router registration

**File**: `modules/backend/api/v1/__init__.py`

Add:

```python
from modules.backend.api.v1.endpoints import auth, admin_users

# Auth endpoints (login, token refresh, API key management)
router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Admin user management endpoints
router.include_router(admin_users.router, prefix="/admin/users", tags=["admin"])
```

Place `auth` before the admin router registration (auth endpoints are public, admin are protected). The `admin_users` router sits alongside the existing `admin` router — both under `/admin` with the same tag.

**Remove** the `# ---- User / Role Management ----` section from `admin.py` (the existing `admin_list_roles` and `admin_list_user_roles` endpoints). Move them to `admin_users.py` as they logically belong with user management.

---

## 11  MissionMember FK Wiring

### 11.1  Model change

**File**: `modules/backend/models/mission.py`

Change `MissionMember.user_id` to add a FK constraint:

```python
# Before:
user_id: Mapped[str] = mapped_column(
    String(200), nullable=False, index=True,
)

# After:
user_id: Mapped[str] = mapped_column(
    String(36),
    ForeignKey("users.id", ondelete="RESTRICT"),
    nullable=False,
    index=True,
)
```

Add a relationship:

```python
user: Mapped["User"] = relationship("User")
```

Add import at top of file:

```python
from sqlalchemy import ForeignKey  # already imported — just ensure it's there
```

### 11.2  Mission.owner_id

`Mission.owner_id` remains a bare string for now (not FK'd). This is intentional — `owner_id` is a denormalized field used for quick filtering. The authoritative ownership is determined by `MissionMember` entries with `role == OWNER`. Adding a FK on `owner_id` is a separate concern that can be addressed in a future plan.

---

## 12  Bootstrap CLI Command

### 12.1  New CLI action

**File**: `modules/clients/cli/admin_cmds.py`

Add a new action `"bootstrap-user"` to the `actions` dictionary in `run_admin_cmd()`.

**Implementation**: `_action_bootstrap_user`

```python
async def _action_bootstrap_user(cli_logger, *, email, display_name, password, **_kwargs):
    """Create the first admin user and generate their API key."""
    from modules.backend.core.database import get_async_session
    from modules.backend.services.bootstrap import BootstrapService

    if not email:
        get_console().print("[red]--email is required[/red]")
        sys.exit(1)
    if not display_name:
        display_name = email.split("@")[0]
    if not password:
        import getpass
        password = getpass.getpass("Admin password (min 12 chars): ")
        if len(password) < 12:
            get_console().print("[red]Password must be at least 12 characters[/red]")
            sys.exit(1)

    async with get_async_session() as session:
        service = BootstrapService(session)
        user, api_key = await service.bootstrap_admin(
            email=email,
            display_name=display_name,
            password=password,
        )
        await session.commit()

    console = get_console()
    console.print(f"\n[green]Admin user created:[/green]")
    console.print(f"  Email: {user.email}")
    console.print(f"  Name:  {user.display_name}")
    console.print(f"  ID:    {user.id}")
    console.print(f"\n[yellow]API Key (save this — it will not be shown again):[/yellow]")
    console.print(f"  {api_key}")
    console.print()
```

### 12.2  Admin password reset CLI command

Add a `reset-password` action for admin password recovery when the admin is locked out of the web interface.

```python
@admin_group.command("reset-password")
@click.option("--email", required=True, help="User email address")
@click.option("--password", default=None, help="New password (prompted if omitted)")
```

**Implementation**: Load user by email, hash new password, update `hashed_password`, commit. This is a direct DB operation — no auth check needed (CLI access implies server access).

### 12.3  CLI parameter additions

The CLI entry point (likely in `cli.py` or `__init__.py`) needs to pass `email`, `display_name`, and `password` parameters when dispatching to `run_admin_cmd()` for the `bootstrap-user` action. Add Click options:

```python
@admin_group.command("bootstrap-user")
@click.option("--email", required=True, help="Admin email address")
@click.option("--name", "display_name", default=None, help="Display name")
@click.option("--password", default=None, help="Password (prompted if omitted)")
```

Find the CLI entry point by looking at how existing admin commands are registered and follow the same pattern.

---

## 13  Existing Code Updates

### 13.1  Files that reference `_resolve_role` or old auth pattern

Search the codebase for references to `_resolve_role`, `require_role`, and the old `require_admin`. These are all in `dependencies.py` and should be replaced by the new implementation. No other files reference these internal functions.

### 13.2  Tests that reference "trader" role

**File**: `tests/unit/backend/core/test_admin_auth.py` (and any other test files referencing "trader")

Update assertions to use "user" instead of "trader". Search: `rg "trader" tests/`.

### 13.3  Tests that reference `_resolve_role`

Update to test the new `get_current_user` dependency instead. The unit tests should mock the database session and verify:
- JWT resolution returns the correct user
- API key resolution returns the correct user
- Legacy `ADMIN_API_KEY` fallback works
- Invalid credentials raise `AuthenticationError`
- Inactive users are rejected

### 13.4  `security.py` — no changes needed

The existing functions in `modules/backend/core/security.py` are reused as-is:
- `hash_password()`, `verify_password()` — for user passwords
- `create_access_token()`, `create_refresh_token()`, `decode_token()` — for JWT
- `generate_api_key()`, `verify_api_key()` — for API keys

No modifications required to this file.

---

## 14  Implementation Order

Each phase should compile and pass tests independently. Do not proceed to the next phase until the current one is verified.

### Phase 1 — Models and Config (no runtime changes)

| Step | File | Action |
|------|------|--------|
| 1.1 | `modules/backend/models/user.py` | Create `SystemRole` enum and `User` model |
| 1.2 | `modules/backend/models/api_key.py` | Create `ApiKey` model |
| 1.3 | `modules/backend/models/__init__.py` | Add `User`, `SystemRole`, `ApiKey` imports and `__all__` entries |
| 1.4 | `config/settings/security.yaml` | Rename `trader` → `user`, update JWT audience to `mission-control-api`, add `X-API-Key` to CORS headers |
| 1.5 | `modules/backend/core/config_schema.py` | Add `auth_allow_self_registration: bool = False` to `FeaturesSchema` (no change needed for `SecuritySchema.roles` — defaults come from YAML) |
| 1.6 | `config/settings/features.yaml` | Add `auth_allow_self_registration: false` |

**Verify**: `python -c "from modules.backend.models.user import User, SystemRole; from modules.backend.models.api_key import ApiKey; print('OK')"` should succeed. Confirm `User` has `is_service_account` and `ApiKey` has `scopes` columns.

### Phase 2 — Migration

| Step | File | Action |
|------|------|--------|
| 2.1 | `modules/backend/migrations/versions/20260321_phase3_users_and_api_keys.py` | Create Alembic migration (see §4.1) |
| 2.2 | `modules/backend/migrations/env.py` | Add `User` and `ApiKey` imports |
| 2.3 | Run migration | `conda activate mission-control && python -m alembic -c modules/backend/migrations/alembic.ini upgrade head` |

**Verify**: `psql -U mission_control -d mission_control -c "\dt"` should show `users` and `api_keys` tables. `\d users` and `\d api_keys` should show correct columns and constraints.

### Phase 3 — Repositories

| Step | File | Action |
|------|------|--------|
| 3.1 | `modules/backend/repositories/user.py` | Create `UserRepository` |
| 3.2 | `modules/backend/repositories/api_key.py` | Create `ApiKeyRepository` |

**Verify**: Import both repositories in a Python REPL without errors.

### Phase 4 — Schemas

| Step | File | Action |
|------|------|--------|
| 4.1 | `modules/backend/schemas/user.py` | Create user schemas |
| 4.2 | `modules/backend/schemas/auth.py` | Create auth schemas |

**Verify**: Import and instantiate schemas with sample data.

### Phase 5 — Services

| Step | File | Action |
|------|------|--------|
| 5.1 | `modules/backend/services/auth.py` | Create `AuthService` |
| 5.2 | `modules/backend/services/user.py` | Create `UserService` |
| 5.3 | `modules/backend/services/bootstrap.py` | Create `BootstrapService` |

**Verify**: Import all services without errors.

### Phase 6 — Dependencies (the pivot point)

| Step | File | Action |
|------|------|--------|
| 6.1 | `modules/backend/core/dependencies.py` | Add `get_current_user`, `get_optional_user`, `CurrentUser`, `OptionalUser`. Rewrite `require_admin` and `AdminRole`. Remove old `_resolve_role` and `require_role`. |

**Verify**: The FastAPI app starts without errors: `conda activate mission-control && python -c "from modules.backend.main import create_app; app = create_app(); print('OK')"`.

### Phase 7 — API Endpoints

| Step | File | Action |
|------|------|--------|
| 7.1 | `modules/backend/api/v1/endpoints/auth.py` | Create auth router with all endpoints |
| 7.2 | `modules/backend/api/v1/endpoints/admin_users.py` | Create admin user management router with all user/role/key endpoints |
| 7.3 | `modules/backend/api/v1/__init__.py` | Register auth router at `/auth` and admin_users router at `/admin/users` |
| 7.4 | `modules/backend/api/v1/endpoints/admin.py` | Remove `# ---- User / Role Management ----` section (moved to admin_users.py) |

**Verify**: Start the server and confirm `/docs` shows the new auth and admin/users endpoints.

### Phase 8 — MissionMember FK

| Step | File | Action |
|------|------|--------|
| 8.1 | `modules/backend/models/mission.py` | Change `user_id` column to FK, add `user` relationship |

**Verify**: The app still starts. The FK constraint is enforced by the migration from Phase 2.

### Phase 9 — Bootstrap CLI

| Step | File | Action |
|------|------|--------|
| 9.1 | `modules/clients/cli/admin_cmds.py` | Add `bootstrap-user` action |
| 9.2 | `modules/clients/cli/admin_cmds.py` | Add `reset-password` action |
| 9.3 | CLI entry point | Add Click options for email, name, password |

**Verify**: `python cli.py admin bootstrap-user --email admin@mc.local --name Admin --password "securepassword1"` — should create user and print API key. `python cli.py admin reset-password --email admin@mc.local` — should prompt for and update password.

### Phase 10 — Test Updates

| Step | File | Action |
|------|------|--------|
| 10.1 | Update existing tests | Fix "trader" → "user" role references. Fix `_resolve_role` test mocks. |
| 10.2 | `tests/unit/backend/services/test_auth_service.py` | Unit tests for AuthService (login, resolve_api_key, resolve_jwt, create/revoke keys) |
| 10.3 | `tests/unit/backend/services/test_user_service.py` | Unit tests for UserService (CRUD, authorization checks) |
| 10.4 | `tests/unit/backend/api/test_auth_api.py` | Integration tests for auth endpoints |
| 10.5 | `tests/unit/backend/api/test_admin_users_api.py` | Integration tests for admin user management |
| 10.6 | Run full test suite | `pytest tests/` — no regressions |

---

## 15  Verification Checklist

After implementation, verify each of these manually:

| # | Test | Expected Result |
|---|------|-----------------|
| 1 | Run migration | `users` and `api_keys` tables created with correct schema |
| 2 | Bootstrap admin | `python cli.py admin bootstrap-user --email admin@mc.local --name Admin` prints API key |
| 3 | Login | `POST /api/v1/auth/login {"email": "admin@mc.local", "password": "..."}` returns JWT pair |
| 4 | JWT auth | `GET /api/v1/auth/me` with `Authorization: Bearer <token>` returns user info |
| 5 | API key auth | `GET /api/v1/auth/me` with `X-API-Key: <key>` returns user info |
| 6 | Create user | `POST /api/v1/admin/users` with admin auth creates a new user |
| 7 | Create key for user | `POST /api/v1/admin/users/{id}/api-keys` returns full key |
| 8 | Legacy fallback | `X-API-Key: <ADMIN_API_KEY from .env>` still works for admin endpoints |
| 9 | Role enforcement | Non-admin user gets 403 on admin endpoints |
| 10 | Deactivation | Deactivated user gets 401 on all auth attempts |
| 11 | Token refresh | `POST /api/v1/auth/refresh` with valid refresh token returns new pair |
| 12 | Key revocation | Revoked API key returns 401 |
| 13 | Password change | `POST /api/v1/auth/change-password` with correct old password succeeds |
| 14 | Existing tests | `pytest tests/` passes with no regressions |

---

## 16  Critical Files Reference

### Files to CREATE (new)

| File | Purpose |
|------|---------|
| `modules/backend/models/user.py` | User and SystemRole models |
| `modules/backend/models/api_key.py` | ApiKey model |
| `modules/backend/repositories/user.py` | UserRepository |
| `modules/backend/repositories/api_key.py` | ApiKeyRepository |
| `modules/backend/schemas/user.py` | User request/response schemas |
| `modules/backend/schemas/auth.py` | Auth request/response schemas |
| `modules/backend/services/auth.py` | AuthService (login, JWT/API key resolution, key management) |
| `modules/backend/services/user.py` | UserService (CRUD, authorization) |
| `modules/backend/services/bootstrap.py` | BootstrapService (first admin creation) |
| `modules/backend/api/v1/endpoints/auth.py` | Auth API router |
| `modules/backend/api/v1/endpoints/admin_users.py` | Admin user management router |
| `modules/backend/migrations/versions/20260321_phase3_users_and_api_keys.py` | Alembic migration |

### Files to MODIFY (existing)

| File | Change |
|------|--------|
| `modules/backend/models/__init__.py` | Add User, SystemRole, ApiKey imports |
| `modules/backend/models/mission.py` | Add FK and relationship on MissionMember.user_id |
| `modules/backend/core/dependencies.py` | Replace auth dependencies with User-based versions |
| `modules/backend/api/v1/__init__.py` | Register auth router |
| `modules/backend/api/v1/endpoints/admin.py` | Remove User/Role Management section (moved to admin_users.py) |
| `modules/backend/migrations/env.py` | Add model imports for autogenerate |
| `modules/clients/cli/admin_cmds.py` | Add bootstrap-user action |
| `config/settings/security.yaml` | Rename trader→user, update audience, CORS headers |
| `config/settings/features.yaml` | Add auth_allow_self_registration flag |
| `modules/backend/core/config_schema.py` | Add `auth_allow_self_registration` to `FeaturesSchema` |

### Files to REUSE (read-only reference)

| File | What to reuse |
|------|---------------|
| `modules/backend/core/security.py` | `hash_password`, `verify_password`, `create_access_token`, `create_refresh_token`, `decode_token`, `generate_api_key`, `verify_api_key` |
| `modules/backend/core/exceptions.py` | `AuthenticationError`, `AuthorizationError`, `ConflictError`, `ValidationError`, `NotFoundError` |
| `modules/backend/models/base.py` | `Base`, `UUIDMixin`, `TimestampMixin` patterns |
| `modules/backend/repositories/base.py` | `BaseRepository` generic CRUD pattern |
| `modules/backend/services/base.py` | `BaseService` pattern with `_execute_db_operation()` |
| `modules/backend/schemas/base.py` | `ApiResponse`, `ResponseMetadata` envelope |

---

## 17  Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| AdminRole type change breaks admin endpoints | All admin endpoints fail | Verified: all 15 endpoints use `_role: AdminRole` as throwaway — type change is transparent |
| Legacy ADMIN_API_KEY fallback has no matching admin user in DB | Fallback fails with error | BootstrapService creates the admin user. Fallback gracefully raises AuthenticationError if no admin exists. |
| Bcrypt key lookup too slow with many keys | Auth latency > 500ms | Prefix narrowing reduces bcrypt comparisons to 1-2 per request |
| Bcrypt blocks async event loop | All concurrent requests stall during hash | Wrap all bcrypt calls in `asyncio.to_thread()` |
| Migration breaks existing MissionMember data | FK constraint violation | Migration creates placeholder users, then UPDATEs `mission_members.user_id` to new UUIDs before adding FK |
| Legacy `==` comparison on ADMIN_API_KEY | Timing attack leaks key bytes | Use `hmac.compare_digest()` for constant-time comparison |
| Deactivated user retains valid API keys | Deactivated user can still authenticate | `deactivate_user()` also revokes all active API keys |
| JWT secret rotation invalidates all tokens | All users logged out | Documented in auth spec. Accept this as expected behaviour during rotation. |
| Password-less users (API-key-only) try to login via JWT | Confusing error | `AuthService.login()` returns clear error: "Password login not configured for this account" |
| `get_optional_user` catches broad `Exception` | Masks real bugs (DB errors, import errors) | Narrow catch to `AuthenticationError` only |
| User deletion cascades to mission members | Mission history silently lost | FK uses `ON DELETE RESTRICT` — admin must reassign or archive missions first |

---

## 18  Five-Angle Review Findings

This plan was reviewed from five angles: security, database integrity, modularity, future-proofing, and operations. All 14 must-fix findings have been incorporated into the plan above. Summary of changes made:

| # | Finding | Section Updated |
|---|---------|----------------|
| 1 | Migration must UPDATE `mission_members.user_id` to placeholder UUIDs (not just INSERT placeholder users) | §4.1 step 3 |
| 2 | Bcrypt blocks event loop — wrap in `asyncio.to_thread()` | §8.1 implementation notes |
| 3 | `get_optional_user` catches `Exception` — narrow to `AuthenticationError` | §9.1 |
| 4 | Deactivating user should revoke all their API keys | §8.2 `deactivate_user`, §6.2 `revoke_all_by_user` |
| 5 | Legacy ADMIN_API_KEY uses `==` — use `hmac.compare_digest()` | §2 D6, §8.1 `resolve_legacy_key` |
| 6 | No `jti` claim in JWTs — add UUID jti for future revocation | §8.1 implementation notes |
| 7 | `has_role()` hardcodes role levels — read from config | §3.1 helper method |
| 8 | Add nullable `scopes` JSON column to `api_keys` | §3.2 |
| 9 | Add `is_service_account` boolean to `users` | §3.1, §7.1 |
| 10 | Move legacy fallback into `AuthService.resolve_legacy_key()` | §8.1, §9.1 |
| 11 | `MissionMember.user_id` FK should be `ON DELETE RESTRICT` | §4.1 step 4, §11.1 |
| 12 | BootstrapService should take session in `__init__` | §8.3 |
| 13 | Split admin user endpoints into `admin_users.py` | §10.2, §10.3, §14 Phase 7, §16 |
| 14 | Add admin `reset-password` CLI command | §12.2 |

**Acknowledged for later** (not in scope for this plan):

- Rate limiting on login (10 req/min) — middleware concern
- Token blacklist / `jti` enforcement — needs Redis, separate plan
- OAuth/SSO — not needed at current scale
- Email verification — needs email service
- Scope enforcement on API keys — column added, enforcement later
- Audit logging of auth events — separate plan
- `Mission.owner_id` FK — denormalized field, separate cleanup
- Password complexity rules beyond min length — later enhancement

---

## 19  What This Plan Does NOT Cover (pre-review list)

| Topic | Why excluded | Where it belongs |
|-------|-------------|-----------------|
| OAuth / SSO integration | Not needed for current team size | Future plan |
| Email verification | Requires email service integration | Feature flag `auth_require_email_verification` already exists |
| Password reset via email | Requires email service | Future plan |
| Session revocation / token blacklist | JWT is stateless by design; acceptable for current scale | Future plan if needed |
| Rate limiting on login endpoint | Documented in auth spec (10 req/min) but not yet implemented | Middleware enhancement |
| Frontend auth implementation | Defined in Plan 29 §5.1, §8, §10.4 | Plan 29 |
| Mission.owner_id FK to users | Denormalized field, ownership is via MissionMember | Future cleanup |
| Audit logging of auth events | Documented in auth spec §Audit Logging | Future plan |

---

## 20  Success Criteria

1. A fresh database can be bootstrapped with an admin user via CLI
2. Users can authenticate via email/password (JWT) or API key
3. The frontend login flow from Plan 29 works end-to-end
4. Admin endpoints are protected by user-based role checking
5. Users can manage their own API keys (create, list, revoke)
6. Admins can create users, manage roles, reset passwords, and manage anyone's API keys
7. `MissionMember.user_id` is a proper FK to the `users` table
8. The legacy `ADMIN_API_KEY` continues to work during migration
9. All existing tests pass after the changes
10. The "trader" role is fully removed from the codebase
