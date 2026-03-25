# Plan 31 — Current Mission Selection

| Field | Value |
|-------|-------|
| **Status** | Complete |
| **Created** | 2026-03-24 |
| **Depends on** | Plan 30 (User Management — complete), Plan 28 (Mission Control Platform — complete) |
| **Blocked by** | Nothing — P3 (Breaking Changes Are Free) applies |
| **Target** | models, schemas, services, repositories, API, CLI, TUI, migration |

---

## 1  Objective

Add a **current mission** selection to the user profile so that every authenticated client (CLI, TUI, web frontend, Telegram) knows which mission the user is working in — without the user specifying `--mission` on every command.

Today:
- The CLI requires `--mission <id>` on most commands, or ignores mission context entirely
- The TUI opens a mission picker modal on every launch
- The web frontend has no mission context
- There is no cross-client persistence — selecting a mission in the TUI has no effect on the CLI

After this plan:
- `current_mission_id` lives on the `users` table as a nullable FK to `missions`
- Any client can set it (`mission use <id>`, TUI picker, frontend dropdown, Telegram `/use`)
- Any client can read it (returned in `/auth/me` and every `UserResponse`)
- Commands that need a mission fall back to the user's current selection when `--mission` is omitted
- The `👉` indicator marks the current mission in list views across all clients

**This is a user preference, not a client preference.** It belongs in the database, not in a local config file, because:
- **P3 (Single Source of Truth)** — one value, not N copies per client
- **P2 (Clients Are Stateless)** — clients read server state, they don't maintain their own
- All clients already authenticate and have access to the user profile

---

## 2  Design Decisions

### D1: Nullable FK on `users`, not a separate `user_preferences` table

**Decision**: Add `current_mission_id` as a nullable FK column directly on the `users` table.

**Rationale**: This is a single scalar value tightly coupled to user identity. A separate preferences table would be over-engineering — it adds a join, a new model, a new repository, and a new migration for one column. If we accumulate 3+ user preferences in the future, we can extract a table then. YAGNI applies.

### D2: FK with `SET NULL` on mission delete

**Decision**: `FOREIGN KEY (current_mission_id) REFERENCES missions(id) ON DELETE SET NULL`.

**Rationale**: If a mission is archived or deleted, the user's selection should silently clear rather than block the deletion or leave a dangling reference. The user will see "No mission selected" on their next command and can pick another. This is the least-surprising behavior.

### D3: Validation — mission must exist and be active

**Decision**: `set_current_mission()` in `UserService` validates that the mission exists and has status `active`. Setting a paused or archived mission is rejected.

**Rationale**: Allowing selection of an inactive mission would lead to confusing errors downstream when commands try to operate on it. Fail fast (P5).

### D4: No authorization check beyond authentication

**Decision**: Any authenticated user can select any active mission as their current mission.

**Rationale**: Mission membership governs what you can *do* within a mission, not which mission you can *look at*. Selecting a mission is a navigation action, not a privileged operation. The authorization layer on individual operations (create execution, modify team, etc.) already enforces access control. Adding a membership check here would prevent users from browsing missions they have viewer access to.

### D5: CLI uses a `@with_mission` decorator, not repeated fallback boilerplate

**Decision**: A single decorator resolves the mission ID from `--mission` flag → user profile → error. Commands use `@with_mission` and receive `mission_id: str` as a guaranteed-resolved parameter.

**Rationale**: The zeblit codebase copies the same 5-line fallback block into every command — a DRY violation. A decorator centralizes the resolution logic and keeps commands clean. This also aligns with Click's idioms (decorators compose naturally with `@click.option`).

### D6: TUI seeds `current_mission_id` from user profile on launch

**Decision**: The TUI reads the user's `current_mission_id` on startup and pre-selects that mission. The mission picker still opens if no mission is selected. When the user picks a mission in the TUI, it calls `set_current_mission()` to persist the choice server-side.

**Rationale**: This eliminates the "pick a mission every time you launch" friction while keeping the TUI stateless (P2). The TUI's `TuiState.current_mission_id` becomes a local cache of the server-side value, not an independent source of truth.

### D7: `GET /auth/me` returns `current_mission_id` — no extra API call needed

**Decision**: `UserResponse` includes `current_mission_id` and `current_mission_name` (denormalized for display convenience). Every client that authenticates already calls `/auth/me` or equivalent — the current mission comes for free.

**Rationale**: Avoids an extra round-trip. The denormalized `current_mission_name` prevents clients from needing to resolve the mission name separately just to display "👉 Current mission: Alpha".

---

## 3  Database Changes

### 3.1  `users` table — add column

```
ALTER TABLE users ADD COLUMN current_mission_id VARCHAR(36) NULL
    REFERENCES missions(id) ON DELETE SET NULL;

CREATE INDEX ix_users_current_mission_id ON users(current_mission_id);
```

| Column | Type | Constraints |
|--------|------|-------------|
| current_mission_id | String(36) | NULLABLE, FK → missions.id ON DELETE SET NULL, INDEXED |

### 3.2  Migration

**File**: `modules/backend/migrations/versions/20260324_phase4_current_mission.py`

**Revision**: `phase4_001`, revises `phase3_001`.

**Upgrade**:
1. Add column `current_mission_id` to `users` (String(36), nullable=True)
2. Add FK constraint referencing `missions.id` with `ON DELETE SET NULL`
3. Add index `ix_users_current_mission_id`

**Downgrade**:
1. Drop index `ix_users_current_mission_id`
2. Drop FK constraint
3. Drop column `current_mission_id`

---

## 4  Model Changes

### 4.1  `User` model

**File**: `modules/backend/models/user.py`

Add column:

```python
current_mission_id: Mapped[str | None] = mapped_column(
    String(36),
    ForeignKey("missions.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
```

Add relationship (for eager loading the mission name):

```python
current_mission: Mapped["Mission | None"] = relationship(
    "Mission",
    foreign_keys=[current_mission_id],
    lazy="joined",
)
```

The `lazy="joined"` ensures the mission name is available without an extra query when loading the user — critical for the `/auth/me` endpoint and the `get_current_user` dependency.

---

## 5  Schema Changes

### 5.1  `UserResponse`

**File**: `modules/backend/schemas/user.py`

Add fields:

```python
current_mission_id: str | None = None
current_mission_name: str | None = None
```

The `current_mission_name` is populated via a `@model_validator` or computed in the service layer from the joined relationship.

### 5.2  `UserBriefResponse`

No changes — brief responses don't need the current mission.

### 5.3  New schema: `SetCurrentMissionRequest`

```python
class SetCurrentMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str | None = Field(
        None,
        description="Mission ID to select, or null to clear selection",
    )
```

Accepting `null` allows clearing the selection explicitly.

---

## 6  Service Changes

### 6.1  `UserService.set_current_mission()`

**File**: `modules/backend/services/user.py`

```python
async def set_current_mission(
    self,
    user_id: str,
    mission_id: str | None,
    requesting_user: User,
) -> User:
    """Set or clear the user's current mission.

    Self only — users set their own current mission.
    Validates that the mission exists and is active.
    Pass mission_id=None to clear.
    """
```

Logic:
1. `_require_owner_or_admin(user_id, requesting_user)` — self or admin only
2. If `mission_id` is not None:
   - Look up mission via `MissionRepository.get_by_id_or_none(mission_id)`
   - If not found, raise `NotFoundError("Mission not found")`
   - If `mission.status != "active"`, raise `ValidationError("Cannot select a non-active mission")`
3. `user_repo.update(user_id, current_mission_id=mission_id)`
4. Log operation: `"current_mission_set"`, user_id, mission_id
5. Return updated user

### 6.2  `UserResponse` population

When building `UserResponse`, populate `current_mission_name` from the joined relationship:

```python
current_mission_name = user.current_mission.name if user.current_mission else None
```

This is handled in the API layer when constructing the response, or via a `@model_validator(mode="before")` on `UserResponse`.

---

## 7  API Changes

### 7.1  New endpoint: `PUT /auth/me/current-mission`

**File**: `modules/backend/api/v1/endpoints/auth.py`

```python
@router.put("/me/current-mission", response_model=ApiResponse, summary="Set current mission")
async def set_current_mission(
    body: SetCurrentMissionRequest,
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Set or clear the current user's active mission."""
```

Returns the updated `UserResponse` so the client has the new state immediately.

### 7.2  Existing endpoint: `GET /auth/me`

No code change needed — `UserResponse` already uses `from_attributes=True`. Adding the fields to the schema and the column to the model is sufficient. The joined relationship ensures `current_mission_name` is available.

---

## 8  CLI Changes

### 8.1  New command: `mission use <mission_id>`

**File**: `modules/clients/cli/mission_cmds.py`

```
python cli.py mission use <mission_id>
python cli.py mission use --clear
```

Calls `UserService.set_current_mission()` via the service factory. Prints confirmation:

```
👉 Current mission: Alpha (a1b2c3d4-...)
```

Or on clear:

```
Current mission cleared.
```

### 8.2  `@with_mission` decorator

**File**: `modules/clients/cli/mission_context.py` (new file)

```python
def with_mission(f):
    """Decorator that resolves mission_id from --mission flag or user profile.

    Adds --mission/-m option to the command. If not provided, reads the
    authenticated user's current_mission_id from the database. Raises
    UsageError if neither is available.
    """
```

Resolution order:
1. `--mission` / `-m` flag (explicit override)
2. `current_user.current_mission_id` (from DB)
3. `click.UsageError("No mission specified. Use 'mission use <id>' to set a default.")`

Usage in commands:

```python
@mission_group.command("detail")
@with_mission
async def detail(mission_id: str):
    ...
```

### 8.3  `mission list` — add `👉` indicator

When displaying the mission list table, compare each mission's ID against the authenticated user's `current_mission_id`. Prefix the name with `👉` if it matches.

After the table, print:

```
👉 Current mission: <name> (<id>)
```

Or if none is set:

```
No current mission set. Use 'mission use <id>' to select one.
```

### 8.4  Commands that adopt `@with_mission`

The following commands currently require `--mission` and should adopt the decorator:

- `mission detail`
- `mission archive`
- `mission context-show`
- `mission context-history`
- `mission summarize`
- `execution create` (needs mission context)
- `execution list` (scoped to mission)

Each command retains the `--mission/-m` option for explicit override.

---

## 9  TUI Changes

### 9.1  Startup: seed from user profile

**File**: `modules/clients/tui/app.py`

On `on_mount()`, after authentication:

```python
user = await self.bridge.get_current_user()
if user.get("current_mission_id"):
    await self._select_mission(user["current_mission_id"], user["current_mission_name"])
else:
    self.push_screen(MissionPickerScreen())
```

This replaces the current unconditional mission picker launch.

### 9.2  Mission picker: persist selection

When the user picks a mission in the TUI, call `set_current_mission()` via the service bridge:

```python
async def on_mission_selected(self, mission_id: str) -> None:
    await self.bridge.set_current_mission(mission_id)
    # Local state updates as before
```

### 9.3  ServiceBridge additions

**File**: `modules/clients/tui/services/service_bridge.py`

```python
async def get_current_user(self) -> dict[str, Any]:
    """Return the authenticated user's profile."""
    ...

async def set_current_mission(self, mission_id: str | None) -> None:
    """Set the current user's active mission."""
    ...
```

Both delegate to `UserService` via factory pattern.

---

## 10  Frontend Changes (Future)

No implementation in this plan — the React frontend is a skeleton. When built:

- The mission selector dropdown reads `current_mission_id` from the `/auth/me` response
- Changing the selection calls `PUT /auth/me/current-mission`
- All API calls include the mission context automatically

The API contract defined here is sufficient for the frontend.

---

## 11  Display Helper

### 11.1  Shared indicator function

**File**: `modules/clients/common/display.py`

```python
def annotate_current_mission(name: str, mission_id: str, current_mission_id: str | None) -> str:
    """Prefix mission name with 👉 if it's the current selection."""
    if mission_id == current_mission_id:
        return f"👉 {name}"
    return name
```

Used by CLI `mission list`, TUI mission picker, and future frontend. One function, not ad-hoc emoji insertion.

---

## 12  Implementation Order

| Step | Layer | Files | Description |
|------|-------|-------|-------------|
| 1 | Migration | `migrations/versions/20260324_phase4_current_mission.py` | Add column, FK, index |
| 2 | Model | `models/user.py` | Add column + relationship |
| 3 | Schema | `schemas/user.py` | Add fields to `UserResponse`, new `SetCurrentMissionRequest` |
| 4 | Service | `services/user.py` | Add `set_current_mission()` method |
| 5 | API | `api/v1/endpoints/auth.py` | Add `PUT /auth/me/current-mission` endpoint |
| 6 | Display | `clients/common/display.py` | Add `annotate_current_mission()` helper |
| 7 | CLI | `clients/cli/mission_context.py` | New file: `@with_mission` decorator |
| 8 | CLI | `clients/cli/mission_cmds.py` | Add `mission use` command, `👉` in list |
| 9 | CLI | Various command files | Adopt `@with_mission` on mission-scoped commands |
| 10 | TUI | `clients/tui/app.py`, `services/service_bridge.py` | Seed from profile, persist selection |
| 11 | Tests | `tests/unit/`, `tests/integration/` | Service, API, CLI, decorator tests |

Steps 1–5 are the backend foundation (can be done as one commit). Steps 6–10 are client adoption (can be parallelized across CLI and TUI). Step 11 accompanies each step.

---

## 13  Testing

### 13.1  Unit tests

- `test_user_service.py` — `set_current_mission()`: happy path, clear, not found, inactive mission, non-self user rejected
- `test_auth_api.py` — `PUT /auth/me/current-mission`: 200 on set, 200 on clear, 404 on bad mission, 422 on invalid body
- `test_auth_api.py` — `GET /auth/me`: verify `current_mission_id` and `current_mission_name` present in response
- `test_mission_context.py` — `@with_mission` decorator: flag takes precedence, fallback to user profile, error when neither set
- `test_display.py` — `annotate_current_mission()`: matching, non-matching, None

### 13.2  Integration tests

- Create user → set current mission → `GET /auth/me` returns it
- Delete mission → user's `current_mission_id` is NULL (ON DELETE SET NULL)
- Archive mission → `set_current_mission()` rejects it

---

## 14  What This Plan Does NOT Do

- **No client-side caching** — clients always read from the DB. If latency becomes an issue, caching can be added later without schema changes.
- **No multi-mission selection** — one current mission per user. "Workspaces" or "pinned missions" are a future concern.
- **No frontend implementation** — the API contract is defined; frontend adopts it when built.
- **No Telegram implementation** — same: the service method exists, Telegram bot adds a `/use` command when ready.
- **No migration of existing TUI state** — the TUI's `TuiState.current_mission_id` remains as a local cache. It is seeded from the DB on launch and written back on change.
