# 3.4 — Auth-code + PKCE & JWT verification

!!! bottomline "Bottom line"
    Client-credentials (3.3) authenticates a *machine*. The **authorization-code grant** authenticates a *human* and gets their consent — it's the flow behind every "Sign in and allow this app to see your accounts" screen. **PKCE** hardens it against code interception for public clients, and minting the result as a **signed JWT** lets every downstream verify identity with **no shared session and no callback to the token server**. By the end you can stand up `/authorize` and `/token`, issue a JWT access token, and verify it on a protected flow with `VerifyJWT`.

## Why this exists

In Spring you've almost certainly *consumed* this flow — `spring-boot-starter-oauth2-client` with an `oauth2Login()` filter chain. You configured an `issuer-uri`, Spring discovered the `/authorize` and `/token` endpoints, bounced the user to the IdP, swapped a code for tokens, and handed you a populated `Authentication`. You were the **client**. The IdP — Okta, Keycloak, Entra, Google — was the **authorization server**. This session builds that authorization-server side, at the edge, in Apigee.

The authorization-code grant exists because the password and client-credentials grants can't safely involve a *person*. You must not let the app see the user's bank password, and you must capture explicit consent ("this TPP may read your accounts"). So the flow redirects the user's *browser* to the authorization server, the user authenticates and consents there, and the app receives only a short-lived, single-use **authorization code** on a redirect back. The app then exchanges that code — server-to-server — for tokens. The code never grants access by itself; it's a claim ticket.

**PKCE** (Proof Key for Code Exchange, RFC 7636) closes the remaining gap: a public client (a mobile app, an SPA) can't keep a `client_secret`, so a stolen authorization code could be redeemed by an attacker. With PKCE the client invents a random `code_verifier`, sends only its SHA-256 hash (`code_challenge`) to `/authorize`, and must present the original `code_verifier` at `/token`. An intercepted code is useless without the verifier. In UK Open Banking / FAPI, PKCE with `S256` is **mandatory**, not optional.

Finally, the token itself. A JWT is a **signed, self-describing** token: a resource server validates the signature against a public key (JWKS) and reads the claims, with no database lookup and no introspection call. That statelessness is the whole point — it's what lets you scale resource servers horizontally without a shared session store.

!!! bridge "Spring Boot bridge"
    You've built both halves of this in Spring; Apigee just relocates them to the edge. The mapping is tight:

    | Spring OAuth concept | Apigee X equivalent |
    |---|---|
    | `oauth2Login()` client filter chain | the *client* — you're now the server it talks to |
    | Spring Authorization Server `/oauth2/authorize` | **OAuthV2** `GenerateAuthorizationCode` |
    | Spring Authorization Server `/oauth2/token` | **OAuthV2** `GenerateAccessToken`, `grant_type=authorization_code` |
    | `JwtEncoder` / `NimbusJwtEncoder` signing a JWT | **GenerateJWT** signing with `RS256` |
    | `JwtDecoder` + `jwk-set-uri` on a resource server | **VerifyJWT** with `<JWKS uri="…"/>` |
    | `RegisteredClient` (`client_id`, redirect URIs) | the developer **App** from 3.2 (`consumerKey` = `client_id`) |

    If you ever wired a `NimbusJwtDecoder` from a `jwk-set-uri` and let it cache the keys, `VerifyJWT` with a `<JWKS uri>` is the same thing — fetch-and-cache the JWKS, validate `RS256`, expose the claims.

!!! breaks "Where the analogy breaks"
    Spring Authorization Server is a single application that owns the *whole* dance — it renders the login page, stores the consent, persists the code, and signs the token, all in-process. Apigee's OAuthV2 deliberately does **not** own the human-facing parts. It mints and validates codes and tokens, but **you** must supply the login/consent UI and the user-authentication step (typically a separate IdP or a custom app the proxy calls out to). OAuthV2 is the *token machinery*, not the identity provider. The other break: an opaque OAuthV2 access token and a signed JWT are two different artifacts. Plain `GenerateAccessToken` issues an *opaque* token that only Apigee can introspect; to get the stateless, anyone-can-verify JWT you mint a **separate** JWT (via GenerateJWT). Don't assume the bearer string is a JWT just because OAuth issued it.

## The concept

The flow has two legs separated by a browser redirect. The **front-channel** (through the user's browser) carries the `code_challenge` and returns the `code`. The **back-channel** (server-to-server) exchanges the `code` + `code_verifier` for the token. PKCE is the thread that ties them: the same secret, hashed going out, revealed coming back.

```widget
{
  "type": "sequence",
  "title": "Authorization-code + PKCE, end to end",
  "actors": [
    {"id": "u", "label": "User browser"},
    {"id": "a", "label": "Client app"},
    {"id": "g", "label": "Apigee /authorize + /token"},
    {"id": "r", "label": "Resource proxy"}
  ],
  "steps": [
    {"from": "a", "to": "a", "label": "make code_verifier; code_challenge = S256(verifier)", "note": "The client invents a high-entropy random string and SHA-256-hashes it. Only the hash leaves the device."},
    {"from": "a", "to": "u", "label": "redirect to /authorize?…&code_challenge=…&method=S256", "note": "Front-channel. Carries client_id, redirect_uri, scope, state, and the challenge — never the verifier."},
    {"from": "u", "to": "g", "label": "GET /authorize (user logs in + consents)", "note": "Apigee calls out to your IdP/consent UI to authenticate the human and capture consent. OAuthV2 does not render this itself."},
    {"from": "g", "to": "u", "kind": "return", "label": "302 redirect_uri?code=XYZ&state=…", "note": "GenerateAuthorizationCode mints a short-lived, single-use code bound to the challenge."},
    {"from": "u", "to": "a", "label": "browser lands on redirect_uri with code", "note": "The app now holds the code but cannot use it without the verifier."},
    {"from": "a", "to": "g", "label": "POST /token  code=XYZ & code_verifier=…", "note": "Back-channel. GenerateAccessToken recomputes S256(verifier) and compares to the stored challenge."},
    {"from": "g", "to": "a", "kind": "return", "label": "access_token (signed JWT), refresh_token", "note": "Match → issue. The JWT carries sub, scope, exp, signed with RS256."},
    {"from": "a", "to": "r", "label": "GET /accounts  Authorization: Bearer <JWT>", "note": "The protected proxy runs VerifyJWT against the JWKS — no callback to /token needed."},
    {"from": "r", "to": "a", "kind": "return", "label": "200 + account data", "note": "Stateless: the resource proxy trusted the signature, read the claims, and never touched a session store."}
  ]
}
```

The four OAuthV2/JWT operations you'll wire, and where each lives:

- **`/authorize`** → `GenerateAuthorizationCode` — validates `client_id`/`redirect_uri`, stores the `code_challenge`, returns a code on the redirect. Runs *after* your login+consent step.
- **`/token`** → `GenerateAccessToken` with `<GrantType>authorization_code</GrantType>` — verifies the code, recomputes `S256(code_verifier)`, issues tokens. PKCE checking is automatic when a challenge was stored.
- **GenerateJWT** — signs an `RS256` JWT with your private key so the access token is self-verifiable.
- **VerifyJWT** — on the *protected* proxy, validates the signature against a JWKS URL and surfaces the claims as `jwt.{policy}.claim.*` variables.

!!! pitfall "Watch out"
    PKCE only protects you if the verifier actually matches: the `code_verifier` presented at `/token` must SHA-256-hash (`S256`) to the exact `code_challenge` sent at `/authorize`, or the exchange fails with `invalid_grant`. Equally unforgiving is `redirect_uri` — it must match the registered value **exactly**, down to a trailing slash, or `/authorize` rejects the request before any login. Hash and URL are both literal comparisons, not fuzzy ones.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — stand up /authorize + /token, then verify the JWT

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; the developer **App** from 3.2 (its `consumerKey` is your `client_id`) with a registered redirect URI; and an RSA keypair for signing. Generate one if you don't have it:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out private.pem
openssl rsa -in private.pem -pubout -out public.pem
```

**1. Store the signing key** in an environment KVM (so rotation needs no redeploy):

```bash
apigeecli kvms create --name oauth-keys --env "$ENV" --org "$ORG" --token "$TOKEN"
apigeecli kvms entries create --map oauth-keys --key signing-private-key \
  --value "$(cat private.pem)" --env "$ENV" --org "$ORG" --token "$TOKEN"
```

**2. The `/authorize` endpoint.** After your login+consent step runs, mint the code. OAuthV2 reads `client_id`, `redirect_uri`, `scope`, `code_challenge`, and `code_challenge_method` straight off the request:

```xml
<OAuthV2 name="OA-GenAuthCode">
  <Operation>GenerateAuthorizationCode</Operation>
  <ExpiresIn>600000</ExpiresIn>
  <GenerateResponse enabled="true"/>
</OAuthV2>
```

**3. The `/token` endpoint** — exchange the code for an opaque OAuth token. PKCE verification is automatic: because a `code_challenge` was stored with the code, OAuthV2 requires and checks `code_verifier`:

```xml
<OAuthV2 name="OA-GenAccessToken">
  <Operation>GenerateAccessToken</Operation>
  <GrantType>request.formparam.grant_type</GrantType>
  <ExpiresIn>1800000</ExpiresIn>
  <SupportedGrantTypes>
    <GrantType>authorization_code</GrantType>
  </SupportedGrantTypes>
  <GenerateResponse enabled="false"/>
</OAuthV2>
```

**4. Mint the JWT** right after, on the `/token` response flow, so the bearer the client receives is a self-verifiable `RS256` JWT carrying the OAuth scope and subject. Load `signing-private-key` from the KVM into `private.signing-key.pem` with a `KeyValueMapOperations` get *before* this policy:

```xml
<GenerateJWT name="GJ-MintAccessToken">
  <Algorithm>RS256</Algorithm>
  <PrivateKey>
    <Value ref="private.signing-key.pem"/>
  </PrivateKey>
  <Subject ref="oauthv2accesstoken.OA-GenAccessToken.developer.id"/>
  <Issuer>https://{organization.name}-{environment.name}.apigee.net</Issuer>
  <Audience>aisp-resource</Audience>
  <ExpiresIn>1800</ExpiresIn>
  <AdditionalClaims>
    <Claim name="scope" ref="oauthv2accesstoken.OA-GenAccessToken.scope"/>
    <Claim name="client_id" ref="oauthv2accesstoken.OA-GenAccessToken.client_id"/>
  </AdditionalClaims>
  <OutputVariable>signed.jwt</OutputVariable>
</GenerateJWT>
```

**5. Verify the JWT on the protected proxy.** On `aisp-accounts` (from 3.2), in the ProxyEndpoint request PreFlow, validate the bearer against your JWKS endpoint and pull out the claims:

```xml
<VerifyJWT name="VJ-AccessToken">
  <Algorithm>RS256</Algorithm>
  <Source>request.header.authorization.bearer</Source>
  <JWKS uri="https://{organization.name}-{environment.name}.apigee.net/.well-known/jwks.json"/>
  <Issuer>https://{organization.name}-{environment.name}.apigee.net</Issuer>
  <Audience>aisp-resource</Audience>
</VerifyJWT>
```

On success it populates `jwt.VJ-AccessToken.claim.sub`, `.claim.scope`, `.claim.exp`, etc. — gate `/accounts` on `jwt.VJ-AccessToken.claim.scope` containing `accounts` exactly as you'd check authorities in a Spring `@PreAuthorize`.

!!! pitfall "Watch out"
    Pin `<Algorithm>RS256</Algorithm>` and never let `VerifyJWT` accept `alg: none` or a symmetric algorithm like `HS256` you didn't intend — an attacker who can pick the algorithm can forge a token the verifier "validates." The `<JWKS uri>` must also serve the public key whose `kid` signed *this* token; if signer and JWKS drift apart, verification fails even though the signature is genuine. Match the algorithm and the `kid` deliberately, don't leave them open.

**6. Deploy and drive the full flow** (PKCE values precomputed for clarity):

```bash
apigeecli apis create bundle --name aisp-oauth --proxy-folder ./aisp-oauth/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name aisp-oauth --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

VERIFIER="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
# CHALLENGE = base64url(SHA256(VERIFIER)) — sent at /authorize
CID="<your consumerKey>"

# /token exchange — assuming you captured CODE from the /authorize redirect
curl -s -X POST "https://$RUNTIME_HOST/aisp-oauth/token" \
  -d grant_type=authorization_code -d "client_id=$CID" \
  -d "code=$CODE" -d "code_verifier=$VERIFIER" | jq .

# call the protected proxy with the resulting JWT
JWT="<paste access_token>"
curl -s -o /dev/null -w "with JWT: %{http_code}\n" \
  -H "Authorization: Bearer $JWT" "https://$RUNTIME_HOST/aisp-accounts/accounts"
```

**What success looks like:** `/token` returns a JSON body whose `access_token` decodes (paste it into jwt.io) to claims `sub`, `scope`, `iss`, `aud`, `exp`; the protected call returns `200`; and replaying the same `code` a second time returns `invalid_grant` because authorization codes are single-use. Tamper one character of the JWT and `VerifyJWT` rejects it before the backend is ever touched.
</div>

## Verify it

Confirm three things in Trace. First, in the `/token` exchange, OAuthV2 logs a PKCE check — send the request with a *wrong* `code_verifier` and you get `invalid_grant`, proving the `S256` comparison runs. Second, on the protected proxy, `VerifyJWT` runs in PreFlow *before* the `RouteRule`, so a bad token never reaches the backend. Third, inspect `jwt.VJ-AccessToken.claim.scope` in the Trace variables — it should equal the `scope` you requested at `/authorize`, carried through the code and into the JWT.

!!! pitfall "Watch out"
    A short `<ExpiresIn>` plus a small clock difference between the signing host and the verifying host produces sporadic "token expired" `401`s on tokens that were just minted. Allow a few seconds of skew leeway on the `exp` check rather than chasing intermittent failures, and keep `ExpiresIn` realistic so genuine expiry and skew never blur together.

A useful negative test: strip the `<Audience>` from your `GenerateJWT` and redeploy. `VerifyJWT` now fails with an audience mismatch, exactly as a Spring `JwtDecoder` with an `OAuth2TokenValidator` audience check would reject it. That symmetry is the point — the same validations you configure on a Spring resource server are the ones `VerifyJWT` runs at the edge.

!!! failure "Common failure modes"
    - **No PKCE because no challenge was stored.** If `/authorize` didn't capture `code_challenge`, OAuthV2 issues a code with no challenge and `/token` never asks for a verifier. Symptom: an intercepted code redeems successfully without a verifier — the exact attack PKCE exists to stop. Confirm the challenge reaches `GenerateAuthorizationCode`.
    - **Treating the opaque token as a JWT.** `GenerateAccessToken` alone returns an opaque string; pasting it into jwt.io yields garbage. Symptom: "my JWT won't decode." You need the separate `GenerateJWT` step (step 4).
    - **JWKS / issuer / audience mismatch.** `VerifyJWT` fails if `iss`/`aud` on the token don't match the policy, or the JWKS URL doesn't serve the public key whose private half signed it. Symptom: `401` with `jwt.VJ-AccessToken.error` showing the specific mismatch — read that variable, don't guess.
    - **Clock skew on `exp`.** A short `ExpiresIn` plus skew between signer and verifier produces sporadic "token expired." Symptom: intermittent `401`s on fresh tokens. Allow a few seconds of leeway and keep `ExpiresIn` realistic.
    - **Redirect URI not registered.** `GenerateAuthorizationCode` rejects a `redirect_uri` that isn't on the App. Symptom: `invalid_request` at `/authorize` before any login. Register the exact URI (including path and trailing slash) on the developer App.

!!! stretch "Stretch goal"
    Wire a real Spring `oauth2Login()` client against your Apigee endpoints end to end. Point `spring.security.oauth2.client.provider.apigee.authorization-uri` and `token-uri` at your `/authorize` and `/token`, set the `client-id` to the App's `consumerKey`, enable PKCE on the client registration, and configure a resource server with `spring.security.oauth2.resourceserver.jwt.jwk-set-uri` pointing at your JWKS. Click through the login, watch Spring swap the code (with its own generated verifier) for your JWT, and call a `@PreAuthorize("hasAuthority('SCOPE_accounts')")` endpoint with it. When that round-trips, you've proven Apigee is a drop-in authorization server for the exact Spring machinery you started from.

## Recap & next

You've built the *server* side of the flow your Spring `oauth2Login()` client consumes: `/authorize` issuing a PKCE-bound code with `GenerateAuthorizationCode`, `/token` exchanging it (and auto-checking the `S256` verifier) with `GenerateAccessToken`, a signed `RS256` JWT minted by `GenerateJWT`, and stateless validation on the protected proxy via `VerifyJWT` against a JWKS. Identity is now signed, self-describing, and verifiable at the edge with no shared session.

**Next — 3.5:** identity is solved, but the *transport* underneath it is still implicitly trusted. You'll secure both edges with **TLS and mTLS** — keystores, truststores, and references — terminating one-way (and optionally mutual) TLS north-bound at the host, and configuring south-bound mutual TLS to your backend in the TargetEndpoint's `<SSLInfo>`. That mutual-TLS client identity is what FAPI later binds tokens to in 4.4.
