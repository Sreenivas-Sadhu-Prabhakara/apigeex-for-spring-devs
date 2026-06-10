# 4.3 — Implementing FAPI I: PAR, request objects & client auth

!!! bottomline "Bottom line"
    FAPI Advanced forbids the old habit of dangling authorization parameters in a browser redirect. Instead the client **pushes** a signed authorization request to a back-channel **PAR** endpoint, authenticating itself with `private_key_jwt` or **mTLS**, and gets back an opaque `request_uri`. By the end you can build that `/par` endpoint in Apigee — verifying the signed **request object** with **VerifyJWT**, verifying the **client assertion** with another **VerifyJWT**, storing the request, and minting a `request_uri` — then have `/authorize` consume it. This is the server-side enforcement a Spring FAPI client trusts you to do.

## Why this exists

In plain OAuth the authorization request is a query string: `response_type`, `scope`, `redirect_uri`, `state` — all visible in the browser, all tamperable, all logged in someone's proxy. FAPI Advanced closes that gap two ways. First, **PAR** (RFC 9126) moves the whole request off the front channel: the client `POST`s it directly to the authorization server over TLS, server-to-server, and `/authorize` then carries only a one-time `request_uri` reference. Nothing sensitive rides in the browser. Second, the pushed request isn't a form post — it's a **signed JWS request object** (JAR, RFC 9101) whose claims *are* the authorization parameters, so the AS can prove the client authored them and they weren't altered in flight.

The second half of this session is **client authentication**. A confidential FAPI client never sends a shared `client_secret`. It proves identity with either `private_key_jwt` — a short-lived JWT (`client_assertion`) signed by the client's private key, which you verify against its registered public key — or **mutual TLS**, where the client presents an OB transport certificate you validate against the truststore from 4.1. Both bind the request to a key the attacker doesn't have.

You are implementing the *server* a Spring `RegisteredClient` configured for `private_key_jwt` or mTLS will talk to. Spring Security can produce these requests for you; FAPI makes the **server's verification** non-negotiable, and that verification is what lives in Apigee.

!!! bridge "Spring Boot bridge"
    On the Spring side, a FAPI-aware client mostly *produces* these artefacts — you'd configure a `RegisteredClient` with `ClientAuthenticationMethod.PRIVATE_KEY_JWT`, a `JwtClientAssertionDecoderFactory`, and a `JWK` source. Apigee is the **other end**: the strict verifier. Map it:

    | Spring (client side) | Apigee X (server side) |
    |---|---|
    | `OAuth2AuthorizationRequest` builder | the **request object** claims the client signs |
    | `NimbusJwtClientAuthenticationParametersConverter` building `client_assertion` | **VerifyJWT** on `client_assertion` (`private_key_jwt`) |
    | `JwtDecoder` with a remote JWK set | **VerifyJWT** with `<JWKS uri=…>` = the client's `jwks_uri` |
    | `client.ssl.*` / `RestTemplate` truststore | **SSLInfo** mTLS + truststore from 4.1 |

    The crucial inversion: in Spring you mostly *sign and send*. Here you *receive and verify*. A FAPI server that "trusts but doesn't verify" the signature is the whole failure this session prevents.

!!! breaks "Where the analogy breaks"
    Spring's `@Valid` and bean validation check **shape** — is `redirect_uri` present, is `scope` non-empty. FAPI requires **cryptographic** validation: the request object must be a JWS signed with `PS256` or `ES256` (never `none`, never `HS256` with a shared secret), issued by the client (`iss` == `client_id`), audienced to *you* (`aud` == the AS issuer), and unexpired. None of that is shape — it's signature, issuer binding, and freshness. A request that passes every `@Valid` rule and still has a forged signature must be rejected, and only **VerifyJWT** — not a schema check — catches it. Likewise, mTLS client auth has no Spring-controller analogue at all: the proof happens during the TLS handshake, before any policy or filter runs.

## The concept

The PAR flow is a back-channel push followed by a front-channel reference. The client signs its authorization request, authenticates itself, and pushes both to `/par`; you verify, persist, and hand back a `request_uri`; the browser then hits `/authorize?request_uri=…` carrying nothing sensitive.

```widget
{
  "type": "sequence",
  "title": "PAR: push a signed request, get back a request_uri",
  "actors": [
    {"id": "c", "label": "FAPI client"},
    {"id": "par", "label": "/par (Apigee)"},
    {"id": "az", "label": "/authorize (Apigee)"}
  ],
  "steps": [
    {"from": "c", "to": "par", "label": "POST /par  request=<signed JWS>  client_assertion=<JWS>", "note": "Back channel, mTLS. request is the signed request object (JAR); client_assertion authenticates the client (private_key_jwt)."},
    {"from": "par", "to": "par", "label": "VerifyJWT(request)", "note": "Signature PS256/ES256, iss==client_id, aud==AS issuer, exp valid. Tampered → fault, no request_uri issued."},
    {"from": "par", "to": "par", "label": "VerifyJWT(client_assertion)", "note": "Verify against the client's jwks_uri; sub==iss==client_id; aud==/par. This is client authentication."},
    {"from": "par", "to": "par", "label": "store request, mint request_uri", "note": "Persist the verified params; return an opaque, single-use, short-lived urn:ietf:params:oauth:request_uri:… + expires_in."},
    {"from": "par", "to": "c", "kind": "return", "label": "201  { request_uri, expires_in: 90 }", "note": "The opaque handle. Nothing sensitive will ride the browser."},
    {"from": "c", "to": "az", "label": "GET /authorize?client_id=…&request_uri=…", "note": "Front channel now carries only the reference. /authorize loads the stored, already-verified request."},
    {"from": "az", "to": "c", "kind": "return", "label": "302 → redirect_uri?code=…", "note": "User authenticates/consents; AS returns the authorization code against the pushed request."}
  ]
}
```

The two **VerifyJWT** policies do different jobs. One proves the *request* is authentic (JAR); the other proves the *client* is authentic (`private_key_jwt`). A FAPI `/par` needs both — or mTLS standing in for the second.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — build a verifying /par endpoint, then consume the request_uri

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; the OB truststore reference from 4.1 (call it `ob-truststore`); a registered app (3.2) whose `jwks_uri` you can reach; a proxy named `fapi-as` with `/par` and `/authorize` conditional flows.

**1. Require mTLS at the edge** so the client transport cert is captured for client auth. In the ProxyEndpoint, before any flow runs:

```xml
<!-- SSLInfo on the virtual host / ProxyEndpoint: request and validate the client cert -->
<SSLInfo>
  <Enabled>true</Enabled>
  <ClientAuthEnabled>true</ClientAuthEnabled>
  <TrustStore>ref://ob-truststore</TrustStore>
  <IgnoreValidationErrors>false</IgnoreValidationErrors>
</SSLInfo>
```

**2. Verify the signed request object** in the `/par` request flow. The client's public keys come from its registered `jwks_uri`; `id` pins which client we expect:

```xml
<VerifyJWT name="VJWT-RequestObject">
  <Algorithm>PS256</Algorithm>
  <Source>request.formparam.request</Source>
  <PublicKey>
    <JWKS uri="https://directory.openbanking.example/{client_id}/jwks.json"/>
  </PublicKey>
  <Issuer ref="request.formparam.client_id"/>
  <Audience>https://{organization}-{environment}.apigee.net/fapi-as</Audience>
  <AdditionalClaims>
    <Claim name="response_type" ref="request.formparam.response_type" required="true"/>
  </AdditionalClaims>
</VerifyJWT>
```

A bad signature, a wrong `iss`, a missing/expired `exp`, or `alg:none` makes this policy raise `steps.jwt.FailedToDecode` / `steps.jwt.InvalidSignature` and the flow stops here — no `request_uri` is ever issued.

**3. Authenticate the client with `private_key_jwt`.** A second VerifyJWT over `client_assertion`, asserting `client_assertion_type` and binding `sub == iss == client_id`, audienced to `/par`:

```xml
<VerifyJWT name="VJWT-ClientAssertion">
  <Algorithm>PS256</Algorithm>
  <Source>request.formparam.client_assertion</Source>
  <PublicKey>
    <JWKS uri="https://directory.openbanking.example/{client_id}/jwks.json"/>
  </PublicKey>
  <Subject ref="request.formparam.client_id"/>
  <Issuer ref="request.formparam.client_id"/>
  <Audience>https://{organization}-{environment}.apigee.net/fapi-as/par</Audience>
</VerifyJWT>
```

(If you authenticate by **mTLS** instead, this step is the SSLInfo check from step 1 plus matching the cert's subject/`org_id` to the registered client — no `client_assertion` at all. FAPI allows either; pick one per client.)

**4. Mint and store the `request_uri`.** Generate an opaque handle, cache the verified params against it, and return it. Persist with a short TTL so it can't be replayed:

```xml
<AssignMessage name="AM-MintRequestUri">
  <AssignVariable>
    <Name>par.request_uri</Name>
    <Template>urn:ietf:params:oauth:request_uri:{createUuid()}</Template>
  </AssignVariable>
  <Set>
    <Payload contentType="application/json">{"request_uri":"{par.request_uri}","expires_in":90}</Payload>
    <StatusCode>201</StatusCode>
  </Set>
</AssignMessage>
```

```xml
<!-- Cache the verified request object payload keyed by the request_uri, TTL 90s -->
<PopulateCache name="PC-StorePar">
  <CacheKey><KeyFragment ref="par.request_uri"/></CacheKey>
  <Source>jwt.VJWT-RequestObject.payload-json</Source>
  <ExpirySettings><TimeoutInSec>90</TimeoutInSec></ExpirySettings>
</PopulateCache>
```

**5. Consume it at `/authorize`.** The front-channel request now carries only `client_id` + `request_uri`; load the cached, already-verified params (a cache miss = expired/unknown handle = reject):

```xml
<LookupCache name="LC-LoadPar">
  <CacheKey><KeyFragment ref="request.queryparam.request_uri"/></CacheKey>
  <AssignTo>par.loaded</AssignTo>
</LookupCache>
```

**6. Deploy and push a real PAR over mTLS:**

```bash
apigeecli apis create bundle --name fapi-as --proxy-folder ./fapi-as/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name fapi-as --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

# REQ = signed request object (PS256), CA = client_assertion (PS256) — produce these with your client key
curl -s --cert client-transport.pem --key client-transport.key \
  -X POST "https://$RUNTIME_HOST/fapi-as/par" \
  -d "client_id=acme-budgeting" \
  -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" \
  -d "client_assertion=$CA" \
  --data-urlencode "request=$REQ" | jq .
# → { "request_uri": "urn:ietf:params:oauth:request_uri:…", "expires_in": 90 }
```

**What success looks like:** a valid PAR returns `201` with a `request_uri` and `expires_in`, and `/authorize?client_id=…&request_uri=…` loads it and proceeds to a code. Re-run with a **tampered** request object (flip one base64url char of the JWS payload) and the call fails at `VJWT-RequestObject` with `steps.jwt.InvalidSignature` and **no** `request_uri` — exactly the forgery a `@Valid` check would have waved through.
</div>

## Verify it

Open a debug session and confirm both VerifyJWT policies executed and populated their context. After a good PAR you should see `jwt.VJWT-RequestObject.valid = true`, `jwt.VJWT-RequestObject.claim.iss` equal to your `client_id`, and a matching `jwt.VJWT-ClientAssertion.valid = true`. The minted `par.request_uri` should appear in the `201` body and as a cache entry. On the front channel, `LC-LoadPar` should report a hit; let the 90-second TTL lapse and retry to confirm a miss → rejection. In Trace, the mTLS handshake variables `tls.client.s.dn` / `client.ssl.cert.*` should carry the OB transport cert's distinguished name, proving the truststore from 4.1 accepted it.

!!! failure "Common failure modes"
    - **Accepting `alg:none` or `HS256`.** If VerifyJWT has no `<Algorithm>` pinned to `PS256`/`ES256`, a forged unsigned request object can slip through. Symptom: a request with a stripped signature is accepted and a `request_uri` is issued. Pin the algorithm explicitly.
    - **Not binding the audience.** A `client_assertion` minted for the `/token` endpoint replayed at `/par`, or a request object audienced to a different AS. Symptom: cross-endpoint token replay passes verification. Set `<Audience>` to the exact endpoint URL on each VerifyJWT.
    - **`iss`/`sub` not pinned to `client_id`.** A valid JWS signed by *some* registered client passes as a *different* client. Symptom: client A's assertion authorizes client B. Use `<Issuer ref>`/`<Subject ref>` tied to the submitted `client_id`.
    - **`request_uri` reused or long-lived.** No TTL, or no single-use eviction. Symptom: the same `request_uri` drives multiple `/authorize` calls. Cache with a 60–90s TTL and evict on first consumption.
    - **mTLS not actually enforced.** `ClientAuthEnabled` false, or the proxy reachable on a non-mTLS host. Symptom: a PAR succeeds with no client cert presented. Require the cert at the edge and validate it against the 4.1 truststore.

!!! stretch "Stretch goal"
    Send a tampered request object through a live Trace and capture the **exact** fault: which policy raised it (`VJWT-RequestObject`), the fault name (`steps.jwt.InvalidSignature` vs `steps.jwt.FailedToDecode`), and the HTTP status your FaultRules return to the client. Then craft a *valid* `client_assertion` audienced to `/token` and replay it at `/par`; confirm the audience check rejects it, and note how that single `<Audience>` line stops a whole class of cross-endpoint replay.

## Recap & next

You built the FAPI front door: an mTLS-protected `/par` endpoint that **verifies** a signed request object and a `private_key_jwt` client assertion with two distinct **VerifyJWT** policies, persists the verified request under a short-lived single-use `request_uri`, and an `/authorize` that consumes it — moving every sensitive parameter off the browser and proving both the request and the client are cryptographically authentic. This is the strict server a Spring FAPI client is built to talk to.

**Next — 4.4:** the token half. You'll issue **certificate-bound access tokens** — stamping the client cert thumbprint into the token's `cnf.x5t#S256` claim at `/token`, enforcing that binding on every `/accounts` call so a stolen token is useless without the cert, and exposing an RFC 7662 **introspection** endpoint that reports `active`, `scope`, and `cnf`.
