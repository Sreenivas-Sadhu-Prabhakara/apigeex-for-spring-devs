# 5.3 — AISP reads: accounts, balances & transactions

!!! bottomline "Bottom line"
    The OBIE Account Information (AIS) endpoints — `/accounts`, `/accounts/{AccountId}/balances`, `/accounts/{AccountId}/transactions` — look like ordinary read APIs, but every call is gated by a **consent**, not a role. By the end you'll expose them behind a proxy that verifies a FAPI access token, echoes the mandatory `x-fapi-*` headers, looks up the **Authorised** consent built in 5.2, and refuses any account the PSU never consented to. The shape of the data and the shape of the authorization are both prescribed — you implement the contract, you don't invent it.

## Why this exists

In a Spring service, a read endpoint is a `@GetMapping` plus a `@PreAuthorize("hasRole('...')")` or a scope check. Authorization there is almost always about *what kind of caller* you are — a role, a scope, an audience. Open Banking inverts that: the AISP (Account Information Service Provider) presenting the token is a *trusted, regulated* party, so "are you allowed to call `/accounts`?" is the easy part. The hard part is "*which* accounts, and *which* data on them, did this specific end user agree to share, and for how long?" That answer lives in a consent resource, not in the token's scopes.

So an AIS read is a two-stage authorization. Stage one is FAPI-level: a valid, sender-constrained access token carrying the `accounts` scope, with the required `x-fapi-interaction-id` and `x-fapi-auth-date` headers present. Stage two is consent-level: the token references a `ConsentId`, that consent must be in state **Authorised**, its `Permissions` array must include the permission the endpoint needs (`ReadBalances` for balances, `ReadTransactionsDetail` for transactions, and so on), and — critically — the `AccountId` in the path must be one the PSU actually selected during authorisation.

That second stage is where most real implementations leak. It is entirely possible to hold a perfectly valid token for consent `C-123` and use it to ask for an account that belongs to consent `C-456` or to nobody. The gateway, not the backend, is the right place to slam that door — because the backend is a dumb data source and the consent is an edge concern.

!!! bridge "Spring Boot bridge"
    The endpoints map cleanly onto controllers you've written; the *authorization model* does not.

    | Spring read API | OBIE AIS read |
    |---|---|
    | `@GetMapping("/accounts")` | `GET /aisp/accounts` |
    | `@PreAuthorize("hasScope('accounts')")` | VerifyAccessToken with scope `accounts` |
    | A role/authority on the principal | A **Permission** inside the Authorised consent |
    | `@PathVariable Long accountId` you trust | An `AccountId` you must **prove is in the consent** |
    | Filtering rows by `userId = principal.id` | Filtering by *the account set the PSU consented to* |

    The closest single Spring idea is a per-request, per-resource authorization check — a `PermissionEvaluator.hasPermission(auth, accountId, "read")` — except the "permission" is sourced from a stateful consent object the user signed off on, and it is enforced at the gateway before your service is ever called.

!!! breaks "Where the analogy breaks"
    A Spring scope is static and caller-shaped: once `hasRole('ACCOUNTS')` passes, every `/accounts` row the query returns is fair game, and the principal is the same yesterday and tomorrow. A consent is dynamic and resource-shaped: it enumerates *specific* account identifiers, it carries an expiry, it can be revoked mid-life by the PSU, and the very same token that worked an hour ago must start returning 403 the instant the consent flips out of **Authorised**. There is no "role" that does this. Reasoning about AIS reads as "scope-protected GETs" is exactly how people ship a proxy that happily serves account `22289` to a token that only ever consented to `31820`.

## The concept

A consent-scoped read is one happy path with two failure exits. The proxy must (1) verify the token and required FAPI headers, (2) resolve the `ConsentId` to the stored consent record, (3) check the consent is **Authorised**, carries the needed permission, and contains the requested `AccountId`, then (4) call the backend and shape an OBIE-flavoured response. Any one of those checks failing short-circuits to a `403` *before* the target is touched — the gateway is acting as the consent enforcement point.

Step through a single consented `GET /accounts/{AccountId}/balances` — click **Next** at each stage:

```widget
{
  "type": "sequence",
  "title": "A consent-scoped AIS read",
  "actors": [
    {"id": "a", "label": "AISP"},
    {"id": "p", "label": "Apigee proxy"},
    {"id": "k", "label": "Consent KVM"},
    {"id": "b", "label": "ASPSP backend"}
  ],
  "steps": [
    {"from": "a", "to": "p", "label": "GET /aisp/accounts/22289/balances", "note": "Bearer token + x-fapi-interaction-id + x-fapi-auth-date. The token was minted against consent C-AAC-77 in session 5.2."},
    {"from": "p", "to": "p", "label": "VerifyAccessToken(scope=accounts)", "note": "FAPI stage. Reject 401 if the token is invalid/expired or lacks the accounts scope. Required x-fapi-* headers must be present."},
    {"from": "p", "to": "k", "label": "lookup ConsentId from token", "note": "The token carries the ConsentId; fetch the stored consent record from the KVM written in 5.2."},
    {"from": "k", "to": "p", "kind": "return", "label": "{Status:Authorised, Permissions:[...], accounts:[22289,31820]}", "note": "Consent stage. Must be Authorised, must include ReadBalances, and 22289 must be in the consented account set."},
    {"from": "p", "to": "b", "label": "GET /balances/22289", "note": "All checks passed. Only now is the backend called — and only for an account inside the consent."},
    {"from": "b", "to": "p", "kind": "return", "label": "raw balance", "note": "Backend is a dumb data source; it knows nothing about consent."},
    {"from": "p", "to": "a", "kind": "return", "label": "200 OBIE Data.Balance[...] + echoed x-fapi-interaction-id", "note": "Response shaped to the OBIE schema; the interaction id is echoed for end-to-end traceability."}
  ]
}
```

!!! pitfall "Watch out"
    A valid `accounts`-scoped token is **stage one only** — it never authorises a specific account. The token scope and the consent's `Permissions` are two independent gates, and **both** must pass: the scope says "this caller may use AIS", the consent says "*these* accounts, *these* permissions, while Authorised". Treat the token alone as sufficient and you ship a proxy that serves any account to any valid token.

The mandatory headers are non-negotiable in FAPI: `x-fapi-interaction-id` is a client-supplied UUID you **echo back unchanged** so a call can be correlated across the four-party chain, and `x-fapi-auth-date` records when the PSU last authenticated. Their absence is a contract violation, not a soft warning.

!!! pitfall "Watch out"
    Echo `x-fapi-interaction-id` back **byte-for-byte** — it's client-supplied, not yours to mint. Generating a fresh UUID for the response (or dropping it) silently breaks end-to-end correlation and fails conformance, even though the call otherwise "works". The id you return must equal the id you received, unchanged.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — expose AIS reads gated by token + consent + FAPI headers

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; the OAuth token server from Part 3 issuing tokens with an `accounts` scope; and the **Authorised** consent from 5.2 stored in a KVM. We'll mock the backend so the focus stays on enforcement.

**1. Seed a consent in a KVM** (this is the record 5.2 produced). The key is the `ConsentId`; the value is the OBIE consent state:

```bash
apigeecli kvms entries create --map ob-consents \
  --key "urn-alphabank-aac-C-AAC-77" \
  --value '{"Status":"Authorised","Permissions":["ReadAccountsDetail","ReadBalances","ReadTransactionsDetail"],"accounts":["22289","31820"],"ExpirationDateTime":"2026-12-31T00:00:00Z"}' \
  --env "$ENV" --org "$ORG" --token "$TOKEN"
```

**2. Verify the token and require the FAPI headers** in the ProxyEndpoint request PreFlow. VerifyAccessToken enforces the scope; a RaiseFault guards the mandatory headers:

```xml
<VerifyAccessToken name="VA-Token">
  <Scope>accounts</Scope>
</VerifyAccessToken>
```
```xml
<!-- RF-RequireFapi: 400 if either FAPI header is missing -->
<RaiseFault name="RF-RequireFapi">
  <FaultResponse>
    <Set>
      <StatusCode>400</StatusCode>
      <Payload contentType="application/json">{"ErrorCode":"UK.OBIE.Header.Missing","Message":"x-fapi-interaction-id and x-fapi-auth-date are required"}</Payload>
    </Set>
  </FaultResponse>
</RaiseFault>
```

Attach the fault behind a condition so it only fires when a header is absent:

```xml
<Step>
  <Name>RF-RequireFapi</Name>
  <Condition>request.header.x-fapi-interaction-id = null or request.header.x-fapi-auth-date = null</Condition>
</Step>
```

**3. Load the consent and enforce the three consent-level checks.** Pull the `ConsentId` off the verified token (it rides in a custom claim/attribute), read the KVM, then parse and assert:

```xml
<KeyValueMapOperations name="KVM-Consent" mapIdentifier="ob-consents">
  <Get assignTo="consent.json"><Key><Parameter ref="accesstoken.consent_id"/></Key></Get>
</KeyValueMapOperations>
```
```xml
<!-- JS-CheckConsent: parse the JSON and set boolean flags for the conditions below -->
<Javascript name="JS-CheckConsent" timeLimit="200">
  <ResourceURL>jsc://checkConsent.js</ResourceURL>
</Javascript>
```

In `checkConsent.js`, set the flags the proxy will branch on — Status, the permission this path needs, and account membership:

```javascript
var c = JSON.parse(context.getVariable("consent.json") || "{}");
var accountId = context.getVariable("accountid");        // extracted from the path
var needed   = context.getVariable("required.permission"); // e.g. ReadBalances
context.setVariable("consent.authorised", c.Status === "Authorised");
context.setVariable("consent.hasPermission",
    (c.Permissions || []).indexOf(needed) !== -1);
context.setVariable("consent.coversAccount",
    (c.accounts || []).indexOf(accountId) !== -1);
```

!!! pitfall "Watch out"
    All three flags — `consent.authorised`, `consent.hasPermission`, `consent.coversAccount` — must be checked together; passing any one is not enough. A token for consent `C-AAC-77` can legitimately verify, hold `ReadBalances`, and still be asking for account `99999` that lives in someone else's consent. The `coversAccount` membership test on the path's `AccountId` is the gate most implementations forget, and it's the one that prevents cross-consent account leakage.

**4. Reject anything that fails any check** with an OBIE-shaped `403`:

```xml
<Step>
  <Name>RF-Forbidden</Name>
  <Condition>consent.authorised != true or consent.hasPermission != true or consent.coversAccount != true</Condition>
</Step>
```

**5. Shape an OBIE response** for the happy path. AssignMessage builds the `Data.Account[...]` envelope and echoes the interaction id:

```xml
<AssignMessage name="AM-AccountsResponse">
  <Set>
    <Headers><Header name="x-fapi-interaction-id">{request.header.x-fapi-interaction-id}</Header></Headers>
    <Payload contentType="application/json">{"Data":{"Account":[{"AccountId":"22289","Currency":"GBP","AccountType":"Personal","AccountSubType":"CurrentAccount","Nickname":"Everyday","Account":[{"SchemeName":"UK.OBIE.SortCodeAccountNumber","Identification":"30040422289","Name":"Mr A Smith"}]}]},"Links":{"Self":"https://{request.header.host}/aisp/accounts"},"Meta":{"TotalPages":1}}</Payload>
  </Set>
</AssignMessage>
```

**6. Deploy and test the deny path** — ask for an account that is *not* in the consent (`99999`):

```bash
apigeecli apis deploy --name aisp-accounts --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"
IID=$(uuidgen)
# consented account → 200
curl -s -o /dev/null -w "consented:    %{http_code}\n" \
  -H "Authorization: Bearer $AT" -H "x-fapi-interaction-id: $IID" \
  -H "x-fapi-auth-date: $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "https://$RUNTIME_HOST/aisp/accounts/22289/balances"
# non-consented account → 403
curl -s -o /dev/null -w "non-consented: %{http_code}\n" \
  -H "Authorization: Bearer $AT" -H "x-fapi-interaction-id: $IID" \
  -H "x-fapi-auth-date: $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "https://$RUNTIME_HOST/aisp/accounts/99999/balances"
```

**What success looks like:** `consented: 200` returns OBIE `Data.Account[...]` JSON with the request's `x-fapi-interaction-id` echoed verbatim in the response headers; `non-consented: 403` is rejected at the gateway — the mock backend is never called for account `99999`, which you can confirm in Trace.
</div>

## Verify it

Pull the full headers on the consented call with `curl -i` and confirm the response carries the **same** `x-fapi-interaction-id` you sent — byte-for-byte. If it differs or is missing, your AssignMessage isn't echoing `request.header.x-fapi-interaction-id`. Then drop the `x-fapi-auth-date` header entirely and re-run: you should get `400 UK.OBIE.Header.Missing`, proving the FAPI guard fires independently of the consent logic.

Open Trace for both the `22289` and `99999` calls. On the consented call you'll see the TargetEndpoint request flow execute; on the non-consented call the flow stops at `RF-Forbidden` and the backend step never runs — that gap is the proof the consent is enforced at the edge, not behind it. Finally, edit the KVM entry to flip `Status` to `Revoked` and re-run the consented call: it must now return `403` with no code change, demonstrating the live, stateful nature of consent.

!!! failure "Common failure modes"
    - **Treating scope as the whole story.** A valid `accounts`-scoped token passes VerifyAccessToken but says nothing about *which* accounts. Symptom: any token reads any account — the `coversAccount` check is missing or never wired into a condition.
    - **Not echoing `x-fapi-interaction-id`.** Generating a fresh UUID, or dropping it, breaks end-to-end correlation and fails conformance. Symptom: the AISP's logs and yours can't be joined; the response id never matches the request id.
    - **Wrong permission for the endpoint.** Serving transactions while only checking `ReadBalances` (or not checking permissions at all). Symptom: a `ReadBalances`-only consent successfully reads transaction detail.
    - **Enforcing consent in the backend.** If the mock target is what returns 403, an attacker who reaches the target directly bypasses it. Symptom: Trace shows the backend executing for a non-consented account.
    - **Stale consent reads.** Caching the consent JSON too aggressively means a just-revoked consent still serves data. Symptom: a revoked consent keeps returning 200 until a cache TTL expires.

!!! stretch "Stretch goal"
    Tighten the account check from "is this `AccountId` in the consent" to "*every* account this request could touch is in the consent." For the bulk `GET /aisp/accounts` (no `{AccountId}` in the path), don't just authorize the call — **filter the returned `Data.Account[]`** down to exactly the consented account set, so a consent for two accounts can never surface a third even in a list response. Then write the negative test that proves a token for `[22289, 31820]` returns a two-element array and never leaks account `99999`, even though the backend would happily return all three.

## Recap & next

You can now stand up the OBIE AIS reads — `/accounts`, `/balances`, `/transactions` — as consent-scoped endpoints: VerifyAccessToken plus required `x-fapi-*` headers for the FAPI stage, a KVM-resolved consent for the authorization stage, and a hard `403` at the gateway for any account, permission, or status the PSU never granted. The authorization is resource-shaped and stateful, not role-shaped — the single biggest mental shift from a Spring `@PreAuthorize` GET.

**Next — 5.4:** the write side. You'll build the PISP **domestic-payment-consent** and **payment submission** flow, where the new hazard isn't *who can read* but *making sure a retried POST doesn't pay twice* — enforced with the `x-idempotency-key` header at the gateway.
