# 3.3 — OAuthV2 as a token server (client credentials)

!!! bottomline "Bottom line"
    Apigee's **OAuthV2** policy turns the gateway itself into an OAuth 2.0 **authorization server** — no separate service to stand up. With one policy in `GenerateAccessToken` mode you mint client-credentials tokens at a `/oauth/token` endpoint; with the same policy in `VerifyAccessToken` mode you protect `/accounts`. The **App** you built in 3.2 *is* the OAuth client — its `consumerKey`/`consumerSecret` are the `client_id`/`client_secret`, and the token's scopes are derived from the granted API Product. By the end you can issue a token, get a `401` without it and a `200` with it.

## Why this exists

In Spring, "be an OAuth token server" means standing up **Spring Authorization Server**: a `RegisteredClient` repository, a token endpoint, signing keys, an introspection or JWK endpoint, and the operational burden of running, scaling, and rotating all of it. For machine-to-machine traffic — one service calling another with the **client-credentials** grant — that's a lot of infrastructure to authenticate a backend job.

Apigee already holds the client registry: the **Developer → App → API Product** chain from 3.2. The App's `consumerKey`/`consumerSecret` are exactly what a client-credentials exchange needs. So rather than run a second system, you point the App at a `/oauth/token` proxy endpoint, attach **OAuthV2** in `GenerateAccessToken` mode, and Apigee issues, stores, and later verifies the token for you. The authorization server *is* the gateway.

The payoff is that issuance and enforcement share one model. The scopes baked into the token come from the **API Product** the App holds — change the product, change what the token can do, no proxy redeploy. And because **VerifyAccessToken** re-walks the same chain on every protected call, the entitlement decision you made in 3.2 is enforced on the bearer token automatically. (This session is the two-legged, machine-to-machine grant; the user-present **authorization-code + PKCE** flow and standalone **JWT verification** are 3.4.)

!!! bridge "Spring Boot bridge"
    You're replacing a service you'd otherwise run with a policy you attach:

    | Spring Authorization Server piece | Apigee equivalent |
    |---|---|
    | The authorization server application itself | A proxy with **OAuthV2** policies — no separate deployment |
    | `RegisteredClient` (client_id / client_secret) | The **App** from 3.2 (`consumerKey` / `consumerSecret`) |
    | `client_credentials` token endpoint | A `/oauth/token` flow running **OAuthV2** `GenerateAccessToken` |
    | Scopes / authorities on the client | Scopes derived from the granted **API Product** |
    | `oauth2ResourceServer().opaqueToken()` on a resource server | **OAuthV2** `VerifyAccessToken` on the protected flow |
    | `RegisteredClientRepository` lookups | `VerifyAPIKey`-style chain walk inside `GenerateAccessToken` |

    The App you registered in 3.2 needs *no* changes to become an OAuth client. That's the point: identity and token issuance are the same registry.

!!! breaks "Where the analogy breaks"
    By default Apigee issues **opaque** access tokens — random strings it stores and validates internally — not the signed JWTs Spring Authorization Server hands out by default. So a downstream Spring resource server can't decode an Apigee opaque token with a `JwtDecoder`; it would either call back to Apigee to verify, or you'd configure Apigee to issue a JWT instead (that JWT path, and verifying it downstream, is the 3.4 territory and the stretch goal below). Also, Apigee's `VerifyAccessToken` does more than Spring's introspection: it re-resolves the **App and API Product** behind the token on every call, so revoking the product's access takes effect immediately — there's no cached authority list living on the resource server.

## The concept

The client-credentials flow is two exchanges that share one token store. First the App trades its credentials for a token; then it presents that token on every protected call, where `VerifyAccessToken` validates it and re-attaches the entitlement context.

```widget
{
  "type": "sequence",
  "title": "Client-credentials: mint a token, then use it",
  "actors": [
    {"id": "app", "label": "Client App"},
    {"id": "tok", "label": "/oauth/token proxy"},
    {"id": "api", "label": "/accounts proxy"},
    {"id": "store", "label": "Apigee token store"}
  ],
  "steps": [
    {"from": "app", "to": "tok", "label": "POST /oauth/token  Basic base64(key:secret)  grant_type=client_credentials", "note": "The App's consumerKey/secret ARE the client_id/client_secret, sent as HTTP Basic."},
    {"from": "tok", "to": "store", "label": "OAuthV2 GenerateAccessToken", "note": "Validates the credentials against the App, derives scopes from the granted API Product, mints + stores a token."},
    {"from": "store", "to": "tok", "kind": "return", "label": "access_token, expires_in, scope", "note": "Opaque token by default, with TTL and product-derived scopes."},
    {"from": "tok", "to": "app", "kind": "return", "label": "200 { access_token, token_type: Bearer, expires_in }", "note": "Standard OAuth token response shape."},
    {"from": "app", "to": "api", "label": "GET /accounts  Authorization: Bearer <token>", "note": "The App now calls the protected resource with the bearer token."},
    {"from": "api", "to": "store", "label": "OAuthV2 VerifyAccessToken", "note": "Looks up the token, checks expiry + scope, re-resolves App + API Product."},
    {"from": "store", "to": "api", "kind": "return", "label": "valid: client_id, scope, app, product", "note": "Populates oauthv2accesstoken.* context for downstream policies."},
    {"from": "api", "to": "app", "kind": "return", "label": "200 (or 401 if missing/expired/invalid)", "note": "No token, expired token, or insufficient scope → 401, backend never touched."}
  ]
}
```

The two **OAuthV2** modes you'll write:

- **`GenerateAccessToken`** lives on the `/oauth/token` flow. It reads `grant_type`, validates the Basic-auth client credentials, derives scopes from the App's API Product, and returns the standard token JSON. Token TTL is set with `<ExpiresIn>`.
- **`VerifyAccessToken`** lives in the protected proxy's request PreFlow. It pulls the bearer token from the `Authorization` header, validates it, and on success populates `oauthv2accesstoken.*` flow variables (`client_id`, `scope`, `developer.email`, `api_product_list`) for downstream policies — quota, logging, routing.

!!! pitfall "Watch out"
    The `/oauth/token` endpoint must stay **unprotected**: if `VerifyAccessToken` runs in front of it you need a token to get a token — a chicken-and-egg lockout where every `POST /oauth/token` returns `401`. Always exclude the token path from the verify step. And don't try to invent scopes in the token request — `GenerateAccessToken` derives them from the granted API Product and ignores what the client asks for.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — issue client-credentials tokens, then protect /accounts

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported, and the **App** + **API Product** from 3.2 (`acme-budgeting` granted `aisp-read`, scope `accounts`). Grab the App's `consumerKey`/`consumerSecret`:

```bash
apigeecli apps get --name acme-budgeting --email tpp-acme@example.com \
  --org "$ORG" --token "$TOKEN" | jq '.credentials[0] | {consumerKey, consumerSecret}'
```

**1. The token-issuing policy** — `GenerateAccessToken` for the client-credentials grant. Put this in `apiproxy/policies/`:

```xml
<!-- OA-GenerateCC.xml -->
<OAuthV2 name="OA-GenerateCC">
  <Operation>GenerateAccessToken</Operation>
  <SupportedGrantTypes>
    <GrantType>client_credentials</GrantType>
  </SupportedGrantTypes>
  <GrantType>request.formparam.grant_type</GrantType>
  <ExpiresIn>3600000</ExpiresIn>            <!-- 1 hour, in ms -->
  <GenerateResponse enabled="true"/>
</OAuthV2>
```

Apigee reads the `client_id`/`client_secret` from HTTP Basic by default; it validates them against the App and derives scopes from the granted **API Product** automatically.

!!! pitfall "Watch out"
    Resist the urge to echo the `consumerSecret` or the minted `access_token` into a `MessageLogging` policy or a `curl` you paste into a ticket — a logged secret is a leaked secret, and a logged bearer token is a live credential anyone reading the log can replay until it expires. If you must trace, log only the first few characters as in the `echo "token: ${ACCESS_TOKEN:0:12}..."` above.

**2. The verification policy** — `VerifyAccessToken` for protected resources:

```xml
<!-- OA-Verify.xml -->
<OAuthV2 name="OA-Verify">
  <Operation>VerifyAccessToken</Operation>
</OAuthV2>
```

**3. Wire the `/oauth/token` flow.** Add a conditional flow in the ProxyEndpoint (`proxies/default.xml`) that runs `GenerateAccessToken` and returns — there's no backend behind a token endpoint:

```xml
<Flow name="OAuthToken">
  <Condition>proxy.pathsuffix MatchesPath "/oauth/token" and request.verb = "POST"</Condition>
  <Request>
    <Step><Name>OA-GenerateCC</Name></Step>
  </Request>
  <Response/>
</Flow>
```

**4. Protect `/accounts`.** Attach `VerifyAccessToken` in the request PreFlow so every protected path requires a valid bearer token (point ① from 2.1). The token endpoint itself must stay unprotected — gate the step off the token path:

```xml
<PreFlow name="PreFlow">
  <Request>
    <Step>
      <Name>OA-Verify</Name>
      <Condition>proxy.pathsuffix !MatchesPath "/oauth/token"</Condition>
    </Step>
  </Request>
  <Response/>
</PreFlow>
```

**5. Deploy:**

```bash
apigeecli apis create bundle --name aisp-accounts --proxy-folder ./aisp-accounts/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name aisp-accounts --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"
```

**6. Mint a token, then prove enforcement:**

```bash
KEY="<consumerKey>"; SECRET="<consumerSecret>"

# exchange client credentials for a token
ACCESS_TOKEN=$(curl -s -u "$KEY:$SECRET" \
  -d "grant_type=client_credentials" \
  "https://$RUNTIME_HOST/aisp-accounts/oauth/token" | jq -r '.access_token')
echo "token: ${ACCESS_TOKEN:0:12}..."

# no token → 401
curl -s -o /dev/null -w "no token:   %{http_code}\n" \
  -H "x-fapi-interaction-id: $(uuidgen)" \
  "https://$RUNTIME_HOST/aisp-accounts/accounts"

# valid bearer token → 200
curl -s -o /dev/null -w "bearer:     %{http_code}\n" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "x-fapi-interaction-id: $(uuidgen)" \
  "https://$RUNTIME_HOST/aisp-accounts/accounts"
```

**What success looks like:** the token call returns JSON with `access_token`, `token_type: "Bearer"`, `expires_in: 3600`, and a `scope` of `accounts` derived from the product; `no token: 401`; `bearer: 200`. Revoke the App's grant on the product in 3.2 and the *same* token starts failing verification — proof that `VerifyAccessToken` re-resolves the live entitlement, not a snapshot.
</div>

## Verify it

Inspect the token response shape and confirm the scope came from the API Product, not the request:

```bash
curl -s -u "$KEY:$SECRET" -d "grant_type=client_credentials" \
  "https://$RUNTIME_HOST/aisp-accounts/oauth/token" | jq '{token_type, expires_in, scope}'
```

!!! pitfall "Watch out"
    Revoking the App's grant on the product changes future authorization, but a token already minted keeps verifying until it **expires** or you explicitly revoke it — `VerifyAccessToken` re-resolves the entitlement, yet the token itself still exists in the store. If a plan change must take effect immediately, revoke the outstanding tokens too; don't assume the product edit alone closes the window.

You should see `token_type: "Bearer"`, `expires_in: 3600`, and `scope: "accounts"` — the scope is product-derived, so an App on a different product gets a different scope without any proxy change. Open a debug session and replay the protected call: the Trace should show `OA-Verify` populating `oauthv2accesstoken.client_id`, `oauthv2accesstoken.scope`, and `oauthv2accesstoken.api_product_list` — the same context `VerifyAPIKey` gave you in 3.2, now derived from the bearer token. Send a deliberately mangled token and confirm a clean `401` with `RouteRule` never selecting a target.

!!! failure "Common failure modes"
    - **Token endpoint accidentally protected.** Attaching `VerifyAccessToken` in PreFlow without excluding `/oauth/token` means you need a token to get a token. Symptom: `POST /oauth/token` returns `401`. Gate the verify step off `proxy.pathsuffix !MatchesPath "/oauth/token"`.
    - **Sending credentials in the body instead of Basic auth.** OAuthV2 reads `client_id`/`client_secret` from HTTP Basic by default. Symptom: `invalid_client` even with correct keys. Use `curl -u "$KEY:$SECRET"` or configure the policy's `<ClientId>`/`<ClientSecret>` refs explicitly.
    - **Expecting a decodable JWT.** The default token is opaque, not a signed JWT. Symptom: a downstream Spring `JwtDecoder` throws on it. Either verify via Apigee or switch issuance to a JWT (see the stretch goal and 3.4).
    - **Confusing `expires_in` units.** `<ExpiresIn>` is **milliseconds** in the policy but the response reports `expires_in` in **seconds**. Symptom: tokens that seem to live 1000× too long or too short. `3600000` ms → `expires_in: 3600`.
    - **Wrong scope, wrong product.** A token's scope is whatever the granted API Product carries. Symptom: a downstream scope check fails. Fix the **product** in 3.2, not the proxy.

!!! stretch "Stretch goal"
    Configure `OAuthV2` to issue a **JWT** access token (via the JWT-format issuance option) signed with a key in an Apigee keystore, then stand up a minimal Spring resource server with `spring.security.oauth2.resourceserver.jwt.jwk-set-uri` pointing at Apigee's JWKS, and validate the Apigee-minted token end to end with a `JwtDecoder` — no introspection call back to the gateway. Note which claims you had to add explicitly (issuer, audience, scope) to satisfy Spring's default validators, and where the FAPI requirements (`aud`, short TTL) would tighten that further. This is the bridge into 3.4.

## Recap & next

You've turned Apigee into an OAuth 2.0 **authorization server** without standing up a separate service: **OAuthV2** in `GenerateAccessToken` mode issues client-credentials tokens at `/oauth/token`, the **App** from 3.2 *is* the OAuth client, scopes flow from the granted **API Product**, and `VerifyAccessToken` enforces the token on `/accounts` while re-resolving the live entitlement on every call. No token is a `401`; a valid bearer is a `200`.

**Next — 3.4:** the user-present half of OAuth. You'll add the **authorization-code grant with PKCE** for flows where a human consents in a browser, and verify externally-issued **JWTs** with `VerifyJWT` against a JWKS — the FAPI-grade token handling Open Banking actually mandates.
