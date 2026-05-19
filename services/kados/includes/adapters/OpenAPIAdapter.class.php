<?php

/*
 * Copyright (C) 2013 Kolibre
 * This file is part of Kolibre-KADOS.
 * Kolibre-KADOS is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation, either version 2.1 of the License, or
 * at your option any later version.
 *
 * Kolibre-KADOS is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with Kolibre-KADOS. If not, see <http://www.gnu.org/licenses/>.
 */

require_once(dirname(__FILE__) . '/Adapter.class.php');

/**
 * OpenAPI adapter
 *
 * A thin HTTP proxy adapter. Every method forwards to
 *   POST {baseUrl}/protocols/kados/v1/methods/{methodName}/
 * with a JSON body:
 *   { "method": "<methodName>", "data": { ...args } }
 * and expects a JSON response:
 *   { "data": <value matching the method's return contract> }
 *
 * The value at response.data is returned to the caller verbatim.
 */
class OpenAPIAdapter extends Adapter
{
    private $baseUrl = null;
    private $apiKey = null;
    private $sessionToken = null;
    private $timeout = 30;

    /**
     * Construct the adapter.
     *
     * The base URL and API key are resolved in this order:
     *   1. Explicit constructor argument (if non-empty string).
     *   2. Environment variable OPENAPI_BASE_URL / OPENAPI_API_KEY.
     *
     * OPENAPI_BASE_URL is required; if neither source yields a
     * value, an AdapterException is thrown. OPENAPI_API_KEY is
     * optional.
     *
     * @throws AdapterException when no base URL can be resolved
     */
    public function __construct($baseUrl = null, $apiKey = null)
    {
        $resolvedBaseUrl = null;
        if (is_string($baseUrl) && $baseUrl !== '')
        {
            $resolvedBaseUrl = $baseUrl;
        }
        else
        {
            $envBaseUrl = getenv('OPENAPI_BASE_URL');
            if (is_string($envBaseUrl) && $envBaseUrl !== '')
            {
                $resolvedBaseUrl = $envBaseUrl;
            }
        }

        if ($resolvedBaseUrl === null)
        {
            throw new AdapterException('OpenAPIAdapter: base URL not set (pass via constructor or set OPENAPI_BASE_URL)');
        }
        $this->baseUrl = rtrim($resolvedBaseUrl, '/');

        if (is_string($apiKey) && $apiKey !== '')
        {
            $this->apiKey = $apiKey;
        }
        else
        {
            $envApiKey = getenv('OPENAPI_API_KEY');
            if (is_string($envApiKey) && $envApiKey !== '')
            {
                $this->apiKey = $envApiKey;
            }
        }
    }

    public function setApiKey($apiKey)
    {
        $this->apiKey = $apiKey;
    }

    public function setBaseUrl($baseUrl)
    {
        $this->baseUrl = rtrim($baseUrl, '/');
    }

    /**
     * Preserve auth state across PHP session serialization.
     *
     * KADOS stores the adapter in $_SESSION between SOAP requests,
     * so the session token must survive serialize/unserialize.
     */
    public function __sleep()
    {
        return array(
            'baseUrl',
            'apiKey',
            'sessionToken',
            'timeout',
            'user',
            'protocolVersion',
            'deviceManufaturer',
            'deviceModel',
            'deviceSerial',
            'deviceVersion',
        );
    }

    /**
     * Forward a call to the OpenAPI backend and return response.data.
     *
     * @param string $methodName The adapter method name
     * @param array  $args       Named arguments for the method
     * @return mixed The value of response.data
     * @throws AdapterException on HTTP, transport or decoding failure
     */
    protected function callAPI($methodName, array $args = array())
    {
        $url = $this->baseUrl . '/protocols/kados/v1/methods/' . rawurlencode($methodName) . '/';
        $payload = json_encode(array(
            'method' => $methodName,
            'data'   => (object) $args,
        ));

        if ($payload === false)
        {
            throw new AdapterException('Failed to encode request payload for ' . $methodName);
        }

        $ch = curl_init($url);
        if ($ch === false)
        {
            throw new AdapterException('Failed to initialize HTTP client');
        }

        $headers = array(
            'Content-Type: application/json',
            'Accept: application/json',
        );
        if (!empty($this->apiKey))
        {
            $headers[] = 'X-API-Key: ' . $this->apiKey;
        }
        if (!empty($this->sessionToken))
        {
            $headers[] = 'Authorization: Session ' . $this->sessionToken;
        }

        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, $this->timeout);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);

        $body = curl_exec($ch);
        if ($body === false)
        {
            $err = curl_error($ch);
            curl_close($ch);
            throw new AdapterException('HTTP request to ' . $url . ' failed: ' . $err);
        }

        $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($status < 200 || $status >= 300)
        {
            throw new AdapterException('HTTP ' . $status . ' from ' . $url . ': ' . $body);
        }

        $decoded = json_decode($body, true);
        if (!is_array($decoded) || !array_key_exists('data', $decoded))
        {
            throw new AdapterException('Malformed response from ' . $url . ': expected object with "data" key');
        }

        return $decoded['data'];
    }

    // -----------------------------------------------------------------
    // Optional hooks (still forwarded so the backend can observe them)
    // -----------------------------------------------------------------

    public function setProtocolVersion($version)
    {
        $this->protocolVersion = $version;
        $this->callAPI('setProtocolVersion', array('version' => $version));
    }

    public function logSoapRequestAndResponse($request, $response, $timestamp, $ip)
    {
        $this->callAPI('logSoapRequestAndResponse', array(
            'request'   => $request,
            'response'  => $response,
            'timestamp' => $timestamp,
            'ip'        => $ip,
        ));
    }

    public function startSession()
    {
        // Anonymous on hummingbird's side -- safe to call before
        // authenticate(). The session lifecycle on the OpenAPI
        // side is owned by ``authenticate`` (which mints the
        // sessionToken); ``startSession`` here is a no-op-shaped
        // RPC hook the KADOS framework invokes on every request
        // and which hummingbird returns ``{"data": true}`` for
        // regardless of auth state.
        return $this->callAPI('startSession', array());
    }

    public function stopSession()
    {
        // KADOS's DaisyOnlineService.sessionHandle() calls
        // sessionDestroy() (and so this method) at the *start*
        // of every SOAP request, before the new logOn handshake
        // runs. On a fresh PHP process there is no prior token,
        // and hummingbird's v0.7+ KADOS router requires
        // Authorization: Session for session-scoped methods --
        // calling stopSession without a token returns 401, which
        // an earlier version of this adapter let bubble up as an
        // AdapterException, killing the SOAP envelope with a PHP
        // fatal error before any of logOn's actual work ran.
        //
        // Guard: when we have no session, there is nothing to
        // stop. Idempotency-correct and matches hummingbird's
        // current contract.
        if (empty($this->sessionToken))
        {
            return null;
        }
        $result = $this->callAPI('stopSession', array());
        $this->sessionToken = null;
        return $result;
    }

    // -----------------------------------------------------------------
    // Required abstract methods
    // -----------------------------------------------------------------

    public function label($id, $type, $language = null)
    {
        return $this->callAPI('label', array(
            'id'       => $id,
            'type'     => $type,
            'language' => $language,
        ));
    }

    /**
     * Authenticate and establish a session.
     *
     * The backend MUST respond with:
     *   { "data": { "authenticated": bool,
     *               "sessionToken": "<string>" (when authenticated) } }
     * A bare boolean { "data": true|false } is also accepted for
     * backends that do not issue tokens, though the adapter will
     * then remain unauthenticated for user-scoped calls.
     *
     * The token is retained privately and injected as
     *   Authorization: Session <token>
     * on every subsequent request.
     */
    public function authenticate($username, $password)
    {
        $this->sessionToken = null;

        $result = $this->callAPI('authenticate', array(
            'username'           => $username,
            'password'           => $password,
            'deviceManufaturer'  => $this->deviceManufaturer,
            'deviceModel'        => $this->deviceModel,
            'deviceSerial'       => $this->deviceSerial,
            'deviceVersion'      => $this->deviceVersion,
            'protocolVersion'    => $this->protocolVersion,
        ));

        if (is_array($result))
        {
            if (!empty($result['sessionToken']))
            {
                $this->sessionToken = $result['sessionToken'];
            }
            if (array_key_exists('user', $result))
            {
                $this->user = $result['user'];
            }
            return !empty($result['authenticated']);
        }

        return (bool) $result;
    }

    public function contentListExists($list)
    {
        return $this->callAPI('contentListExists', array(
            'list' => $list,
        ));
    }

    public function contentList($list, $contentFormats = null, $protectionFormats = null, $mimeTypes = null)
    {
        return $this->callAPI('contentList', array(
            'list'              => $list,
            'contentFormats'    => $contentFormats,
            'protectionFormats' => $protectionFormats,
            'mimeTypes'         => $mimeTypes,
        ));
    }

    public function contentLastModifiedDate($contentId)
    {
        return $this->callAPI('contentLastModifiedDate', array(
            'contentId' => $contentId,
        ));
    }

    public function contentAccessDate($contentId)
    {
        return $this->callAPI('contentAccessDate', array(
            'contentId' => $contentId,
        ));
    }

    public function contentAccessMethod($contentId)
    {
        return $this->callAPI('contentAccessMethod', array(
            'contentId' => $contentId,
        ));
    }

    public function contentAccessState($contentId, $state)
    {
        return $this->callAPI('contentAccessState', array(
            'contentId' => $contentId,
            'state'     => $state,
        ));
    }

    public function contentExists($contentId)
    {
        return $this->callAPI('contentExists', array(
            'contentId' => $contentId,
        ));
    }

    public function contentAccessible($contentId)
    {
        return $this->callAPI('contentAccessible', array(
            'contentId' => $contentId,
        ));
    }

    public function contentSample($contentId)
    {
        return $this->callAPI('contentSample', array(
            'contentId' => $contentId,
        ));
    }

    public function contentCategory($contentId)
    {
        return $this->callAPI('contentCategory', array(
            'contentId' => $contentId,
        ));
    }

    public function contentSubCategory($contentId)
    {
        return $this->callAPI('contentSubCategory', array(
            'contentId' => $contentId,
        ));
    }

    public function contentReturnDate($contentId)
    {
        return $this->callAPI('contentReturnDate', array(
            'contentId' => $contentId,
        ));
    }

    public function contentMetadata($contentId)
    {
        return $this->callAPI('contentMetadata', array(
            'contentId' => $contentId,
        ));
    }

    public function contentIssuable($contentId)
    {
        return $this->callAPI('contentIssuable', array(
            'contentId' => $contentId,
        ));
    }

    public function contentIssue($contentId)
    {
        return $this->callAPI('contentIssue', array(
            'contentId' => $contentId,
        ));
    }

    public function contentAddBookshelf($contentId)
    {
        return $this->callAPI('contentAddBookshelf', array(
            'contentId' => $contentId,
        ));
    }

    public function contentResources($contentId, $accessMethod = null)
    {
        return $this->callAPI('contentResources', array(
            'contentId'    => $contentId,
            'accessMethod' => $accessMethod,
        ));
    }

    public function contentReturnable($contentId)
    {
        return $this->callAPI('contentReturnable', array(
            'contentId' => $contentId,
        ));
    }

    public function contentReturn($contentId)
    {
        return $this->callAPI('contentReturn', array(
            'contentId' => $contentId,
        ));
    }

    // -----------------------------------------------------------------
    // Announcements
    // -----------------------------------------------------------------

    public function announcements()
    {
        return $this->callAPI('announcements', array());
    }

    public function announcementInfo($announcementId)
    {
        return $this->callAPI('announcementInfo', array(
            'announcementId' => $announcementId,
        ));
    }

    public function announcementExists($announcementId)
    {
        return $this->callAPI('announcementExists', array(
            'announcementId' => $announcementId,
        ));
    }

    public function announcementRead($announcementId)
    {
        return $this->callAPI('announcementRead', array(
            'announcementId' => $announcementId,
        ));
    }

    // -----------------------------------------------------------------
    // Bookmarks
    // -----------------------------------------------------------------

    public function setBookmarks($contentId, $bookmark, $action = null, $lastModifiedDate = null)
    {
        return $this->callAPI('setBookmarks', array(
            'contentId'        => $contentId,
            'bookmark'         => $bookmark,
            'action'           => $action,
            'lastModifiedDate' => $lastModifiedDate,
        ));
    }

    public function getBookmarks($contentId, $action = null)
    {
        return $this->callAPI('getBookmarks', array(
            'contentId' => $contentId,
            'action'    => $action,
        ));
    }

    // -----------------------------------------------------------------
    // Dynamic menus
    // -----------------------------------------------------------------

    public function menuDefault()
    {
        return $this->callAPI('menuDefault', array());
    }

    public function menuSearch()
    {
        return $this->callAPI('menuSearch', array());
    }

    public function menuBack()
    {
        return $this->callAPI('menuBack', array());
    }

    public function menuNext($responses)
    {
        return $this->callAPI('menuNext', array(
            'responses' => $responses,
        ));
    }

    public function menuContentQuestion($contentId)
    {
        return $this->callAPI('menuContentQuestion', array(
            'contentId' => $contentId,
        ));
    }

    // -----------------------------------------------------------------
    // PDTB2 key exchange
    // -----------------------------------------------------------------

    public function requestedKey($name)
    {
        return $this->callAPI('requestedKey', array(
            'name' => $name,
        ));
    }

    public function clientKey($name)
    {
        return $this->callAPI('clientKey', array(
            'name' => $name,
        ));
    }

    public function issuerInfo()
    {
        return $this->callAPI('issuerInfo', array());
    }

    // -----------------------------------------------------------------
    // Credentials and terms of service
    // -----------------------------------------------------------------

    public function userCredentials($manufacturer, $model, $serialNumber, $version)
    {
        return $this->callAPI('userCredentials', array(
            'manufacturer' => $manufacturer,
            'model'        => $model,
            'serialNumber' => $serialNumber,
            'version'      => $version,
        ));
    }

    public function termsOfService()
    {
        return $this->callAPI('termsOfService', array());
    }

    public function termsOfServiceAccept()
    {
        return $this->callAPI('termsOfServiceAccept', array());
    }

    public function termsOfServiceAccepted()
    {
        return $this->callAPI('termsOfServiceAccepted', array());
    }
}

?>