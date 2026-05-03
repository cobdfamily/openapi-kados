# openapi-kados

An OpenAPI-backed adapter for [Kolibre-KADOS][kados]
and a Docker Compose setup that runs the upstream
`kolibreorg/kados` image against an HTTP library
backend instead of a SQL database.

KADOS ships a PHP abstract `Adapter` class that the
DAISY Online Delivery Protocol (DODP v1 and v2.0.2)
SOAP service calls into for every operation --- list
content, fetch metadata, set bookmarks, log on, etc.
The stock adapter (`KobraAdapter`) talks to a
Postgres/MySQL database. This repo replaces it with
`OpenAPIAdapter`: a thin proxy that forwards each
adapter method to an HTTP endpoint on a remote
library backend and unwraps a uniform response
envelope.

## How it works

Every call the SOAP service makes on the adapter is
forwarded to:

    POST {OPENAPI_BASE_URL}/protocols/kados/v1/methods/<methodName>/

with a JSON body of:

    {
      "method": "<methodName>",
      "data": { ...named args... }
    }

The backend responds with:

    { "data": <value matching the method's return contract> }

The adapter returns the `data` value verbatim to the
SOAP layer. There is exactly one helper
(`OpenAPIAdapter::callAPI`) --- each abstract method
is a one-liner that packs its arguments and delegates
to it.

## Authentication

- `X-API-Key: <key>` --- app-level credential,
  optional, sent on every request when
  `OPENAPI_API_KEY` is set.
- `Authorization: Session <token>` --- user-level
  credential. Captured from the `authenticate`
  response and sent on every subsequent call. The
  adapter implements `__sleep` so the token survives
  `$_SESSION` serialization between SOAP requests.

The authenticate response contract:

    {
      "data": {
        "authenticated": true,
        "sessionToken": "<opaque>",
        "user": "<optional user id>"
      }
    }

Full flow, including `startSession` / `stopSession`
semantics and failure modes, is documented in
[`services/kados/includes/adapters/OpenAPIAdapter.md`][auth-doc].

## Configuration

Two environment variables drive the adapter:

| Variable           | Required | Purpose                     |
|--------------------|----------|-----------------------------|
| `OPENAPI_BASE_URL` | yes      | Root of the backend. The `/protocols/kados/v1/methods/<name>/` path is appended per call. |
| `OPENAPI_API_KEY`  | no       | Sent as `X-API-Key` on every outbound request.                                             |

Both can also be passed to the constructor
explicitly; the constructor argument wins.

## Quick start

The default compose stack stands up KADOS plus a
hummingbird backend pulled from the cobdfamily
registry, ready to talk out of the box:

    docker compose up

This pulls
`kibble.apps.blindhub.ca/cobdfamily/hummingbird:latest`,
brings it up with `testuser` / `testpass` credentials,
and then starts KADOS once hummingbird's healthcheck
passes. KADOS is reachable at
<http://localhost:8080/service.php> (WSDL at
<http://localhost:8080/service.php?wsdl>); hummingbird
is reachable directly at <http://localhost:8001/> for
test-harness assertions.

To point KADOS at an external OpenAPI backend instead,
override `OPENAPI_BASE_URL` and bring up just the
KADOS service:

    export OPENAPI_BASE_URL=https://library.example.org
    export OPENAPI_API_KEY=sk_live_xxx   # optional
    docker compose up -d kados

Override host ports with `KADOS_HTTP_PORT` (default
8080) and `HUMMINGBIRD_HTTP_PORT` (default 8001).

## Testing

A Python test harness in
[`services/kados/tests/`][tests] drives DODP v2
operations against the running container. There are
two test files:

- `test_logon.py` --- backend-agnostic SOAP `logOn`
  tests (WSDL, valid creds, invalid creds). Works
  against any OpenAPI backend.
- `test_hummingbird_backend.py` --- exercises the
  default kados+hummingbird stack end-to-end, hitting
  hummingbird directly for liveness + the adapter
  wire contract, then a full SOAP `logOn` round-trip
  through KADOS into hummingbird. Auto-skips when
  hummingbird isn't reachable.

Default flow:

    pip install -r services/kados/tests/requirements.txt
    docker compose up -d
    python3 -m unittest discover services/kados/tests

For fully offline runs, a stdlib `mock_backend.py`
ships with the harness; see the [tests README][tests]
for that flow plus the Linux-host `host.docker.internal`
note.

## Repo layout

    docker-compose.yaml          kados + hummingbird (kibble :latest)
    .gitignore
    services/
      kados/
        README.md                DODP spec links
        config/
          service.openapi.ini    service.ini override selecting OpenAPIAdapter
        includes/
          adapters/
            OpenAPIAdapter.class.php
            OpenAPIAdapter.md    auth / session flow reference
        docs/
          html/                  doxygen-rendered adapter API docs
        tests/
          README.md              how to run the harness
          mock_backend.py        offline backend mock
          test_logon.py          backend-agnostic SOAP tests
          test_hummingbird_backend.py
          requirements.txt

## DODP specifications

- DODP v1:
  <http://www.daisy.org/projects/daisy-online-delivery/drafts/20100402/do-spec-20100402.html>
- DODP v2.0.2:
  <http://www.daisy.org/projects/daisy-online-delivery/2-0/DODP2-0-2.html>

## Upstream

- Kolibre-KADOS: <https://github.com/kolibre/Kolibre-KADOS>
- Docker image: <https://hub.docker.com/r/kolibreorg/kados>

[kados]: https://github.com/kolibre/Kolibre-KADOS
[auth-doc]: services/kados/includes/adapters/OpenAPIAdapter.md
[tests]: services/kados/tests/README.md