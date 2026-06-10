# 4.4 — Implementing FAPI II: mTLS-bound tokens & introspection

!!! bottomline "Bottom line"
    A plain bearer token is a bearer instrument: whoever holds it, uses it. FAPI Advanced closes that gap with **certificate-bound tokens** (RFC 8705) — at `/token` you stamp the client cert's SHA-256 thumbprint into the token's `cnf.x5t#S256` claim, and on **every** resource call you re-check that the cert on the wire still matches. A stolen token presented from a different client cert is rejected. By the end you can mint a bound token, enforce the binding on `/accounts`, and expose an RFC 7662 **introspection** endpoint that reports `active`, `scope`, and `cnf`.

## Why this exists

The whole point of OAuth is that a resource server accepts a token without re-authenticating the client. That convenience is also the weakness: a token stolen from a log, a proxy, or a compromised client works perfectly for the thief, because nothing ties it to *who* it was issued to. In open banking that means a leaked AISP token can drain account data until it expires. FAPI Advanced mandates **sender-constrained** tokens to remove that risk.

The mechanism is **mTLS-bound tokens**. When the client requests a token over a mutual-TLS connection, the AS records the SHA-256 thumbprint of the client's certificate and embeds it in the token as the confirmation claim `cnf` with member `x5t#S256`. From then on, every protected call must *also* be over mTLS with the *same* client cert. The resource server computes the thumbprint of the presented cert and compares it to `cnf.x5t#S256`. Match → proceed; mismatch → `401`. The token is no longer a bearer instrument; it's bound to a private key the attacker doesn't have.

The second piece is **token introspection** (RFC 7662). Resource servers — yours and, in OB, separately deployed account/payment APIs — need a way to ask "is this token still active, and what's it good for?" A standard `/introspect` endpoint returns `active`, `scope`, `exp`, and crucially the `cnf` claim, so a downstream enforcer can perform the same binding check.

!!! bridge "Spring Boot bridge"
    A vanilla Spring resource server (`oauth2ResourceServer().jwt()` or `.opaqueToken()`) validates the token's signature/introspection result and stops there — it never asks *which client* is on the connection. That's exactly the stolen-token gap FAPI closes. Map it:

    | Spring resource server | Apigee X (FAPI) |
    |---|---|
    | `JwtDecoder` validates signature + `exp` | **VerifyJWT** validates the access token |
    | (no equivalent) | compare `cnf.x5t#S256` to the presented client cert thumbprint |
    | `NimbusOpaqueTokenIntrospector` → `/introspect` | your **RFC 7662** introspection proxy returning `active`/`scope`/`cnf` |
    | `server.ssl.client-auth=need` | **SSLInfo** `ClientAuthEnabled` + 4.1 truststore |

    Spring Security *can* do mTLS client auth (`X509` filter) and you can write a custom validator for the binding — but FAPI requires the binding to be enforced on every protected call, and that enforcement is what lives at the gateway here.

!!! breaks "Where the analogy breaks"
    A Spring resource server treats the token and the transport as independent layers — TLS terminates, then a filter inspects a self-contained bearer token, and the two never compare notes. Certificate binding deliberately couples them: the token is meaningless unless re-presented over the same key-pair that obtained it. There's no single Spring annotation for "this token is only valid from this client certificate." You'd have to reach the TLS-layer cert (often lost at a load balancer that terminates TLS upstream), recompute its thumbprint, and reject on mismatch by hand. The gateway sees both the raw client cert and the token in one place, which is precisely why the binding check belongs at the edge rather than in the downstream service.

## The concept

Binding has two moments: **stamp** at issuance, **check** at use. At `/token`, over mTLS, the AS computes the cert thumbprint and writes it into the token. At every resource call, also over mTLS, the gateway recomputes the presented cert's thumbprint and compares.

```widget
{
  "type": "sequence",
  "title": "Certificate-bound token: stamp once, check every call",
  "actors": [
    {"id": "c", "label": "FAPI client (cert A)"},
    {"id": "t", "label": "/token (Apigee)"},
    {"id": "r", "label": "/accounts (Apigee)"}
  ],
  "steps": [
    {"from": "c", "to": "t", "label": "POST /token  (mTLS, cert A)  grant=client_credentials", "note": "Connection is mutual-TLS; gateway captures cert A from the handshake."},
    {"from": "t", "to": "t", "label": "thumbprint(cert A) → cnf.x5t#S256", "note": "SHA-256 of the DER cert, base64url. GenerateJWT stamps it into the access token's cnf claim."},
    {"from": "t", "to": "c", "kind": "return", "label": "200  { access_token (cnf.x5t#S256=A), token_type: Bearer }", "note": "Token is now sender-constrained to cert A."},
    {"from": "c", "to": "r", "label": "GET /accounts  (mTLS, cert A)  Authorization: Bearer …", "note": "Same client, same cert A, presents the bound token."},
    {"from": "r", "to": "r", "label": "thumbprint(presented cert) == token.cnf.x5t#S256 ?", "note": "VerifyJWT reads cnf; gateway recomputes the live cert thumbprint and compares."},
    {"from": "r", "to": "c", "kind": "return", "label": "200 (cert A matches)  /  401 (cert B → mismatch)", "note": "A token stolen and replayed from cert B fails the binding — bearer theft neutralised."}
  ]
}
```

!!! pitfall "Watch out"
    The binding is only real if you re-check `cnf.x5t#S256` against the **presented** client cert on *every* resource call — not just at issuance. Stamp `cnf` at `/token` but skip the comparison on `/accounts` and the binding is purely decorative: a stolen bearer token still works from any cert. The check must run on every protected flow, no exceptions.

Introspection exposes the same facts to other resource servers: a `POST /introspect` returns `active`, `scope`, `exp`, and the `cnf` object so a downstream enforcer can run the identical thumbprint comparison.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — stamp cnf at /token, enforce it on /accounts, expose /introspect

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; the mTLS edge + OB truststore (`ob-truststore`) from 4.1/4.3; a `fapi-as` proxy serving `/token`, `/accounts`, and `/introspect`. Two distinct client certs (`certA`, `certB`) to prove the binding.

**1. Capture the client cert thumbprint at `/token`.** Apigee exposes the presented cert; compute the FAPI thumbprint (base64url SHA-256 of the DER):

```xml
<AssignMessage name="AM-CertThumbprint">
  <AssignVariable>
    <Name>fapi.cnf.x5t</Name>
    <!-- Apigee surfaces the SHA-256 fingerprint of the client cert from the mTLS handshake -->
    <Ref>client.ssl.cert.fingerprint.sha256.base64url</Ref>
  </AssignVariable>
</AssignMessage>
```

**2. Mint a bound access token** with **GenerateJWT**, writing the thumbprint into the `cnf` claim as `x5t#S256`:

```xml
<GenerateJWT name="GJWT-BoundToken">
  <Algorithm>PS256</Algorithm>
  <PrivateKey>
    <Keystore ref="as-signing-keystore"/>
    <Alias>as-key</Alias>
  </PrivateKey>
  <Issuer>https://{organization}-{environment}.apigee.net/fapi-as</Issuer>
  <Audience ref="request.formparam.resource"/>
  <Subject ref="client_id"/>
  <ExpiresIn>300s</ExpiresIn>
  <AdditionalClaims>
    <Claim name="scope" ref="request.formparam.scope"/>
    <Claim name="cnf" type="map">
      <Claim name="x5t#S256" ref="fapi.cnf.x5t"/>
    </Claim>
  </AdditionalClaims>
</GenerateJWT>
```

!!! pitfall "Watch out"
    The thumbprint must be a **base64url-encoded SHA-256 of the DER cert** on *both* sides of the comparison. Mixing base64 with base64url, comparing a colon-separated hex fingerprint, or grabbing the SHA-1 `x5t` instead of the SHA-256 `x5t#S256` all make cert A look like cert B and reject a legitimate caller. Confirm the exact variable Apigee surfaces before you trust it.

**3. Enforce the binding on `/accounts`.** First verify the token, then compare the cert that obtained it against the cert on *this* connection:

```xml
<VerifyJWT name="VJWT-AccessToken">
  <Algorithm>PS256</Algorithm>
  <Source>request.header.authorization.split(" ").1</Source>
  <PublicKey><JWKS uri="https://{organization}-{environment}.apigee.net/fapi-as/jwks"/></PublicKey>
  <Issuer>https://{organization}-{environment}.apigee.net/fapi-as</Issuer>
</VerifyJWT>
```

```xml
<!-- Reject unless the live client cert thumbprint equals the token's cnf.x5t#S256 -->
<RaiseFault name="RF-CertBindingMismatch">
  <Condition>jwt.VJWT-AccessToken.claim.cnf.x5t#S256 != client.ssl.cert.fingerprint.sha256.base64url</Condition>
  <FaultResponse>
    <Set>
      <StatusCode>401</StatusCode>
      <ReasonPhrase>Unauthorized</ReasonPhrase>
      <Headers>
        <Header name="WWW-Authenticate">Bearer error="invalid_token", error_description="certificate binding mismatch"</Header>
      </Headers>
    </Set>
  </FaultResponse>
</RaiseFault>
```

**4. Build the introspection endpoint** (RFC 7662). Verify the submitted token and echo back its status, scope, expiry, and `cnf`:

```xml
<AssignMessage name="AM-IntrospectionResponse">
  <Set>
    <Payload contentType="application/json">{
  "active": true,
  "scope": "{jwt.VJWT-AccessToken.claim.scope}",
  "client_id": "{jwt.VJWT-AccessToken.claim.sub}",
  "exp": {jwt.VJWT-AccessToken.claim.exp},
  "cnf": { "x5t#S256": "{jwt.VJWT-AccessToken.claim.cnf.x5t#S256}" }
}</Payload>
    <StatusCode>200</StatusCode>
  </Set>
</AssignMessage>
```

An invalid/expired token must instead return `{"active": false}` only — never leak claims for a dead token.

!!! pitfall "Watch out"
    `/introspect` must itself require client auth (mTLS or `private_key_jwt`) — an open introspection endpoint is a validity oracle anyone can use to test stolen or guessed tokens. Protect it exactly like the other FAPI endpoints; it is a resource server caller, not a public probe.

**5. Deploy, mint a bound token with cert A, and use it with cert A:**

```bash
apigeecli apis create bundle --name fapi-as --proxy-folder ./fapi-as/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name fapi-as --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

AT=$(curl -s --cert certA.pem --key certA.key \
  -X POST "https://$RUNTIME_HOST/fapi-as/token" \
  -d "grant_type=client_credentials" -d "scope=accounts" | jq -r .access_token)

# same cert A → 200
curl -s -o /dev/null -w "cert A: %{http_code}\n" --cert certA.pem --key certA.key \
  -H "Authorization: Bearer $AT" "https://$RUNTIME_HOST/fapi-as/accounts"
```

**6. Replay the same token from a different cert (the attack):**

```bash
# token stolen, replayed from cert B → 401 (binding mismatch)
curl -s -o /dev/null -w "cert B: %{http_code}\n" --cert certB.pem --key certB.key \
  -H "Authorization: Bearer $AT" "https://$RUNTIME_HOST/fapi-as/accounts"

# introspect the token (over mTLS as a resource server)
curl -s --cert certA.pem --key certA.key \
  -X POST "https://$RUNTIME_HOST/fapi-as/introspect" -d "token=$AT" | jq .
```

**What success looks like:** `cert A: 200` and `cert B: 401` — the *same* token succeeds only from the cert that obtained it. The decoded `$AT` contains `cnf.x5t#S256` equal to cert A's thumbprint, and `/introspect` returns `active: true` with that same `cnf`. Decode `$AT` at jwt.io to see the binding claim sitting in the payload.
</div>

## Verify it

Decode the issued access token (`echo $AT | cut -d. -f2 | base64 -d`) and confirm a `cnf` object with an `x5t#S256` member whose value equals cert A's SHA-256 thumbprint. In a Trace of the successful `/accounts` call, `client.ssl.cert.fingerprint.sha256.base64url` and `jwt.VJWT-AccessToken.claim.cnf.x5t#S256` should be **identical**, and `RF-CertBindingMismatch` should *not* fire. Re-run with cert B and confirm the same Trace shows the two thumbprints differing and `RF-CertBindingMismatch` raising the `401` with the `WWW-Authenticate: Bearer error="invalid_token"` header. Finally, `POST /introspect` with a freshly expired token must return exactly `{"active": false}` with no scope or `cnf` leaked.

!!! failure "Common failure modes"
    - **Binding stamped but never checked.** `/token` writes `cnf` but `/accounts` only verifies the signature. Symptom: a stolen token works from any cert. The `RF-CertBindingMismatch` condition (or equivalent) must run on every protected flow.
    - **TLS terminated before Apigee.** A load balancer terminates mTLS upstream, so `client.ssl.cert.*` is empty at the proxy. Symptom: the thumbprint is blank and the comparison silently passes. Terminate mTLS at Apigee, or forward the verified cert and read it from the forwarded header.
    - **Thumbprint format mismatch.** Comparing a hex fingerprint, or base64 vs base64url, or the SHA-1 (`x5t`) instead of SHA-256 (`x5t#S256`). Symptom: cert A is rejected as if it were cert B. Use base64url SHA-256 on both sides.
    - **Introspection over-shares on dead tokens.** Returning claims for an expired/invalid token instead of `{"active": false}`. Symptom: scope/`cnf` leak for tokens that should be opaque. Branch: valid → full response, otherwise → `active: false` only.
    - **Introspect endpoint left unauthenticated.** Anyone can probe token validity. Symptom: an open oracle for token guessing. Require mTLS or client auth on `/introspect` too.

!!! stretch "Stretch goal"
    Prove the attack end to end in a Trace: mint a token with cert A, capture both thumbprints on the failing cert-B call, and screenshot the exact step where `RF-CertBindingMismatch` evaluates `true`. Then point a real Spring resource server at your `/introspect` endpoint with `NimbusOpaqueTokenIntrospector`, and add a small `OpaqueTokenAuthenticationConverter` that *also* compares the introspection response's `cnf.x5t#S256` to the X.509 cert on the Spring side — closing the binding gap in the downstream service too, not just at the gateway.

## Recap & next

You made bearer tokens non-bearer. At `/token`, over mTLS, you computed the client cert thumbprint and stamped it into `cnf.x5t#S256` with **GenerateJWT**; on `/accounts` you verified the token and then enforced the binding by comparing the live cert thumbprint to `cnf`, returning `401` on mismatch; and you exposed an RFC 7662 `/introspect` endpoint reporting `active`, `scope`, and `cnf`. Together with the PAR and signed-request-object work from 4.3, you now have the core of a FAPI Advanced server implemented as Apigee policy — a stolen token is useless without the key that obtained it.

**Next — 5.1:** stop onboarding TPPs by hand. You'll implement **Dynamic Client Registration** — validating a signed **Software Statement** from the OB Directory and registering the client as a developer app automatically, the self-service version of the manual app creation from 3.2.
