# OpenAPIAdapter Authentication Flow

The OpenAPIAdapter is a thin HTTP proxy between the
Kolibre KADOS SOAP service and a remote library
backend. Every adapter method forwards to one
endpoint shape:

    POST {baseUrl}/protocols/kados/v1/methods/{methodName}/

with a JSON body:

    { "method": "<methodName>", "data": { ...args } }

and expects a response envelope:

    { "data": <value matching the method contract> }

The `data` value is returned to the caller verbatim.
This document describes how authentication and user
context are layered on top of that envelope.

## Configuration

The adapter reads two values at construction time:

- Base URL --- taken from the first constructor
  argument if passed a non-empty string, otherwise
  from the environment variable `OPENAPI_BASE_URL`.
  Required. If neither source yields a value the
  constructor throws `AdapterException`.

- API key --- taken from the second constructor
  argument if passed a non-empty string, otherwise
  from the environment variable `OPENAPI_API_KEY`.
  Optional. When present it is sent as `X-API-Key`
  on every request.

Example:

    OPENAPI_BASE_URL=https://library.example.org \
    OPENAPI_API_KEY=sk_live_xxx \
    php your-soap-endpoint.php

Or explicitly:

    $adapter = new OpenAPIAdapter(
        'https://library.example.org',
        'sk_live_xxx'
    );

`setBaseUrl()` and `setApiKey()` setters remain
available for post-construction changes.

## Headers

Two authentication headers may be sent:

- `X-API-Key: <key>` --- app-level credential.
  Identifies the deploying service. Sent on every
  request when an API key is configured, regardless
  of login state.

- `Authorization: Session <token>` --- user-level
  credential. Scopes the request to a logged-in
  user. Sent only after a successful authenticate.

Both headers may appear on the same request. The
API key does not grant user context by itself; the
backend MUST NOT treat it as a substitute for a
session token on user-scoped endpoints.

## Login (authenticate)

The abstract method `authenticate($username,
$password)` is the single point where a user
session is established. The adapter:

1. Clears any previously held session token.

2. Issues `POST /protocols/kados/v1/methods/authenticate/`
   with body:

        {
          "method": "authenticate",
          "data": {
            "username": "...",
            "password": "...",
            "deviceManufaturer": "...",
            "deviceModel": "...",
            "deviceSerial": "...",
            "deviceVersion": "...",
            "protocolVersion": 1 or 2
          }
        }

   Device fields and protocol version are pulled
   from the base class properties that KADOS
   populates before calling `authenticate`.

3. Parses the response. The backend MUST return:

        {
          "data": {
            "authenticated": true,
            "sessionToken": "<opaque string>",
            "user": "<optional user id>"
          }
        }

   When `authenticated` is `true`, `sessionToken`
   is required. `user` is optional; if present it
   is stored on the base class `$user` slot for
   consistency with other adapters.

   A bare boolean shape `{ "data": true | false }`
   is also accepted for backends that do not issue
   tokens. In that case no user-scoped calls will
   succeed, because no `Authorization: Session`
   header can be sent.

4. Stores `sessionToken` in a private property.

5. Returns only the boolean to the caller. This
   matches the abstract contract and ensures the
   token never leaks back to SOAP-layer code.

## Authenticated calls

Once a token is held, every subsequent `callAPI`
invocation attaches:

    Authorization: Session <token>

The backend uses the token to resolve the user and
authorize the call. Endpoints that require a
session and receive no valid token MUST respond
with an HTTP 401.

## Session lifecycle

- `startSession()` forwards to the backend. The
  backend should validate the current token and
  return `{ "data": true }` if still alive, else
  `{ "data": false }`. KADOS invokes this on every
  non-logon call after session init.

- `stopSession()` forwards to the backend so it
  can invalidate the token server-side, then nulls
  the local token. KADOS invokes this on logoff
  and immediately before any re-logon.

- A `false` return from `startSession` tells KADOS
  to force a fresh `logOn`, at which point
  `authenticate` will run again and acquire a new
  token.

## Persistence across SOAP requests

KADOS serializes the adapter instance into
`$_SESSION` between SOAP calls. To survive the
serialize/unserialize round-trip, the adapter
implements `__sleep` and whitelists:

    baseUrl, apiKey, sessionToken, timeout,
    user, protocolVersion,
    deviceManufaturer, deviceModel,
    deviceSerial, deviceVersion

No `__wakeup` is required because every preserved
field is a plain scalar.

## Failure modes

- Transport failure (DNS, timeout, TLS) throws
  `AdapterException`. The session token is left in
  place so the next call can retry.

- Non-2xx HTTP status throws `AdapterException`
  carrying the status code and response body.

- Response body that is not valid JSON, or that
  lacks a top-level `data` key, throws
  `AdapterException`.

- HTTP 401 on a user-scoped call currently
  surfaces as a generic `AdapterException`. If
  auto-clearing a stale token on 401 is desired,
  that is a small follow-up in `callAPI`.

## Backend contract checklist

1. `POST /protocols/kados/v1/methods/authenticate/`
   returns
   `{ data: { authenticated, sessionToken, user? } }`
   on success.
2. Every other endpoint honors
   `Authorization: Session <token>` and resolves
   the user from it.
3. `POST /protocols/kados/v1/methods/stopSession/`
   invalidates the token server-side.
4. `POST /protocols/kados/v1/methods/startSession/`
   validates the current token and returns a
   boolean.
5. Tokens are opaque to the adapter; the backend
   may rotate or expire them at will, provided it
   returns false from `startSession` once a token
   is no longer usable.
