#!/usr/bin/env python3
"""DODP v2 logOn test harness for the KADOS server.

Sends a raw SOAP logOn envelope to the running KADOS
instance (the one brought up by the docker-compose at
include/adapter/docker-compose.yaml) and asserts the
protocol-level behavior:

  * WSDL is served
  * Valid credentials return a logOnResponse
  * Invalid credentials return a SOAP Fault

Assumes an OpenAPI backend is reachable by the KADOS
container. For fully offline runs, start the sibling
mock_backend.py and point OPENAPI_BASE_URL at it; see
this directory's README.md.

Env vars:
  KADOS_SERVICE_URL  default http://localhost:8080/service.php
  KADOS_USERNAME     default testuser
  KADOS_PASSWORD     default testpass

Run:
  python3 -m unittest test_logon.py
"""

import os
import unittest
import xml.etree.ElementTree as ET

import requests


SERVICE_URL = os.environ.get(
    "KADOS_SERVICE_URL", "http://localhost:8080/service.php"
)
USERNAME = os.environ.get("KADOS_USERNAME", "testuser")
PASSWORD = os.environ.get("KADOS_PASSWORD", "testpass")

NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "d": "http://www.daisy.org/ns/daisy-online/",
}

SOAP_ACTION = '"urn:http://www.daisy.org/ns/daisy-online/logOn"'

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


def post_logon(url, username, password, timeout=30):
    body = LOGON_ENVELOPE.format(username=username, password=password)
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": SOAP_ACTION,
    }
    return requests.post(
        url, data=body.encode("utf-8"), headers=headers, timeout=timeout
    )


class DODPv2LogOnTests(unittest.TestCase):
    def test_wsdl_available(self):
        resp = requests.get(SERVICE_URL + "?wsdl", timeout=30)
        self.assertEqual(resp.status_code, 200, msg=resp.text[:500])
        self.assertIn(
            "http://www.daisy.org/ns/daisy-online/",
            resp.text,
            msg="WSDL missing expected targetNamespace",
        )

    def test_logon_with_valid_credentials_returns_service_attrs(self):
        resp = post_logon(SERVICE_URL, USERNAME, PASSWORD)
        self.assertEqual(resp.status_code, 200, msg=resp.text[:1000])

        root = ET.fromstring(resp.text)
        fault = root.find(".//s:Fault", NS)
        self.assertIsNone(
            fault,
            msg="Expected successful logOn, got SOAP Fault:\n" + resp.text,
        )

        logon_resp = root.find(".//d:logOnResponse", NS)
        self.assertIsNotNone(
            logon_resp,
            msg="Missing logOnResponse in body:\n" + resp.text,
        )

    def test_logon_with_invalid_credentials_returns_fault(self):
        resp = post_logon(SERVICE_URL, USERNAME, "definitely-wrong")
        # PHP SoapServer returns HTTP 500 for Faults
        self.assertIn(
            resp.status_code, (200, 500), msg=resp.text[:1000]
        )

        root = ET.fromstring(resp.text)
        fault = root.find(".//s:Fault", NS)
        self.assertIsNotNone(
            fault,
            msg="Expected SOAP Fault for bad credentials:\n" + resp.text,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
