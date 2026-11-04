# 05 - Authentication and Authorization

*Version: 1.1.0*
*Author: Architecture Team*
*Created: 2025-01-27*

## Changelog

- 1.1.0 (2026-02-11): Refocused on authentication/authorization; security standards moved to 06-security-standards.md, data protection to 07-data-protection.md
- 1.0.0 (2025-01-27): Initial generic authentication and security standard

---

## Context

Authentication and authorization are the most security-critical parts of any application. Getting them wrong means data breaches, unauthorized access, or privilege escalation. This document defines the authentication methods, token lifecycle, authorization model, and rate limiting standards that every project must implement.

The architecture supports three authentication methods because different clients have different needs: API keys for programmatic access (CLI, service-to-service, integrations), JWT tokens for web sessions (short-lived access + long-lived refresh), and session cookies as an alternative for traditional web flows. API keys are the primary method because they are simpler, stateless, and work across all client types.

The key design decision is that authorization checks happen in the service layer, not the API layer. This ensures that business rules about who can access what are enforced regardless of how the service is called — whether from an HTTP endpoint, a background task, or another module's internal API. Security standards (06) and data protection (07) complement this document with deeper technical controls and privacy requirements respectively.

---

## Authentication Methods

### API Keys

Primary authentication for all programmatic access.

Use cases:
- CLI applications
- Service-to-service communication
- Third-party integrations

Key format: `prefix_randomstring`
- Prefix identifies key type (e.g., `app_` for application)
- Random string: 32+ characters, cryptographically random

Key storage:
- Database stores hashed key (bcrypt)
- Full key shown only at creation time
- Keys can be named for identification

Key lifecycle:
- User creates key via web interface or API
- Keys have optional expiration
- Keys can be revoked immediately
- Revoked keys rejected on next use

### JWT Tokens

Used for web session management.

Token types:
- Access token: Short-lived (30 minutes)
- Refresh token: Long-lived (7 days)

Token content:
- User ID
- Role (access token only; authorisation reads the role from the user record, not from the token)
- Expiration timestamp
- Token ID (`jti`)
- Token version (`tv`): the user's `token_version` at login. A token whose `tv` differs from the user's current value is refused ("Session ended"), and one without a `tv` is refused ("Invalid token")
- Issued-at (`iat`): used to refuse a refresh token that outlives the configured lifetime
- Session ID (`sid`): minted at login and carried by every token refreshed from it. A token without a `sid` is refused ("Invalid token"), so tokens issued before this claim existed cannot be used or refreshed; users sign in once. A token whose session has been logged out is refused ("Session ended")

Token storage (web clients), as implemented:
- Access token: memory only, never persisted
- Refresh token: `localStorage` (key `mc_refresh_token`). Any script running on the page can read it, so a cross-site scripting flaw exposes a 7-day credential. This is a known risk
- Target design, not implemented: the refresh token in an HttpOnly, Secure, SameSite cookie, which needs CSRF protection and per-environment cookie settings

Token refresh flow, as implemented:
1. Access token expires and a request returns 401
2. Client sends the refresh token to `POST /auth/refresh`
3. Server validates it: type, subject, session, token version and lifetime
4. Server issues a new access/refresh pair in the same session (same `sid`)
5. The old refresh token is not invalidated. It works until it expires, or until logout, a password change, an admin reset or a deactivation ends the session
- Target design, not implemented: single-use refresh tokens (rotation), which need a grace window so that two browser tabs refreshing at once do not sign each other out

Logout (`POST /auth/logout`):
1. Client calls it with the access token, before clearing its own state
2. Server stores the `sid` in `revoked_sessions` and commits before answering
3. Access and refresh verification reject any token whose `sid` is stored, so every token minted from that login stops working, including earlier refresh tokens
4. Rows are deleted by the daily cleanup one `refresh_token_expire_days` after logout. That outlives every token of the session because a refresh token whose lifetime (`exp` minus `iat`) exceeds the configured value is refused, so lowering the setting ends older, longer-lived refresh tokens at once
5. If the call fails or gets no answer within 5 seconds, the client still signs out locally and tells the user the session stays valid until it expires
6. An SSE token (`POST /auth/sse-token`) records the identity it was minted from (`sid`, `tv`) and is refused at connect once that session has ended
7. An open SSE stream re-validates its credential every `security.sse.session_recheck_seconds` (30), using a database session that is released straight away. When the session has ended, whether by logout, a password change, a reset or a deactivation, it sends `event: session_ended` and closes, so a revoked stream lives at most one interval

Ending every session of a user (no list of sessions exists, so this raises `users.token_version`):
1. A password change, an admin password reset and a deactivation each increment `token_version` in the same transaction as the change
2. Every access and refresh token issued earlier carries the old `tv` and stops working, on every device, including the one that made the change
3. A reactivated user does not get old sessions back, because deactivation raised the version
4. After a password change the client clears its own session without calling `POST /auth/logout` and returns to sign-in

### Session Cookies

Alternative to JWT for web applications preferring server-side sessions.

Cookie configuration:
- HttpOnly: true (not accessible to JavaScript)
- Secure: true (HTTPS only)
- SameSite: Strict or Lax
- Domain: Specific domain, not wildcard

Session storage: Redis with TTL matching session duration.

---

## Authorization

### Role-Based Access Control

Users have roles. Roles have permissions.

Standard roles:
- `admin`: Full system access
- `user`: Standard access to own resources
- `readonly`: View-only access

Permissions are fine-grained:
- `resource:create`
- `resource:read`
- `resource:update`
- `resource:delete`

### Resource Ownership

Resources belong to users or organizations. Authorization checks:
1. User authenticated
2. User has required permission
3. User owns resource or has explicit access grant

### Authorization Enforcement

Authorization is checked at the **service layer**, not the API layer. This ensures rules are enforced regardless of how the service is called (HTTP endpoint, background task, agent tool, internal API).

```python
# 1. API layer: extract user identity (thin — no authorization logic)
@router.get("/orders/{order_id}")
async def get_order(
    order_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DbSession,
):
    service = OrderService(db)
    return await service.get_order(order_id, requesting_user=current_user)

# 2. Service layer: enforce authorization (all logic here)
class OrderService:
    async def get_order(self, order_id: UUID, requesting_user: User) -> OrderSchema:
        order = await self.repo.get(order_id)
        if not order:
            raise NotFoundError("Order not found")
        if order.user_id != requesting_user.id and not requesting_user.has_role("admin"):
            raise AuthorizationError("Not authorized to view this order")
        return OrderSchema.model_validate(order)

# 3. get_current_user dependency: resolves token/API key to User object
async def get_current_user(request: Request, db: DbSession) -> User:
    """Extract API key or JWT, validate, return User.
    This is the ONLY place auth tokens are parsed."""
    ...
```

**Rules:**
- API layer passes `requesting_user` to every service method that needs authorization
- Service layer checks permissions and resource ownership
- `AuthorizationError` raised in service, converted to 403 by exception handler
- Never rely on API layer alone for authorization

---

## Password Security

### Password Requirements

Minimum requirements:
- 12 characters minimum
- No maximum length
- No complexity requirements (length matters more)

Recommended: Encourage passphrase usage in UI.

### Password Storage

Passwords hashed with bcrypt:
- Work factor: 12 (adjust based on hardware)
- Each password has unique salt

Never:
- Store plaintext passwords
- Store reversibly encrypted passwords
- Log passwords or tokens

### Password Reset

Flow:
1. User requests reset via email
2. System generates time-limited token (1 hour)
3. Token sent via email (never in URL visible to logs)
4. User submits new password with token
5. Token invalidated after use
6. All existing sessions invalidated on reset

---

## API Security

### Rate Limiting

All endpoints rate limited:
- Per API key or user
- Per IP address (for unauthenticated endpoints)

Default limits:
- Authenticated: 1000 requests/minute
- Unauthenticated: 100 requests/minute
- Login endpoint: 10 requests/minute

Rate limit response: 429 Too Many Requests with Retry-After header.

### Input Validation

All inputs validated:
- Type checking (Pydantic)
- Length limits
- Format validation (email, UUID, etc.)
- Sanitization for injection prevention

Validation errors return 400 with specific field errors.

### Output Encoding

Responses properly encoded:
- JSON responses with correct Content-Type
- HTML content escaped
- User-generated content never rendered as HTML

### Request Size Limits

Maximum request body: 10MB default
Large uploads use separate upload endpoint with streaming.

---

## Network Security

### HTTPS Requirement

All production traffic over HTTPS.

Development may use HTTP for localhost only.

TLS configuration:
- Minimum TLS 1.2
- Strong cipher suites only
- HSTS headers enabled

### CORS Configuration

CORS headers configured per environment:
- Development: Allow localhost origins
- Production: Allow only production domains
- Never: Allow wildcard origins

### Security Headers

All responses include:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'self'`
- `Strict-Transport-Security: max-age=31536000`

---

## Secrets Management

### Environment Variables

Secrets passed via environment variables:
- Database credentials
- API keys for external services
- JWT signing keys
- Encryption keys

Never in:
- Code
- Configuration files in repository
- Logs

### Environment Files

`.env` files:
- Not committed to repository
- `.env.example` shows required variables (no real values)
- Different files per environment

### Rotation

Secrets should be rotatable without downtime:
- JWT keys: Support multiple active keys during rotation
- API keys: Issue new before revoking old
- Database passwords: Application handles reconnection

---

## Audit Logging

### What to Log

Security-relevant events:
- Authentication attempts (success and failure)
- Authorization failures
- Password changes
- API key creation/revocation
- Admin actions
- Data exports

### Audit Log Content

Each entry contains:
- Timestamp (UTC, microsecond precision)
- Event type
- User ID (if authenticated)
- IP address
- User agent
- Resource affected
- Outcome (success/failure)
- Additional context as needed

### Audit Log Protection

Audit logs:
- Append-only (no updates or deletes)
- Separate storage from application logs
- Retained per compliance requirements
- Access restricted to security team

---

## Vulnerability Prevention

### SQL Injection

Prevented by:
- Parameterized queries only
- ORM with parameter binding
- Never string concatenation for queries

### Cross-Site Scripting (XSS)

Prevented by:
- Output encoding in templates
- Content-Security-Policy headers
- JSON responses for API data

### Cross-Site Request Forgery (CSRF)

Prevented by:
- SameSite cookie attribute
- CSRF tokens for state-changing requests (form submissions)
- API endpoints use token auth (not vulnerable)

### Injection Attacks

General prevention:
- Validate and sanitize all inputs
- Use safe APIs (subprocess with list arguments, not shell=True)
- Escape special characters for context

---

## Incident Response

### Security Event Detection

Monitor for:
- Unusual authentication failure patterns
- API key usage from unexpected locations
- Rate limit violations
- Authorization failures

### Response Procedures

When security incident detected:
1. Assess scope and severity
2. Contain (revoke keys, block IPs as needed)
3. Investigate root cause
4. Remediate vulnerability
5. Notify affected users if data exposure
6. Post-incident review

### Disclosure

Security vulnerabilities reported via designated channel.
Response timeline:
- Acknowledge within 24 hours
- Initial assessment within 72 hours
- Fix timeline communicated
