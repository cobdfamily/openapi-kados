# KADOS test harness

End-to-end test of DODP v2 `logOn` against the KADOS
container brought up by
`include/adapter/docker-compose.yaml`.

Files:

- `mock_backend.py` --- stdlib HTTP mock of the
  OpenAPI backend the adapter calls out to. Accepts
  user `testuser` / password `testpass`.
- `test_logon.py` --- unittest that posts raw SOAP
  logOn envelopes and asserts success/fault paths.
- `requirements.txt` --- just `requests`.

## One-shot run (with the mock)

From the `include/adapter/` directory:

    # 1. Install deps
    python3 -m pip install -r services/kados/tests/requirements.txt

    # 2. Start the mock backend (listens on :5555)
    python3 services/kados/tests/mock_backend.py &

    # 3. Bring up KADOS pointing at the mock.
    #    host.docker.internal resolves to the macOS
    #    / Windows host from inside the container.
    OPENAPI_BASE_URL=http://host.docker.internal:5555 \
        docker compose up -d

    # 4. Run the tests
    python3 -m unittest services/kados/tests/test_logon.py

On Linux hosts without `host.docker.internal`, add to
the compose service:

    extra_hosts:
      - "host.docker.internal:host-gateway"

## Running against a real backend

If a real OpenAPI server is available, skip the mock
and point compose straight at it:

    OPENAPI_BASE_URL=https://library.example.org \
        OPENAPI_API_KEY=sk_live_xxx \
        docker compose up -d
    KADOS_USERNAME=realuser \
        KADOS_PASSWORD=realpass \
        python3 -m unittest services/kados/tests/test_logon.py

## Env vars used by the tests

    KADOS_SERVICE_URL  default http://localhost:8080/service.php
    KADOS_USERNAME     default testuser
    KADOS_PASSWORD     default testpass

## What is actually tested

- `GET {service}?wsdl` returns the WSDL with the
  DODP target namespace.
- `logOn` with valid credentials returns a
  `logOnResponse` with no `Fault`.
- `logOn` with bad credentials returns a SOAP
  `Fault` (HTTP 500 from PHP SoapServer).
