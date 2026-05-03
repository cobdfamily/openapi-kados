# KADOS test harness

End-to-end test of DODP v2 against the KADOS container brought
up by `docker-compose.yaml` at the repo root.

The default compose stack stands up two services on a shared
docker network:

  * `kados` — the upstream `kolibreorg/kados:v2-latest` image
    with the `OpenAPIAdapter` mounted in.
  * `hummingbird` —
    `kibble.apps.blindhub.ca/cobdfamily/hummingbird:latest`,
    pulled from the cobdfamily registry. Acts as the OpenAPI
    backend KADOS proxies into.

Files:

- `test_logon.py` — backend-agnostic SOAP `logOn` tests
  (WSDL, valid creds, invalid creds). Runs against any
  OpenAPI backend the compose file points KADOS at.
- `test_hummingbird_backend.py` — end-to-end tests that
  assume the default stack: hits hummingbird's `/`
  liveness directly, sends a `contentListExists` envelope
  straight to hummingbird's KADOS RPC surface, and runs
  the full SOAP `logOn` round-trip through KADOS into
  hummingbird. Auto-skips if hummingbird is not reachable.
- `mock_backend.py` — stdlib HTTP mock of the OpenAPI
  backend, kept for fully offline runs (no docker pull).
- `requirements.txt` — `requests`.

## Default flow (kados + hummingbird)

```sh
# 1. Bring the stack up. hummingbird gets pulled from
#    kibble.apps.blindhub.ca; kados waits for the
#    hummingbird healthcheck before starting.
docker compose up -d

# 2. Install the test harness deps (host Python).
python3 -m pip install -r services/kados/tests/requirements.txt

# 3. Run every test (logon + hummingbird backend assertions).
python3 -m unittest discover services/kados/tests

# 4. Tear down.
docker compose down
```

The compose file binds:

- `127.0.0.1:8080` -> KADOS `service.php` (port set by
  `KADOS_HTTP_PORT`).
- `127.0.0.1:8001` -> hummingbird's `:8000` (port set by
  `HUMMINGBIRD_HTTP_PORT`). Bound to localhost only — the
  KADOS container reaches hummingbird via the internal
  docker network as `http://hummingbird:8000`; the host
  binding is just for the test harness.

Default credentials: `testuser` / `testpass`. Set via
`HUMMINGBIRD_USERNAME` / `HUMMINGBIRD_PASSWORD` on the
hummingbird service.

## Offline flow (kados + python mock backend)

For a fully offline run with no docker pull of hummingbird:

```sh
# 1. Start the mock on the host.
python3 services/kados/tests/mock_backend.py &

# 2. Bring up KADOS only. host.docker.internal resolves
#    to the macOS / Windows host from inside the
#    container; on Linux add
#       extra_hosts:
#         - "host.docker.internal:host-gateway"
#    to the kados service.
OPENAPI_BASE_URL=http://host.docker.internal:5555 \
  docker compose up -d kados

# 3. Run only the backend-agnostic logon tests.
python3 -m unittest \
  services/kados/tests/test_logon.py
```

`test_hummingbird_backend.py` self-skips when the host port
8001 doesn't answer, so this flow is safe to leave the
hummingbird-backend file in place.

## Running against a real external backend

If a real OpenAPI backend is available off-host, point
`OPENAPI_BASE_URL` straight at it and skip both
hummingbird and the mock:

```sh
OPENAPI_BASE_URL=https://library.example.org \
  OPENAPI_API_KEY=sk_live_xxx \
  docker compose up -d kados

KADOS_USERNAME=realuser \
  KADOS_PASSWORD=realpass \
  python3 -m unittest \
    services/kados/tests/test_logon.py
```

## Env vars used by the tests

```
KADOS_SERVICE_URL    default http://localhost:8080/service.php
HUMMINGBIRD_BASE_URL default http://localhost:8001
KADOS_USERNAME       default testuser
KADOS_PASSWORD       default testpass
```

## What is actually tested

`test_logon.py` (backend-agnostic):

- `GET {service}?wsdl` returns the WSDL with the DODP
  target namespace.
- `logOn` with valid credentials returns a
  `logOnResponse` with no `Fault`.
- `logOn` with bad credentials returns a SOAP `Fault`
  (HTTP 500 from PHP SoapServer).

`test_hummingbird_backend.py` (auto-skips when
hummingbird unreachable):

- Hummingbird `/` returns the canonical
  `{service, status, version}` envelope; pins the
  contract the adapter implicitly relies on.
- POSTing the KADOS envelope `contentListExists` to
  hummingbird directly returns
  `{"data": true}` for the `bookshelf` list — proves
  the adapter <-> hummingbird wire contract
  without going through SOAP.
- Full `logOn` SOAP round-trip via KADOS into
  hummingbird succeeds for the compose-set
  credentials.
- The compose file pins the hummingbird image with an
  explicit tag (sentinel against accidentally
  rewriting the image line with no tag).
