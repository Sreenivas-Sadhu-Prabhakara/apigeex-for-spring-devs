# 4.2 — The FAPI Advanced profile: what it requires

!!! bottomline "Bottom line"
    **FAPI 1.0 Advanced** is a hardening profile layered on the OAuth 2.0 and OIDC you already know — it doesn't replace them, it tightens them. Every clause (PAR, signed request objects, mTLS-bound tokens, JARM, algorithm restrictions, exact redirect-URI matching) maps to a concrete Apigee mechanism: a **VerifyJWT**, an **OAuthV2**, an **SSLInfo** check, a **GenerateJWT**. This session is the **requirement → policy traceability table** — the centrepiece you'll implement in 4.3 and 4.4.

## Why this exists

Plain OAuth 2.0 leaves a lot to the deployment. Bearer tokens can be replayed by anyone who steals them. Authorization-request parameters travel through the browser where they can be tampered with. A client can be authenticated with a shared secret that leaks. None of that is acceptable when the API moves money out of someone's bank account. FAPI — the Financial-grade API profile from the OpenID Foundation — exists to close those gaps by *removing options* and *mandating proofs*: it says which algorithms are allowed, how requests must be signed, how tokens must be bound to a client, and how responses must be protected from tampering.

For a Spring developer this is the comfortable part of Part 4. Unlike the trust framework in 4.1 — which is a regulated domain model with no Spring analogue — FAPI is a **technical spec made of OAuth primitives**. You already verify JWTs, terminate mTLS, issue tokens. FAPI just dictates *exactly how strict* each of those must be. There is no framework magic and no proprietary Apigee feature: each FAPI clause becomes a specific policy with specific settings.

The trap is thinking FAPI is one big switch. It isn't — it's roughly a dozen independent requirements, and an auditor will check them individually. So the job of this session is to enumerate them and pin each to the Apigee mechanism that satisfies it, so that when you implement in 4.3 and 4.4 you're filling in a checklist, not improvising. The artifact you walk away with is a **traceability table**: clause, what it demands, the policy that enforces it.

!!! bridge "Spring Boot bridge"
    FAPI maps onto things you've configured in **Spring Security / Spring Authorization Server** — Apigee just enforces them at the edge instead of in-process:

    | FAPI requirement | Spring equivalent you've touched | Apigee mechanism |
    |---|---|---|
    | Signed request object (JWS) | `JwtDecoder` verifying a signed JWT | **VerifyJWT** |
    | Algorithm allow-list (PS256/ES256) | `NimbusJwtDecoder` with a `JWSAlgorithm` set | **VerifyJWT** `<Algorithms>` |
    | `private_key_jwt` client auth | `client-authentication-method: private_key_jwt` | **VerifyJWT** on the `client_assertion` |
    | mTLS-bound tokens | `RequestedTokenUse` / cert-bound config | **SSLInfo** + **OAuthV2** with `cnf` x5t#S256 |
    | Issue signed tokens / JARM | `JwtEncoder` / signed `id_token` | **GenerateJWT** |
    | Token introspection / validation | `OpaqueTokenIntrospector` / `JwtDecoder` | **OAuthV2** (`VerifyAccessToken`) |

    The intuition "decode-and-validate inbound, sign outbound" is exactly right. What changes is *where* it runs and that FAPI makes the strictness **mandatory**, not a default you could relax.

!!! breaks "Where the analogy breaks"
    In Spring you tend to trust the framework's defaults — `NimbusJwtDecoder` will happily accept `RS256`, redirect-URI matching is a property you rarely think about, and `none` is refused for you. FAPI forbids you from leaning on defaults: you must *explicitly* allow only `PS256`/`ES256`, *explicitly* reject `none` and `RS256`, *exactly* match the registered redirect URI (no prefix or wildcard matching), and *prove* the token is bound to the presenting client's certificate. Apigee won't infer any of this — an empty `<Algorithms>` element on VerifyJWT accepts whatever the token claims, which is precisely the FAPI failure mode. The analogy breaks at "the framework has my back": at the edge, every FAPI clause is a setting you must assert, and a missing assertion is a silent hole an auditor (or attacker) will find.

## The concept

FAPI 1.0 Advanced is a set of independent clauses. Here is the centrepiece — the **traceability table** mapping each requirement to the Apigee mechanism that satisfies it. Implementations land in 4.3 (PAR, request objects, client auth) and 4.4 (mTLS-bound tokens, JARM, consent):

| # | FAPI 1.0 Advanced requirement | What it demands | Apigee mechanism | Implemented in |
|---|---|---|---|---|
| 1 | **PAR** (Pushed Authorization Requests, RFC 9126) | Client pushes the authz request server-side first, gets a `request_uri`; nothing sensitive in the browser URL | Proxy on `/par` that stores the request and returns a one-time `request_uri` (KVM/cache + **GenerateJWT**/AssignMessage) | 4.3 |
| 2 | **Signed request object** (JWS) | Authorization parameters carried in a `request`/`request_uri` JWT, signed by the client (OBSeal) | **VerifyJWT** against the TPP's JWKS | 4.3 |
| 3 | **Algorithm restrictions** | Only `PS256`/`ES256`; reject `none`, `RS256`, `HS*` | **VerifyJWT** `<Algorithms><Algorithm>PS256</Algorithm>…</Algorithms>` | 4.2 (this lab) |
| 4 | **Client authentication** | `private_key_jwt` **or** `tls_client_auth` (mTLS) — never a plain shared secret | **VerifyJWT** on `client_assertion` *or* **SSLInfo** cert-subject match | 4.3 |
| 5 | **mTLS-bound (certificate-bound) access tokens** | Token carries a `cnf` claim with the client cert thumbprint (`x5t#S256`, RFC 8705); presented cert must match | **OAuthV2** issues token with `cnf`; **SSLInfo** + **VerifyJWT**/condition checks the thumbprint on each call | 4.4 |
| 6 | **JARM** (signed authorization responses) | The authorization response is returned as a signed JWT (`response_mode=jwt`), so it can't be tampered with in the browser | **GenerateJWT** to sign the response parameters | 4.4 |
| 7 | **`s_hash` / `nonce` / `state`** | Detached-signature/`s_hash` and a per-request `nonce`+`state` to bind request and response | **VerifyJWT** claim checks + JavaScript/condition to compare `s_hash` | 4.4 |
| 8 | **Exact redirect-URI matching** | The `redirect_uri` must *exactly* equal one registered in the SSA — no wildcards, no prefixes | Condition comparing `redirect_uri` to the SSA `software_redirect_uris` (KVM lookup) | 4.3 |
| 9 | **`x-fapi-interaction-id`** | Echo the client's interaction id, or mint a UUID, on every response for traceability | **AssignMessage** to set/echo `x-fapi-interaction-id` (and read `x-fapi-auth-date`) | 4.3 |

The single most foundational of these — and the one this session's lab nails down — is **#3, algorithm restrictions**, because every signed artifact in FAPI (request object, client assertion, JARM, id_token) is only as safe as the algorithm allow-list verifying it. Accept `none` anywhere and an attacker forges any claim they like.

```widget
{
  "type": "sequence",
  "title": "Where each FAPI clause fires in one authorize-then-call journey",
  "actors": [
    {"id": "t", "label": "TPP"},
    {"id": "g", "label": "Apigee (FAPI)"},
    {"id": "a", "label": "Token/Authz"}
  ],
  "steps": [
    {"from": "t", "to": "g", "label": "POST /par  (signed request object)", "note": "Clause 1 (PAR) + clause 2 (VerifyJWT on the request JWT) + clause 3 (PS256/ES256 only). Returns a one-time request_uri."},
    {"from": "t", "to": "g", "label": "GET /authorize?request_uri=…", "note": "Clause 8: redirect_uri must exactly match the SSA. PSU then authenticates and consents at the ASPSP."},
    {"from": "g", "to": "t", "kind": "return", "label": "response as signed JWT (JARM)", "note": "Clause 6: response parameters returned signed (GenerateJWT) so the browser can't tamper with code/state."},
    {"from": "t", "to": "a", "label": "POST /token  (private_key_jwt + mTLS)", "note": "Clause 4: client auth by signed client_assertion or tls_client_auth. Clause 5: token minted with cnf x5t#S256."},
    {"from": "t", "to": "g", "label": "GET /aisp/accounts  (mTLS, bearer + cnf)", "note": "Clause 5 again: SSLInfo cert thumbprint must equal the token's cnf. Clause 9: echo x-fapi-interaction-id."}
  ]
}
```

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — pin the traceability table as config-as-code, then enforce clause #3 on VerifyJWT

You'll produce the traceability table as a versioned artifact *and* implement the one clause that everything else depends on: **algorithm restrictions**. The success criterion is a **VerifyJWT** that rejects a token signed with a disallowed algorithm (`none` or `RS256`).

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; the OB truststore from 4.1; a deployed proxy you can attach a policy to (reuse `aisp-accounts` from 3.2).

**1. Commit the traceability table as config-as-code.** Drop it beside the proxy so it's reviewed and versioned, not buried in a wiki:

```yaml
# fapi-traceability.yaml — FAPI 1.0 Advanced → Apigee mechanism
requirements:
  - id: par,          requirement: "Pushed Authorization Requests",  mechanism: "/par proxy + KVM/cache",        session: "4.3"
  - id: request-obj,  requirement: "Signed request object (JWS)",    mechanism: "VerifyJWT vs TPP JWKS",          session: "4.3"
  - id: alg,          requirement: "PS256/ES256 only; no none/RS256", mechanism: "VerifyJWT <Algorithms>",         session: "4.2"
  - id: client-auth,  requirement: "private_key_jwt or tls_client_auth", mechanism: "VerifyJWT(client_assertion)/SSLInfo", session: "4.3"
  - id: cnf-token,    requirement: "mTLS-bound access tokens (cnf x5t#S256)", mechanism: "OAuthV2 cnf + SSLInfo match", session: "4.4"
  - id: jarm,         requirement: "Signed authorization responses (JARM)", mechanism: "GenerateJWT",              session: "4.4"
  - id: redirect,     requirement: "Exact redirect_uri match",        mechanism: "condition vs SSA redirect_uris", session: "4.3"
  - id: fapi-headers, requirement: "x-fapi-interaction-id traceability", mechanism: "AssignMessage echo/mint",      session: "4.3"
```

**2. Write the VerifyJWT that enforces clause #3.** The `<Algorithms>` element is the FAPI control: list *only* the allowed algorithms, so a token using `none` or `RS256` is rejected before its claims are even read. Put this in `apiproxy/policies/`:

```xml
<VerifyJWT name="VJ-FAPI-RequestObject">
  <DisplayName>VJ-FAPI-RequestObject</DisplayName>
  <Algorithms>
    <Algorithm>PS256</Algorithm>
    <Algorithm>ES256</Algorithm>
  </Algorithms>
  <Source>request.formparam.request</Source>
  <PublicKey>
    <JWKS uri="https://keystore.openbanking.example/0014H/acme.jwks"/>
  </PublicKey>
  <AdditionalClaims>
    <Claim name="aud">https://{organization.name}.apigee.net/par</Claim>
  </AdditionalClaims>
</VerifyJWT>
```

**3. Attach it** in the ProxyEndpoint request PreFlow (point ① from 2.1), so any signed request object is algorithm-checked before anything else:

```xml
<PreFlow name="PreFlow">
  <Request>
    <Step><Name>VJ-FAPI-RequestObject</Name></Step>
  </Request>
</PreFlow>
```

**4. Deploy:**

```bash
apigeecli apis create bundle --name aisp-accounts --proxy-folder ./aisp-accounts/apiproxy \
  --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name aisp-accounts --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"
```

**5. Mint two test JWTs and prove the allow-list bites.** One with `alg: none` (forged, no signature), one with `PS256`:

```bash
# alg:none — header {"alg":"none"}, payload {"aud":".../par"}, empty signature
NONE_JWT="eyJhbGciOiJub25lIn0.eyJhdWQiOiJodHRwczovL29yZy5hcGlnZWUubmV0L3BhciJ9."

# Disallowed alg → VerifyJWT rejects it (401), claims never trusted:
curl -s -o /dev/null -w "alg=none:  %{http_code}\n" \
  -H "x-fapi-interaction-id: $(uuidgen)" \
  --data-urlencode "request=$NONE_JWT" \
  "https://$RUNTIME_HOST/aisp-accounts/accounts"

# A properly PS256-signed request object → passes the algorithm gate (then other checks apply):
PS256_JWT="<paste a PS256-signed JWT whose aud matches>"
curl -s -o /dev/null -w "alg=PS256: %{http_code}\n" \
  -H "x-fapi-interaction-id: $(uuidgen)" \
  --data-urlencode "request=$PS256_JWT" \
  "https://$RUNTIME_HOST/aisp-accounts/accounts"
```

**What success looks like:** `alg=none: 401` — VerifyJWT raises `InvalidAlgorithm`/`InvalidToken` because `none` isn't in `<Algorithms>`, so the forged token's claims are never honoured. The `PS256` token clears the algorithm gate. You also have `fapi-traceability.yaml` committed, so every remaining FAPI clause has a named owner policy and a target session.
</div>

## Verify it

In **Trace**, send the `alg=none` request and confirm the `VJ-FAPI-RequestObject` step shows a fault with error `steps.jwt.InvalidToken` (or `InvalidAlgorithm`) — *not* a downstream 200. The forged token must die at the algorithm gate, before any `verifyjwt.*` claim variable is populated. Then temporarily add `<Algorithm>RS256</Algorithm>` to the policy, redeploy, and watch an `RS256` token start passing the gate: that's the exact relaxation FAPI forbids, and seeing it pass proves the allow-list is what's doing the work. Remove `RS256` again.

For the table itself, treat `fapi-traceability.yaml` as the source of truth in review: every `mechanism` names a real Apigee policy type (VerifyJWT, OAuthV2, SSLInfo, GenerateJWT, AssignMessage), and every row points at the session that implements it. If a clause has no named mechanism, that's a gap to close before 4.3.

!!! failure "Common failure modes"
    - **Empty or missing `<Algorithms>`.** Without it, VerifyJWT accepts whatever `alg` the token's header claims — including `none`. Symptom: a forged `alg:none` token sails through and its claims are trusted. This is the headline FAPI failure.
    - **Allowing `RS256` "because it's signed".** FAPI Advanced mandates `PS256`/`ES256`; `RS256` and `HS*` are not permitted. Symptom: an audit flags the allow-list even though signatures verify.
    - **Treating FAPI as one switch.** It's a dozen independent clauses. Symptom: you enforce algorithm restrictions and declare victory, but PAR, mTLS-bound tokens, and exact redirect matching are still open holes.
    - **Confusing the two signing keys.** The request object is signed with the TPP's **OBSeal** key (verified via its JWKS); the transport cert is **OBWAC** (4.1). Symptom: you point VerifyJWT's JWKS at the transport cert and every signature fails.
    - **Verifying the algorithm but not the `aud`/`iss`.** A valid signature on the wrong audience is still an attack. Symptom: a request object signed for a different ASPSP is accepted because you only checked `alg`.

!!! stretch "Stretch goal"
    Extend `fapi-traceability.yaml` into a full audit artifact: for each clause add the *negative* test that proves enforcement (the disallowed input and the fault it must raise) and the FAPI/RFC reference (RFC 9126 for PAR, RFC 8705 for mTLS-bound tokens and `tls_client_auth`, the OpenID FAPI 1.0 Advanced section number for JARM and algorithm restrictions). Then map each row back to the Spring config that *would* satisfy it in-process — the `NimbusJwtDecoder` algorithm set, the `private_key_jwt` client registration — so a reviewer can see that the edge is enforcing exactly what the Spring client assumes the server does, and nothing is left to a default.

## Recap & next

You can now read **FAPI 1.0 Advanced** as a checklist rather than a monolith, and you hold the **traceability table** that pins each clause — PAR, signed request objects, algorithm restrictions, client auth, mTLS-bound tokens, JARM, `s_hash`/`nonce`, exact redirect-URI matching, `x-fapi-interaction-id` — to a named Apigee mechanism (**VerifyJWT**, **OAuthV2**, **SSLInfo**, **GenerateJWT**, **AssignMessage**). You've committed that table as config-as-code and enforced the foundational clause: a **VerifyJWT** whose `<Algorithms>` allow-list rejects `none` and `RS256`. FAPI is hardened OAuth, not framework magic — every requirement is a setting you assert at the edge.

**Next — 4.3:** start implementing the table top-down. You'll build **PAR** (a `/par` endpoint that stores the pushed request and returns a one-time `request_uri`), verify the **signed request object** against the TPP's JWKS, and authenticate the client with **`private_key_jwt`** / **`tls_client_auth`** — the strict server-side validations a Spring FAPI client relies on, built as real Apigee policies.
