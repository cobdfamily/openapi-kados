#!/usr/bin/env python3
"""Hummingbird-backed end-to-end test for OpenAPIAdapter.

These tests assume the docker-compose stack is up — kados +
hummingbird (the default ``docker compose up -d`` shape).
They exercise:

  * Hummingbird is reachable on its own port (the / liveness
    probe answers with version + status).
  * KADOS, fronting hummingbird via OPENAPIAdapter, accepts a
    SOAP logOn for the credentials the compose file set into
    HUMMINGBIRD_USERNAME / HUMMINGBIRD_PASSWORD.
  * KADOS contentList comes back with a (possibly empty)
    DODP response — i.e. kados -> hummingbird -> back through
    the adapter actually round-trips.

Bring the stack up with:

    docker compose up -d

then run:

    python3 -m unittest test_hummingbird_backend.py

Skip-by-default: tests are skipped if HUMMINGBIRD_BASE_URL points
nowhere reachable, so this file is safe to leave in the suite
even when only the mock backend is up.
"""

from __future__ import annotations

import os
import re
import unittest
import xml.etree.ElementTree as ET

import requests


HUMMINGBIRD_BASE_URL = os.environ.get(
    "HUMMINGBIRD_BASE_URL", "http://localhost:8001"
)
SERVICE_URL = os.environ.get(
    "KADOS_SERVICE_URL", "http://localhost:8080/service.php"
)
USERNAME = os.environ.get("KADOS_USERNAME", "testuser")
PASSWORD = os.environ.get("KADOS_PASSWORD", "testpass")

NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "d": "http://www.daisy.org/ns/daisy-online/",
}

LOGON_ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            xmlns:d="http://www.daisy.org/ns/daisy-online/">
  <s:Body>
    <d:logOn>
      <d:username>{username}</d:username>
      <d:password>{password}</d:password>
      <d:readingSystemAttributes>
        <d:manufacturer>Test Manufacturer</d:manufacturer>
        <d:model>Test Model</d:model>
        <d:serialNumber>SN-0001</d:serialNumber>
        <d:version>1.0</d:version>
        <d:config>
          <d:accessConfig>STREAM_AND_DOWNLOAD</d:accessConfig>
          <d:supportsMultipleSelections>false</d:supportsMultipleSelections>
          <d:supportsAdvancedDynamicMenus>false</d:supportsAdvancedDynamicMenus>
          <d:preferredUILanguage>en</d:preferredUILanguage>
          <d:bandwidth>0</d:bandwidth>
          <d:supportedContentFormats/>
          <d:supportedContentProtectionFormats/>
          <d:supportedMimeTypes/>
          <d:supportedInputTypes/>
          <d:requiresAudioLabels>false</d:requiresAudioLabels>
        </d:config>
      </d:readingSystemAttributes>
    </d:logOn>
  </s:Body>
</s:Envelope>"""


def _hummingbird_reachable() -> bool:
    try:
        r = requests.get(HUMMINGBIRD_BASE_URL + "/", timeout=2)
        return r.status_code == 200 and "hummingbird" in r.text
    except requests.RequestException:
        return False


@unittest.skipUnless(
    _hummingbird_reachable(),
    f"hummingbird not reachable at {HUMMINGBIRD_BASE_URL}; "
    "bring the stack up with `docker compose up -d`",
)
class HummingbirdBackendTests(unittest.TestCase):
    """End-to-end against the kados+hummingbird compose stack."""

    def test_hummingbird_liveness_returns_version(self):
        """The liveness response should look like:
        {"service":"hummingbird","status":"ok","version":"<n>"}.
        Pinning these fields locks the contract the adapter
        implicitly relies on (hummingbird advertises itself
        consistently)."""
        r = requests.get(HUMMINGBIRD_BASE_URL + "/", timeout=5)
        self.assertEqual(r.status_code, 200, msg=r.text[:500])
        body = r.json()
        self.assertEqual(body["service"], "hummingbird")
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["version"], msg="version field empty")
        # Sanity: looks like a SemVer (digit.digit.*).
        self.assertRegex(body["version"], r"^\d+\.\d+")

    def test_hummingbird_kados_contentListExists_directly(self):
        """Skip the SOAP layer for one assertion that proves the
        adapter's wire contract is actually what hummingbird
        speaks: authenticate, then POST kados envelope to
        /protocols/kados/v1/methods/contentListExists/ with the
        session token and expect the canonical
        {"data": <bool>} response.

        hummingbird's KADOS router (v0.7+) gates session-scoped
        methods on Authorization: Session; ``contentListExists``
        is one of those. The adapter handles this transparently
        for the SOAP layer (see OpenAPIAdapter::authenticate),
        but here we drive the contract by hand."""
        auth_url = (
            HUMMINGBIRD_BASE_URL
            + "/protocols/kados/v1/methods/authenticate/"
        )
        auth_body = {
            "method": "authenticate",
            "data": {
                "username": USERNAME,
                "password": PASSWORD,
            },
        }
        auth_r = requests.post(auth_url, json=auth_body, timeout=5)
        self.assertEqual(auth_r.status_code, 200, msg=auth_r.text[:500])
        token = auth_r.json()["data"]["sessionToken"]

        url = (
            HUMMINGBIRD_BASE_URL
            + "/protocols/kados/v1/methods/contentListExists/"
        )
        body = {"method": "contentListExists", "data": {"list": "bookshelf"}}
        r = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Session {token}"},
            timeout=5,
        )
        self.assertEqual(r.status_code, 200, msg=r.text[:500])
        self.assertEqual(r.json(), {"data": True})

    def test_logon_via_kados_against_hummingbird(self):
        """Full SOAP -> KADOS -> OPENAPIAdapter -> hummingbird
        round-trip: the credentials that compose set into
        HUMMINGBIRD_USERNAME / HUMMINGBIRD_PASSWORD must produce
        a successful logOn."""
        body = LOGON_ENVELOPE.format(username=USERNAME, password=PASSWORD)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"urn:http://www.daisy.org/ns/daisy-online/logOn"',
        }
        r = requests.post(SERVICE_URL, data=body.encode("utf-8"),
                          headers=headers, timeout=30)
        self.assertEqual(r.status_code, 200, msg=r.text[:1000])
        root = ET.fromstring(r.text)
        self.assertIsNone(
            root.find(".//s:Fault", NS),
            msg="Expected logOn to succeed against hummingbird:\n" + r.text,
        )
        self.assertIsNotNone(
            root.find(".//d:logOnResponse", NS),
            msg="Missing logOnResponse element:\n" + r.text,
        )

    def test_hummingbird_image_tag_is_pinned_or_latest(self):
        """The compose file pins hummingbird to ``latest``. If a
        future change pins to a specific release, this test
        catches the case where the compose file accidentally got
        rewritten with no tag (Docker would default to ``latest``
        silently; explicit is better)."""
        compose = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "docker-compose.yaml"
        )
        if not os.path.exists(compose):
            self.skipTest("docker-compose.yaml not in expected path")
        with open(compose) as f:
            text = f.read()
        m = re.search(
            r"image:\s*kibble\.apps\.blindhub\.ca/cobdfamily/hummingbird:(\S+)",
            text,
        )
        self.assertIsNotNone(m, msg="hummingbird image line not found")
        tag = m.group(1)
        self.assertNotEqual(tag, "", msg="hummingbird tag is empty")


if __name__ == "__main__":
    unittest.main(verbosity=2)
