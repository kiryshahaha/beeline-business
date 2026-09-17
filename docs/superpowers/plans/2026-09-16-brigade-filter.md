# Brigade Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add brigades, the `foreman` role, brigade membership management, and server-side brigade visibility for users and tickets.

**Architecture:** Keep `observer` as the global operator and add a normalized `brigades` plus `brigade_members` model with one active brigade per worker and one foreman per brigade. Reuse the existing explicit-SQL repository style; pass the authenticated viewer into read queries so `foreman` scope is applied in SQL before pagination and before returning detail records.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2 models, PostgreSQL, Alembic, Pydantic v2, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-brigade-filter-design.md`

## Global Constraints

- Preserve the existing `observer` global permissions.
- Store all membership and visibility rules in PostgreSQL-backed SQL, never in client-provided scope alone.
- Keep an anonymous ticket-read compatibility path; apply brigade scope whenever an authenticated `foreman` is present.
- Do not add CSV import until a stable worker/foreman identifier is available.
- Do not commit or push this branch.

### Task 1: Add role, models, migration, and schemas

**Files:**
- Create: `backend/migrations/versions/0006_add_brigades.py` (the branch already uses revision `0005` for comment timestamps)
- Create: `backend/app/modules/brigades/__init__.py`
- Create: `backend/app/modules/brigades/models.py`
- Create: `backend/app/modules/brigades/schemas.py`
- Modify: `backend/app/modules/users/enums.py`
- Modify: `backend/app/modules/users/models.py` only if shared type changes are required
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_brigade_migration.py`

**Interfaces:**
- Produces `UserRole.FOREMAN`, `Brigade`, `BrigadeMember`, and `BrigadeCreate`, `BrigadeMembersUpdate`, `BrigadeRead`.

- [ ] **Step 1: Write the failing migration/model tests**

  Add a PostgreSQL integration test that upgrades to `head`, asserts both brigade tables exist, checks the unique foreman and worker-membership indexes, inserts a valid foreman and worker, and asserts duplicate worker membership and an invalid role fail.

- [ ] **Step 2: Run the migration tests and verify the expected failure**

  Run `TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/beeline_test /private/tmp/beeline-hack-brigade-venv/bin/pytest -q tests/test_brigade_migration.py`. It must fail because migration `0005` and `FOREMAN` do not exist.

- [ ] **Step 3: Implement the role, SQLAlchemy models, registry, and migration**

  Extend the users role constraint to `observer`, `foreman`, and `worker`; create `brigades` with case-insensitive unique name and unique `foreman_id`; create `brigade_members` with foreign keys, composite primary key, unique `worker_id`, and indexes; import both models in `app/db/models.py`.

- [ ] **Step 4: Add strict Pydantic brigade schemas**

  Validate trimmed non-empty names, positive integer IDs, duplicate-free worker lists, and bounded list sizes; return `worker_ids` in `BrigadeRead`.

- [ ] **Step 5: Run the migration tests and verify they pass**

  Re-run the command from Step 2 and expect PASS.

### Task 2: Add brigade repository, service, and management API

**Files:**
- Create: `backend/app/modules/brigades/repository.py`
- Create: `backend/app/modules/brigades/service.py`
- Create: `backend/app/modules/brigades/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_brigades_api.py`

**Interfaces:**
- Consumes the models and schemas from Task 1.
- Produces `POST /api/v1/brigades`, `GET /api/v1/brigades`, `GET /api/v1/brigades/{id}`, and `PUT /api/v1/brigades/{id}/members`.

- [ ] **Step 1: Write failing API tests**

  Cover observer creation, duplicate names, non-foreman managers, unknown workers, replacement of membership, foreman-only list visibility, worker own-brigade visibility, observer global visibility, and 404 for a foreman requesting another brigade.

- [ ] **Step 2: Run the API tests to verify RED**

  Run `TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/beeline_test /private/tmp/beeline-hack-brigade-venv/bin/pytest -q tests/test_brigades_api.py`; expect import or 404 failures because the router is not registered.

- [ ] **Step 3: Implement repository queries and service validation**

  Use parameterized SQL, validate the manager role, validate all worker IDs, reject workers already assigned to another brigade, lock the brigade during replacement, and map database conflicts to domain exceptions.

- [ ] **Step 4: Register the router and map HTTP errors**

  Restrict mutations to `observer`, scope reads from `current_user.id`, return 201 for creation, 404 for hidden records, 409 for duplicate names or occupied memberships, and 422 for invalid member identities.

- [ ] **Step 5: Run the API tests and verify GREEN**

  Re-run the command from Step 2 and expect PASS.

### Task 3: Extend user role/profile handling and scoped user reads

**Files:**
- Modify: `backend/app/modules/users/schemas.py`
- Modify: `backend/app/modules/users/repository.py`
- Modify: `backend/app/modules/users/service.py`
- Modify: `backend/app/modules/users/router.py`
- Modify: `backend/app/modules/auth/dependencies.py`
- Test: `backend/tests/test_users_and_auth_api.py`

**Interfaces:**
- Consumes brigade membership queries from Task 2.
- Produces `foreman` user creation, `brigade_id`/`brigade_name` in `UserRead`, and scoped `GET /api/v1/users`/`GET /api/v1/users/{id}`.

- [ ] **Step 1: Add failing user-scope tests**

  Create a foreman with two workers in separate brigades, assert the foreman list contains only self and own workers, assert a foreign worker detail returns 404, and assert observers retain all users. Add a test that changing a worker to `foreman` removes worker membership safely.

- [ ] **Step 2: Run the user tests and verify RED**

  Run `TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/beeline_test /private/tmp/beeline-hack-brigade-venv/bin/pytest -q tests/test_users_and_auth_api.py`; expect the new tests to fail because `foreman` is rejected and repository queries have no scope.

- [ ] **Step 3: Implement role/profile validation and query scope**

  Permit `foreman` without a worker profile, reject a worker profile for that role, include the optional brigade fields in user rows, and add a `foreman` scope predicate that returns self plus workers in the foreman’s brigade.

- [ ] **Step 4: Wire current-user-aware user routes**

  Pass the authenticated viewer into list/detail service calls, keep observer behavior unchanged, and return 409 when deleting or demoting a foreman who still manages a brigade.

- [ ] **Step 5: Run focused and existing user tests**

  Re-run the command from Step 2 plus `/private/tmp/beeline-hack-brigade-venv/bin/pytest -q tests/test_auth_security.py tests/test_openapi.py` and expect PASS.

### Task 4: Add brigade filter and ticket visibility enforcement

**Files:**
- Modify: `backend/app/modules/auth/dependencies.py`
- Modify: `backend/app/modules/tickets/router.py`
- Modify: `backend/app/modules/tickets/service.py`
- Modify: `backend/app/modules/tickets/repository.py`
- Modify: `backend/app/modules/comments/repository.py`
- Modify: `backend/app/modules/comments/service.py`
- Modify: `backend/app/modules/tickets/schemas.py` only if OpenAPI examples need the new query description
- Test: `backend/tests/test_brigade_ticket_visibility.py`

**Interfaces:**
- Consumes `UserRole.FOREMAN` and `brigade_members` from Tasks 1–3.
- Produces optional `brigade_id` filtering, authenticated foreman scope in list/detail/comment reads, and scoped foreman comment writes.

- [ ] **Step 1: Write failing visibility tests**

  Create two brigades and three tickets, assign one ticket to each brigade and leave one unassigned; assert observer sees all, foreman sees only own assigned ticket, `brigade_id` cannot expand scope, foreign detail returns 404, foreman can write own-brigade comments, and foreman cannot change status.

- [ ] **Step 2: Run visibility tests to verify RED**

  Run `TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/beeline_test /private/tmp/beeline-hack-brigade-venv/bin/pytest -q tests/test_brigade_ticket_visibility.py`; expect failures because ticket SQL has no brigade predicate.

- [ ] **Step 3: Add optional-current-user dependency and parameterized SQL predicates**

  Keep anonymous reads working, add `brigade_id` to list parameters, and append `EXISTS` predicates joining `ticket_assignments`, `brigade_members`, and `brigades`; apply the viewer predicate before `ORDER BY`, `LIMIT`, and `OFFSET`.

- [ ] **Step 4: Apply the same scope to detail, status, and comments**

  Use the ticket visibility helper for detail and comments, return 404 for hidden records, reject foreman status writes with 403, and allow foreman comment writes only for visible tickets and own comment edits.

- [ ] **Step 5: Run visibility plus existing ticket/comment tests**

  Re-run the command from Step 2 plus `/private/tmp/beeline-hack-brigade-venv/bin/pytest -q tests/test_tickets_api.py tests/test_ticket_workflow_api.py tests/test_ticket_comments_api.py` and expect PASS.

### Task 5: Documentation, regression checks, and final review

**Files:**
- Modify: `backend/README.md`
- Modify: `backend/app/main.py` OpenAPI examples if required
- Test: `backend/tests/test_openapi.py`

- [ ] **Step 1: Document roles, brigade endpoints, and visibility rules**

  Add concise API documentation and note that CSV labels do not provide stable worker identifiers for import.

- [ ] **Step 2: Run the complete test suite and lint**

  Run `TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/beeline_test /private/tmp/beeline-hack-brigade-venv/bin/pytest -q` and `ruff check app migrations tests` from `backend`; resolve only regressions caused by this feature.

- [ ] **Step 3: Inspect migration heads and changed files**

  Run `alembic heads`, `git diff --check`, and `git status --short`; confirm no commit or push occurred and unrelated user files remain untouched.
