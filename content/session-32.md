# 6.4 — Productisation, monetization & API hub

!!! bottomline "Bottom line"
    An endpoint that works is not yet a *product*. Apigee's productisation layer turns your proxies into consumable, governed, sellable units: an **API product** bundles operations into a thing developers subscribe to, a **developer portal** publishes its OpenAPI docs so a TPP can self-serve a key, **monetization** attaches a rate plan (free / tiered / per-call), and **API hub** catalogues every API across the org for governance. There is no Spring analogue for any of this — it's the business-and-governance wrapper around the technology you've already built.

## Why this exists

Everything to this point has been engineering: proxies, policies, security, CI/CD, observability. None of it answers the questions a real API programme actually runs on — *how does an outside developer discover this API, read its docs, agree to terms, and get a working credential without emailing you?* And *how do you charge for it, or at least cap and tier it, per customer?* In Spring you'd hand-build a signup page, a docs site, a key-issuing endpoint, and a billing integration — four bespoke systems glued to your service. Apigee ships them as platform features that sit on top of the entitlement chain you already know.

The **API product** is the hinge, and you met it in 3.2 as the unit of *access*. Here it does a second job: it's also the unit of *packaging and monetization*. The same object that decides "this app may call `/accounts` GET at 1000/day" is the thing a developer subscribes to in a portal and the thing a rate plan prices. One concept, three roles — access control, packaging, and pricing — which is why getting the product boundaries right matters far more than it first appears.

The **developer portal** is the self-service front door. You publish a product plus its OpenAPI spec; the portal renders human-readable reference docs and a signup flow, so a third party registers an app and receives a `consumerKey` *without you in the loop*. **Monetization** layers rate plans onto products — free tiers, tiered volume pricing, per-call charges — with billing and reporting. And **API hub** is the org-wide catalogue: every API (Apigee-managed or not) registered with its metadata, lifecycle stage, and governance attributes, so a large organisation can find, standardise, and govern its whole API estate. The lab focuses on the first two; monetization and API hub are awareness-level.

!!! bridge "Spring Boot bridge"
    This is the rare session where the honest mapping is *there isn't one*. The closest fragments in the Spring world are tools you'd assemble yourself, and none of them is the product/monetization concept:

    | What you'd build in the Spring world | Apigee X feature | Why it's not really the same |
    |---|---|---|
    | springdoc-openapi serving `/v3/api-docs` + Swagger UI | OpenAPI spec published to the **developer portal** | The portal adds signup, key issuance, and access terms, not just rendering |
    | A hand-rolled "request an API key" form + admin approval | **Developer portal** self-service registration | Issues a real credential bound to a product, with approval workflow |
    | A custom usage-metering + Stripe billing integration | **Monetization** rate plans | First-class tiers/quotas/billing wired to the product, not bespoke code |
    | A spreadsheet or wiki listing your services | **API hub** catalogue | Governed metadata, lifecycle, and discovery across the whole org |

    The takeaway: productisation is a *business and governance* layer. Spring gives you the runtime; it deliberately has nothing to say about packaging your runtime into something a stranger can buy and self-serve.

!!! breaks "Where the analogy breaks"
    springdoc makes people reach for the portal as "just hosted Swagger UI" — and that misses the point entirely. The portal's reason to exist is not documentation; it's the **self-service trust boundary**: an unknown developer agrees to terms, registers an app, and walks away with a working, product-scoped credential, all without a human. Swagger UI renders a spec; it never issues you a key bound to a quota and a set of allowed operations. Likewise monetization is not a billing plugin you could swap in — the rate plan is anchored to the *product*, so changing what a customer can do and what they pay for is one governed edit in the same place that controls their access. The analogy breaks because Spring has no notion of an endpoint as a *commercial, self-serviceable unit*; here that's the whole subject.

## The concept

The product is the unit of access *and* the unit of packaging and monetization. The same entitlement chain you enforce at runtime is what a developer subscribes to in the portal and what a rate plan prices — so the picture from 3.2 is exactly the picture here, read commercially:

<figure class="svg-figure">
<img src="assets/svg/entitlement-chain.svg" alt="Developer owns an App; the App is granted an API Product; the Product exposes specific Proxy operations and now also carries the rate plan and portal listing.">
<figcaption>The entitlement chain, read as packaging. The <b>API product</b> is simultaneously the access boundary (right), the thing a developer self-serves in the <b>portal</b> (left), and the thing a <b>rate plan</b> prices. One object, three jobs.</figcaption>
</figure>

A rate plan attaches tiers to a product. A typical AISP shape:

| Tier | Monthly fee | Included calls/day | Overage | Typical consumer |
|---|---|---|---|---|
| **Free / Sandbox** | £0 | 1,000 | hard cap (429) | TPP evaluating the API |
| **Standard** | £99 | 50,000 | £0.001 / call | a small budgeting app in production |
| **Partner** | negotiated | custom | per contract | a regulated bank partner |

Those tiers map straight onto the `Quota` you already drive from the product (3.2) — monetization adds the *pricing and billing* on top of the *limit* you can already enforce. The portal, meanwhile, takes the product plus its OpenAPI spec and renders the developer-facing front door.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — productise the AISP API and publish it to a portal

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported, the deployed `aisp-accounts` proxy and the `aisp-read` product from 3.2, and an OpenAPI 3 spec for the AISP API (write a minimal one below if you don't have it).

**1. Refine the API product** so it's portal-ready — a customer-facing display name and description, a published `productized` flag isn't needed, but quota and scopes should match the tier you intend to sell. Re-create or update `aisp-read`:

```bash
apigeecli products create \
  --name aisp-read --displayName "AISP Accounts (Read)" \
  --approval auto --envs "$ENV" --scopes "accounts" \
  --quota 1000 --interval 1 --unit day \
  --opgrp '{"operationConfigs":[{"apiSource":"aisp-accounts","operations":[{"resource":"/accounts","methods":["GET"]},{"resource":"/accounts/**","methods":["GET"]}]}]}' \
  --org "$ORG" --token "$TOKEN"
```

**2. A minimal OpenAPI spec** for the developer-facing docs. Save as `aisp-openapi.yaml`:

```yaml
openapi: 3.0.3
info:
  title: AISP Accounts API
  version: "1.0"
  description: Read-only access to a PSU's account list and balances (UK Open Banking AISP).
servers:
  - url: https://RUNTIME_HOST/aisp-accounts
security:
  - apiKey: []
paths:
  /accounts:
    get:
      summary: List the PSU's accounts
      responses:
        "200": {description: A list of authorised accounts}
        "401": {description: Missing or invalid API key}
components:
  securitySchemes:
    apiKey:
      type: apiKey
      in: header
      name: x-api-key
```

**3. Create a developer portal** and register the spec. Apigee provides an *integrated* portal per org; create one and attach an API documentation entry sourced from your spec:

```bash
# create the portal (sites) for this org
apigeecli sites create --name aisp-portal \
  --org "$ORG" --token "$TOKEN"

# publish the OpenAPI spec into the spec store
apigeecli spec create --name aisp-accounts \
  --file ./aisp-openapi.yaml --org "$ORG" --token "$TOKEN"
```

Then in the Apigee UI under **Publish → Portals → aisp-portal → API catalog**, add a catalog item: select the **aisp-read** product, attach the **aisp-accounts** spec as its reference docs, mark it **Published** and **visible to anonymous users** (or registered users), and enable **self-service key registration**. (The console flow is the supported path for catalog visibility and theming; the CLI seeds the spec and product the catalog item points at.)

**4. Draft a rate plan (awareness — console).** Under **Monetization → Rate plans**, create a plan against `aisp-read` with a Free tier (1,000 calls/day, hard cap) and a Standard tier (50,000/day, per-call overage), matching the table above. No billing account is required to *draft* the plan; publishing it is what makes it purchasable.

**5. Verify the self-service path** by walking it as a developer would: open the portal URL (shown in the portal's settings), register a developer account, create an app against **AISP Accounts (Read)**, and copy the issued key. Then call the live API with it:

```bash
KEY="<key self-served from the portal>"
curl -s -o /dev/null -w "portal key: %{http_code}\n" \
  -H "x-api-key: $KEY" -H "x-fapi-interaction-id: $(uuidgen)" \
  "https://$RUNTIME_HOST/aisp-accounts/accounts"
```

**What success looks like:** the **AISP Accounts (Read)** product appears in the portal with rendered OpenAPI docs; a developer can self-register, create an app, and receive a `consumerKey` *without any action from you*; and that key returns `200` from the live proxy — proving the portal-issued credential is the same product-scoped key your `VerifyAPIKey` enforces. A draft rate plan exists against the product, ready to publish when a billing account is attached.
</div>

## Verify it

The decisive test is the self-service loop with *you not involved*: a key minted through the portal must be a fully-fledged credential, not a placeholder. Confirm it by inspecting the app the portal created — `apigeecli apps list --org "$ORG" --token "$TOKEN"` should show the developer's app bound to `aisp-read`, and the key it issued is the same one that returned `200` above. That round-trip — portal signup to a live, product-scoped, quota-bound call — is the productisation layer working end to end.

For governance, register the API in **API hub** (Apigee's catalogue) and set its lifecycle stage and owner. Then confirm the rate plan is anchored to the product, not the proxy: the Free tier's 1,000/day cap is the *same* `Quota` your proxy already enforces from the product, so a customer's plan and a customer's access are one edit in one place — exactly the single-source-of-truth that makes the product the centre of gravity.

!!! failure "Common failure modes"
    - **Treating the portal as hosted Swagger.** You publish docs but never enable self-service registration, so a developer can read but not get a key. Symptom: "great docs, how do I actually call it?" Enable key registration on the catalog item.
    - **Product boundaries too coarse.** One giant product bundling AISP, PISP, and CoF can't be priced or tiered independently. Symptom: you can't offer a read-only free tier. Split products along the lines you'd sell and govern.
    - **Spec server URL wrong.** Leaving `RUNTIME_HOST` as a literal (or pointing at the backend) means the portal's "try it" calls hit the wrong host. Symptom: portal examples 404 or CORS-fail. Set the `servers.url` to your env-group hostname + base path.
    - **Publishing a rate plan with no billing account.** Drafting is free; *publishing* a monetized plan needs billing configured. Symptom: publish fails or the plan never becomes purchasable. Draft now, publish once billing is attached.
    - **Forgetting visibility/approval.** A product with `approval manual` or a catalog item not marked published leaves developers stuck pending. Symptom: signup succeeds but no key arrives. Set the product approval and catalog visibility deliberately.

!!! stretch "Stretch goal"
    Draft the full **product bundle and rate plan for your AISP API** the curriculum asks for. Decide the product split — is read-only accounts one product and transactions another, so you can give accounts away free and charge for transactions? Write the rate plan tiers (free / standard / partner), choosing for each the included volume, the overage model, and whether the cap is hard (429) or billed. Then map every tier's *limit* back to the `Quota` you'd drive from the product (3.2) and every tier's *price* to a monetization plan, and note the one decision that's purely commercial — usually the overage price — that no amount of proxy config can make for you.

## Recap & next

You can now explain why the **API product** is the unit of *packaging and monetization*, not just access — the same object from 3.2, read commercially. You refined a portal-ready AISP product, published an **OpenAPI spec to a developer portal** where a TPP self-serves a working, product-scoped key with no human in the loop, drafted **monetization** rate plan tiers anchored to that product, and saw where **API hub** catalogues and governs APIs across the org. This is the layer Spring deliberately has nothing to say about: turning a running endpoint into a consumable, governed, sellable product.

**Next — 7.1:** the capstone. You'll compose every concept — consent, AISP, PISP, and CoF, FAPI-secured end to end — into one operated Open Banking platform and run a **go-live readiness review**: the full system, every Spring-bridge concept assembled into one regulated, production-grade build.

