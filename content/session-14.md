# 3.2 — API Products, Apps, Developers & keys

!!! bottomline "Bottom line"
    Before you can authorize a call you must know *which consumer* makes it. Apigee models that with a chain — **Developer → App → API Product → Proxy** — and the **API Product**, not the proxy, is the unit of access. By the end you can build the chain, enforce it with **VerifyAPIKey**, and drive a quota from the product. This is the model OAuth and Open Banking sit on top of, so it never goes away.

## Why this exists

In a Spring service, "who is calling?" usually means an API-key table you built, or an OAuth client registry, plus some notion of *what plan/scopes that client has*. You wired those together yourself. Apigee gives you that whole apparatus as first-class objects — and crucially, it separates **identity** (who) from **entitlement** (what they're allowed), so changing a customer's plan is a config edit, not a redeploy.

The non-obvious part — and the part worth slowing down for — is that an app is **never granted a proxy directly**. It's granted an **API Product**, and the product decides which proxies, which paths and methods, which environments, plus the quota and OAuth scopes. The product is the unit of access control.

!!! bridge "Spring Boot bridge"
    There's **no clean Spring equivalent** — that's exactly why this session exists. The closest mental model is two things you'd otherwise build by hand and glue together:

    - an **OAuth client registry** (Spring Authorization Server's `RegisteredClient`) — the **App**, with its `consumerKey` / `consumerSecret`;
    - an **entitlements / plans table** — the **API Product**, bundling allowed operations + quota + scopes.

    Apigee ships both, already wired, with **VerifyAPIKey** as the enforcement filter. If you've ever wished your `RegisteredClient` also carried "and this client may call these endpoints at this rate," that's an API Product.

!!! breaks "Where the analogy breaks"
    Spring's authorization is usually **role/scope-centric**: a token has scopes, an endpoint requires them, done. Apigee's product model is **entitlement-centric and indirection-heavy**: the app's reachable surface is computed from the *product* it's bound to, not from anything on the app itself. Two apps with identical credentials-shape can have completely different reach because they hold different products. Don't look for "the app's permissions" — look at the **product**.

## The concept

<figure class="svg-figure">
<img src="assets/svg/entitlement-chain.svg" alt="Developer owns an App; the App is granted an API Product; the Product exposes specific Proxy operations; the App's credentials mint a token.">
<figcaption>The entitlement chain. The <b>API Product</b> in the centre is the unit of access — everything to its right is "what's reachable," everything to its left is "who's asking."</figcaption>
</figure>

In objects:

```text
Developer (a person/org: tpp-acme@example.com)
└── App  (a registered client: "Acme Budgeting App")
    ├── consumerKey / consumerSecret      ← the credentials
    └── is granted one or more →
        API Product ("AISP Read")
        └── bundles: proxy operations + quota + scopes + environments
```

When a request arrives with a key, **VerifyAPIKey** walks this chain backwards: key → app → products → *is the called operation in any granted product, in this environment?* If yes, it loads a pile of context variables you'll use downstream.

```widget
{
  "type": "sequence",
  "title": "A keyed request through the chain",
  "actors": [
    {"id": "c", "label": "Client app"},
    {"id": "p", "label": "Apigee proxy"},
    {"id": "r", "label": "Product registry"}
  ],
  "steps": [
    {"from": "c", "to": "p", "label": "GET /accounts  x-api-key: ABC", "note": "The app sends its consumerKey as the API key."},
    {"from": "p", "to": "r", "label": "VerifyAPIKey(ABC)", "note": "Proxy looks up the key → app → granted products."},
    {"from": "r", "to": "p", "kind": "return", "label": "app, product, quota, scopes", "note": "Is /accounts GET allowed by a granted product in this env? Yes → return entitlement context."},
    {"from": "p", "to": "p", "label": "populate verifyapikey.* vars", "note": "client_id, apiproduct.name, developer.email, quota.limit … now available to later policies."},
    {"from": "p", "to": "c", "kind": "return", "label": "200 (or 401 if key invalid)", "note": "Identity established; quota and routing can now key off the product."}
  ]
}
```

## Hands-on lab — gate a proxy on app identity

<div class="lab" markdown="1">
#### Lab — build the chain, then enforce it

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported, and a deployed proxy named `aisp-accounts` (reuse your passthrough, renamed, or any proxy serving `/accounts`).

**1. An API Product** — the unit of access. Scope it to *specific* paths and methods, not the whole proxy:

```bash
apigeecli products create \
  --name aisp-read --displayName "AISP Read" --approval auto \
  --envs "$ENV" --scopes "accounts" \
  --quota 1000 --interval 1 --unit day \
  --opgrp '{"operationConfigs":[{"apiSource":"aisp-accounts","operations":[{"resource":"/accounts","methods":["GET"]},{"resource":"/accounts/**","methods":["GET"]}]}]}' \
  --org "$ORG" --token "$TOKEN"
```

**2. A Developer** (the owning person/org):

```bash
apigeecli developers create \
  --email tpp-acme@example.com --first Acme --last Fintech --user acme \
  --org "$ORG" --token "$TOKEN"
```

**3. An App bound to the product** — then read back its credentials:

```bash
apigeecli apps create \
  --name acme-budgeting --email tpp-acme@example.com --prods aisp-read \
  --org "$ORG" --token "$TOKEN"

apigeecli apps get --name acme-budgeting --email tpp-acme@example.com \
  --org "$ORG" --token "$TOKEN" | jq '.credentials[0]'
# → { "consumerKey": "....", "consumerSecret": "....", "apiProducts":[{"apiproduct":"aisp-read"}] }
```

Grab the `consumerKey` — that's the API key the client sends.

**4. Enforce with VerifyAPIKey** in the ProxyEndpoint request PreFlow (point ① from session 2.1), reading the key from a header:

```xml
<VerifyAPIKey name="VK-Key">
  <APIKey ref="request.header.x-api-key"/>
</VerifyAPIKey>
```

On success Apigee populates rich context you can use downstream:

```text
verifyapikey.VK-Key.client_id                                → the consumerKey
verifyapikey.VK-Key.apiproduct.name                          → which product authorized it
verifyapikey.VK-Key.developer.email                          → tpp-acme@example.com
verifyapikey.VK-Key.apiproduct.developer.quota.limit         → drive Quota from here ↓
```

**5. Make the quota product-driven** — attach `Q-PerApp` right after `VK-Key`. Now the limit lives on the *product*, not in the proxy:

```xml
<Quota name="Q-PerApp">
  <Allow countRef="verifyapikey.VK-Key.apiproduct.developer.quota.limit" count="1000"/>
  <Interval ref="verifyapikey.VK-Key.apiproduct.developer.quota.interval">1</Interval>
  <TimeUnit ref="verifyapikey.VK-Key.apiproduct.developer.quota.timeunit">day</TimeUnit>
  <Identifier ref="verifyapikey.VK-Key.client_id"/>
</Quota>
```

**6. Redeploy and test allow/deny:**

```bash
apigeecli apis create bundle --name aisp-accounts --proxy-folder ./aisp-accounts/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name aisp-accounts --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

KEY="<paste consumerKey>"
# no key → 401
curl -s -o /dev/null -w "no key:    %{http_code}\n" "https://$RUNTIME_HOST/aisp-accounts/accounts"
# valid key → 200
curl -s -o /dev/null -w "valid key: %{http_code}\n" -H "x-api-key: $KEY" "https://$RUNTIME_HOST/aisp-accounts/accounts"
```

**What success looks like:** `no key: 401` and `valid key: 200`. Then change the customer's plan by editing the **product's** quota and redeploying *nothing* — the proxy picks up the new limit because it reads `countRef` from the product. That separation is what Open Banking and monetization both rely on.
</div>

!!! verify "Verify it"
    - Call `/accounts` with a `POST` instead of `GET`: you get **401** even with a valid key, because the product's operation group only granted `GET`. Entitlement is path *and* method.
    - In Trace, confirm `Q-PerApp` reports a limit of 1000 sourced from `apiproduct.developer.quota.limit` — not a hard-coded value.

## Common failure modes

!!! failure "Entitlement-chain mistakes"
    - **Granting the whole proxy.** A product with no operation group exposes *everything* the proxy serves. Always scope to paths + methods. *(Symptom: a key meant for `/accounts` also reaches `/admin`.)*
    - **Hard-coding the quota in the proxy.** Then every plan change is a redeploy. Drive `Quota` from `countRef` so the product owns the number.
    - **Looking for permissions on the app.** Reach is on the **product** the app holds, not the app. Two apps differ because their products differ.
    - **Forgetting the environment.** A product lists which environments it's valid in. A key that works in `eval` legitimately 401s in `prod` if the product doesn't include `prod`.

```widget
{
  "type": "quiz",
  "title": "Check yourself",
  "questions": [
    {
      "q": "An app needs access to two proxies' specific endpoints. Where do you define that?",
      "options": ["On the app, as a permissions list", "In an API Product's operation group, then grant the product to the app", "In the proxy XML, per consumerKey", "In a Spring SecurityFilterChain"],
      "answer": 1,
      "explain": "The API Product's operation group bundles the allowed proxy/path/method set; the app is granted the product. The product is the unit of access."
    },
    {
      "q": "Why drive Quota from countRef instead of a fixed count?",
      "options": ["It's faster at runtime", "So plan changes are a product edit, not a proxy redeploy", "countRef is required by FAPI", "Fixed counts don't work with VerifyAPIKey"],
      "answer": 1,
      "explain": "countRef reads the limit from the product via the verifyapikey.* variables, so changing a customer's plan never touches the proxy."
    },
    {
      "q": "In OAuth / Open Banking, what Apigee object represents the OAuth *client*?",
      "options": ["The API Product", "The Developer", "The developer App", "The ProxyEndpoint"],
      "answer": 2,
      "explain": "The OAuth client is a developer App under the hood — its consumerKey/secret are the client_id/client_secret. The app-identity model never goes away; OAuth layers on top of it."
    }
  ]
}
```

## Stretch goal

!!! stretch "Stretch goal"
    Map your team's *current* API-client onboarding onto the chain: who is the Developer, what's the App, and what would the API Products be (one per plan/tier?). Then find the thing you build today that Apigee would let you delete — usually the bespoke key table *or* the per-client rate-limit config. Note what you'd have to trust the edge with to actually delete it.

## Recap & next

You can now explain why the **API Product** — not the proxy — is the unit of access, build the **Developer → App → Product** chain, read out credentials, enforce identity with **VerifyAPIKey**, and drive quotas from the product so plan changes never touch the proxy.

**Next — 3.3:** turn that app identity into bearer tokens. You'll make Apigee an **OAuth 2.0 token server** with the **OAuthV2** policy and the client-credentials grant — the role you'd otherwise stand up with Spring Authorization Server — and the same App you built here becomes the OAuth client.
