# 5.1 — Dynamic Client Registration (DCR)

!!! bottomline "Bottom line"
    In Open Banking you don't onboard TPPs by hand — they self-register through a standard **`POST /register`** endpoint, presenting a signed **Software Statement Assertion (SSA)** issued by the OB Directory. Your gateway validates the SSA's JWS signature against the Directory's JWKS, extracts `software_roles` and `software_redirect_uris`, and provisions the **Developer → App → API Product** chain from session 3.2 *automatically* — returning a `client_id` the TPP can immediately use. By the end you can stand up a `/register` proxy that turns a valid SSA into a live developer app.

## Why this exists

Onboarding a client in session 3.2 was a human ritual: someone creates a Developer, creates an App, binds it to an API Product, reads back the credentials, and emails them out. That is fine for a handful of partners. It does not scale to an ecosystem of hundreds of TPPs that come and go, each already vetted by an external authority — and it is explicitly *not* how UK Open Banking works. The standard (OBIE DCR, built on RFC 7591) mandates that registration be a **machine-to-machine API call**, so a TPP that has been enrolled with the OB Directory can register with any ASPSP without a ticket, a phone call, or a portal.

The trust trick is that you don't have to vet the TPP yourself. The OB Directory already did. It packaged the result into a **Software Statement Assertion** — a JWS signed by the Directory — carrying the TPP's `software_client_id`, `org_id`, the exact `software_redirect_uris`, and the `software_roles` (AISP/PISP/CBPII) you met in 4.1. Your `/register` endpoint's job is narrow and mechanical: prove the SSA was really signed by the Directory, lift the facts out of it, and create the corresponding Apigee objects. You are a relying party (the asymmetry from 4.1), not the authority.

The registration request itself is *also* a signed JWT — a registration request object that embeds the SSA in a `software_statement` claim and is signed with the TPP's own **OBSeal** key. So `/register` validates **two** signatures: the outer request object (proving the caller holds the key matching the SSA), and the inner SSA (proving the Directory vouched for that key). Only then does it provision.

!!! bridge "Spring Boot bridge"
    This is the *automated* form of the manual onboarding from 3.2. There, you ran `apigeecli developers create` / `apps create` by hand; here, the proxy does it for you on a verified request. The closest Spring shape is a self-service registration controller backed by an admin client of your authorization server:

    | Manual onboarding (3.2) | DCR (`/register`) |
    |---|---|
    | A human runs `apigeecli apps create` | `POST /register` provisions the App in-flow |
    | You trust the human's say-so | You trust the **SSA's JWS signature** from the OB Directory |
    | You pick the API Product | `software_roles` in the SSA selects the product (AISP → `aisp-read`) |
    | You email back the `consumerKey` | The response body returns `client_id` per RFC 7591 |
    | Spring: `@PostMapping("/register")` calling `RegisteredClientRepository.save(...)` | The proxy calling the Apigee management API to create a developer app |

!!! breaks "Where the analogy breaks"
    A Spring self-registration controller usually mints *its own* trust: the user proves who they are with a password or an email link you control, and you decide whether to accept them. DCR inverts this — you accept a client you have never seen because a *third party* (the OB Directory) signed an assertion about it, and you are legally obliged to honour that assertion. There is no "approve this registration" step you own; the approval already happened off-platform. Equally, the App you create is not a record you may freely edit — its reachable surface (`software_roles`) and its `redirect_uris` are dictated by the SSA, not by your business rules. Treating `/register` like a normal sign-up form, where you get to vet and shape the account, is the mistake.

## The concept

Registration is a validate-then-provision pipeline. The proxy never reaches a backend — it *is* the backend. It verifies the inner SSA against the Directory's published JWKS, extracts the claims, calls the Apigee management API to create the Developer and App bound to the role-appropriate product, and returns the RFC 7591 client information response.

```widget
{
  "type": "sequence",
  "title": "DCR: a signed SSA becomes a developer app",
  "actors": [
    {"id": "t", "label": "TPP"},
    {"id": "p", "label": "/register (Apigee)"},
    {"id": "d", "label": "OB Directory JWKS"},
    {"id": "m", "label": "apigee.googleapis.com"}
  ],
  "steps": [
    {"from": "t", "to": "p", "label": "POST /register  (signed reg request → software_statement: SSA)", "note": "Body is a JWS registration request object signed with the TPP's OBSeal key, embedding the Directory-signed SSA."},
    {"from": "p", "to": "p", "label": "VerifyJWT(request object, OBSeal)", "note": "Prove the caller holds the key the SSA was issued for — the outer signature."},
    {"from": "p", "to": "d", "label": "fetch Directory signing keys", "note": "VerifyJWT pulls the OB Directory JWKS to validate the inner SSA."},
    {"from": "d", "to": "p", "kind": "return", "label": "JWKS (Directory public keys)", "note": "Cached; the trust anchor for every TPP's SSA."},
    {"from": "p", "to": "p", "label": "VerifyJWT(SSA) → extract software_roles, redirect_uris, org_id", "note": "Inner signature valid → lift the vetted facts out of the assertion."},
    {"from": "p", "to": "m", "label": "create Developer + App, bind aisp-read product", "note": "ServiceCallout (or apigeecli in the lab) provisions the 3.2 chain from inside the proxy."},
    {"from": "m", "to": "p", "kind": "return", "label": "App created (consumerKey = client_id)", "note": "The management API returns the new app's credentials."},
    {"from": "p", "to": "t", "kind": "return", "label": "201  { client_id, redirect_uris, software_roles, scope }", "note": "RFC 7591 client information response — the TPP can now request tokens."}
  ]
}
```

The Developer → App → API Product chain you built by hand in 3.2 is exactly what this produces; DCR just provisions it from a signed assertion instead of a console session. The same entitlement chain, automated:

<figure class="svg-figure">
<img src="assets/svg/entitlement-chain.svg" alt="A Developer owns an App; the App is granted an API Product exposing specific proxy operations; the App's credentials become the client_id.">
<figcaption>DCR creates this chain automatically. The SSA's <code>software_roles</code> decide <b>which API Product</b> the new App is bound to — AISP → the read product, PISP → the payments product.</figcaption>
</figure>

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — build a /register endpoint that validates an SSA and provisions an app

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; the OB CA truststore from 4.1 and the `aisp-read` API Product from 3.2 already in place. A sample SSA (a JWS) from 4.1's Directory exercise, here as `$SSA`. A proxy named `dcr` serving `/register`.

**1. Verify the inner SSA against the Directory JWKS.** The Directory publishes its signing keys; **VerifyJWT** validates the SSA's signature and surfaces its claims as flow variables. Put this in `apiproxy/policies/VJWT-SSA.xml`:

```xml
<VerifyJWT name="VJWT-SSA">
  <Algorithm>PS256</Algorithm>
  <!-- The SSA arrives in the registration request's software_statement claim -->
  <Source>jwt.VJWT-RegRequest.claim.software_statement</Source>
  <PublicKey>
    <JWKS uri="https://keystore.openbanking.example/keystore/openbanking.jwks"/>
  </PublicKey>
  <Issuer>OpenBanking Ltd</Issuer>
</VerifyJWT>
```

**2. Extract the vetted facts** the SSA carries — these decide who the App is and what it may reach. After `VJWT-SSA` runs, the claims are available as `jwt.VJWT-SSA.claim.*`:

```text
jwt.VJWT-SSA.claim.software_client_id        → becomes the developer-app name
jwt.VJWT-SSA.claim.org_id                    → the owning TPP org (the Developer)
jwt.VJWT-SSA.claim.software_redirect_uris    → callback URLs (exact-match later, per 4.3)
jwt.VJWT-SSA.claim.software_roles            → ["AISP"] → bind aisp-read; ["PISP"] → pisp-payments
```

**3. Select the API Product from the role.** A condition maps `software_roles` onto a product — the App's reachable surface is the role, not your choice. In the request flow:

```xml
<AssignMessage name="AM-SelectProduct">
  <AssignVariable>
    <Name>dcr.product</Name>
    <Value>aisp-read</Value>
  </AssignVariable>
  <!-- if the SSA asserts PISP, swap to the payments product instead -->
</AssignMessage>
```

**4. Provision the App via the management API.** Inside the proxy you'd use a **ServiceCallout** to `apigee.googleapis.com` (authenticated with a service-account token from a 2.7 KVM). In the lab, prove the same provisioning with `apigeecli`, driven by the SSA's claims:

```bash
# values you would pull from the verified SSA claims at runtime
ORG_ID="0014H00001lFmRtQAK"
SW_CLIENT_ID="acme-budgeting-001"

# Developer == the TPP org from the SSA
apigeecli developers create \
  --email "$ORG_ID@tpp.openbanking" --first Acme --last TPP --user "$ORG_ID" \
  --org "$ORG" --token "$TOKEN"

# App == the software, bound to the role-selected product, name == software_client_id
apigeecli apps create \
  --name "$SW_CLIENT_ID" --email "$ORG_ID@tpp.openbanking" --prods aisp-read \
  --org "$ORG" --token "$TOKEN"
```

**5. Return the RFC 7591 client information response.** The App's `consumerKey` *is* the `client_id`. Shape the response from the created app plus the SSA facts:

```xml
<AssignMessage name="AM-RegResponse">
  <Set>
    <StatusCode>201</StatusCode>
    <Payload contentType="application/json">{
  "client_id": "{servicecallout.SC-CreateApp.response.credentials.0.consumerKey}",
  "client_id_issued_at": {system.timestamp},
  "redirect_uris": {jwt.VJWT-SSA.claim.software_redirect_uris},
  "software_statement": "{jwt.VJWT-RegRequest.claim.software_statement}",
  "scope": "accounts",
  "token_endpoint_auth_method": "private_key_jwt"
}</Payload>
  </Set>
</AssignMessage>
```

**6. Deploy, register, and read the created app back:**

```bash
apigeecli apis create bundle --name dcr --proxy-folder ./dcr/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name dcr --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

# register with a signed registration request (Content-Type per RFC 7591)
curl -s -X POST "https://$RUNTIME_HOST/dcr/register" \
  -H "Content-Type: application/jwt" --data "$REG_REQUEST_JWT" | jq .

# read back the developer app that DCR just created
apigeecli apps get --name acme-budgeting-001 --email "$ORG_ID@tpp.openbanking" \
  --org "$ORG" --token "$TOKEN" | jq '{name, credentials: .credentials[0].apiProducts}'
```

**What success looks like:** the `POST /register` returns `201` with a `client_id`, and `apigeecli apps get` shows a brand-new developer app bound to `aisp-read` that did not exist before the call — provisioned entirely from the verified SSA, no human in the loop.
</div>

## Verify it

The decisive checks are signature and provisioning. Tamper with one byte of the SSA payload and re-`POST`: `VerifyJWT` must reject it with a `401`/`400` and **no app is created** — verify by confirming `apigeecli apps get` still returns `404` for that `software_client_id`. On a valid registration, the returned `client_id` should equal the `consumerKey` you read back with `apigeecli apps get`, and the app's bound product should match the SSA's `software_roles` (an AISP-only SSA must produce an app on `aisp-read`, never `pisp-payments`). In a Trace, confirm `jwt.VJWT-SSA.claim.software_roles` and `jwt.VJWT-SSA.claim.software_redirect_uris` are populated *before* the provisioning callout fires.

!!! failure "Common failure modes"
    - **Validating only the outer request object, not the SSA.** The caller's signature proves they hold a key, not that the OB Directory vouched for it. Symptom: any self-signed SSA registers. Both signatures must pass — outer with the TPP's OBSeal, inner against the Directory JWKS.
    - **Provisioning before verification.** Creating the app, then checking the signature. Symptom: invalid registrations leave orphan apps behind. The management-API callout must be *downstream* of every `VerifyJWT`.
    - **Ignoring `software_roles` and binding everything to one product.** Symptom: an AISP-only TPP ends up able to call payment paths. The product selection must be driven by the role claim, per 4.1.
    - **Re-registering creates duplicates.** A second `POST` for the same `software_client_id` errors or clones. Symptom: `apps create` fails on conflict. Treat repeat registration as an update (RFC 7592), or make the operation idempotent on the app name.
    - **Stale or wrong Directory JWKS URI.** Pointing `VerifyJWT` at the wrong keystore host. Symptom: every SSA fails signature validation. Use the Directory's published JWKS endpoint and let Apigee cache it.

!!! stretch "Stretch goal"
    Take a real sample SSA from 4.1, drive a single `POST /register` through your proxy, and then read the created developer app back with `apigeecli apps get` — confirm the `client_id` in the response equals the app's `consumerKey` and the bound product matches the SSA's `software_roles`. Then add the read-side of RFC 7592: a `GET /register/{client_id}` that returns the current client configuration by reading the app back through the management API, so a TPP can introspect its own registration the same way it created it.

## Recap & next

You replaced the manual onboarding of 3.2 with a standards-based `/register` endpoint. It validates the registration request object **and** the embedded SSA's JWS signature against the OB Directory JWKS, lifts out `software_roles` and `software_redirect_uris`, provisions the **Developer → App → API Product** chain from inside the proxy via the management API, and returns an RFC 7591 client information response carrying the `client_id`. A vetted TPP now self-onboards in one signed call, with no human in the loop and no trust you had to mint yourself.

**Next — 5.2:** the TPP has a client and can get tokens — but it still can't touch a customer's data until the customer agrees. You'll build the **account-access consent** as a stateful resource with its own lifecycle (AwaitingAuthorisation → Authorised → Revoked), persisted in a KVM and enforced at the gateway — the gateway's answer to a JPA entity state machine.
