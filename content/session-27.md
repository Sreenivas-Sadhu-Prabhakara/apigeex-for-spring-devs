# 5.4 — PISP payments & idempotency

!!! bottomline "Bottom line"
    A PISP (Payment Initiation Service Provider) journey is two POSTs: create a **domestic-payment-consent** carrying the `Initiation` and `Risk` blocks, then — after the PSU authorises — submit a **domestic-payment** that references the `ConsentId`. The new hazard is duplication: a retried or replayed payment must **never** move money twice. OBIE solves this with the mandatory `x-idempotency-key` header, and you enforce it at the gateway by caching the first response and replaying it on any repeat — the edge-level version of dedupe logic you'd otherwise hand-roll in a Spring payment service.

## Why this exists

In Part 5.3 the danger was *reading the wrong thing*. On the payment side the danger is *doing a thing twice*. Networks retry. Clients time out and resend. A user double-taps "Pay." In a Spring payment service you'd defend against this with a unique-constraint on a request id, or a `processedKeys` table, or a Redis `SETNX` — some store that remembers "I've already handled this exact request, here's the answer I gave." Open Banking standardises that defence into a header every payment POST must carry: `x-idempotency-key`. Two POSTs with the same key, to the same endpoint, must yield the *same* outcome — one payment, one `DomesticPaymentId`, returned identically both times.

The flow is deliberately two-phase. First the AISP/PISP POSTs a **domestic-payment-consent**: the immutable `Initiation` (debtor, creditor, amount, reference) plus a **Risk** block (e.g. `PaymentContextCode: EcommerceGoods`) that the ASPSP uses for fraud scoring. That returns a `ConsentId` in status `AwaitingAuthorisation`. The PSU is then redirected to authenticate and approve, flipping the consent to `Authorised`. Only then does the PISP POST the actual **domestic-payment**, referencing that `ConsentId`, and the payment begins its own lifecycle toward settlement.

Idempotency bites hardest on that second POST, because that's the one that moves money. The consent POST is comparatively safe — re-creating a consent is wasteful but not financially harmful — but a duplicated *payment* is a double debit. So the contract is: cache the first successful `201` keyed by `x-idempotency-key`, and on any subsequent POST with that key, short-circuit and return the cached `201` — same body, same `DomesticPaymentId` — without ever calling the backend again.

!!! bridge "Spring Boot bridge"
    You've built idempotency by hand; the gateway gives you the same guarantee declaratively.

    | Hand-rolled in a Spring payment service | Gateway equivalent in this session |
    |---|---|
    | A `processed_requests` table keyed by request id | A **ResponseCache / KVM** keyed by `x-idempotency-key` |
    | `if (repo.existsById(key)) return cached;` | LookupCache hit → return the cached response, skip the target |
    | Saving the response after a successful insert | PopulateCache the `201` body after the backend succeeds |
    | A DB unique constraint as a last-resort guard | The cache key *is* the uniqueness guard |
    | `@Transactional` wrapping check-then-act | The proxy flow: lookup → (miss) submit → populate, all before responding |

    The mental model is identical to a Spring `@Idempotent`-style interceptor or a Stripe-style idempotency layer — only here it lives at the edge, so *every* backend behind the proxy inherits it without each service reimplementing the dedupe.

!!! breaks "Where the analogy breaks"
    Your hand-rolled Spring dedupe usually lives *inside the transaction* that writes the payment, so the "did I already do this?" check and the money movement commit or roll back together. The gateway cache is *outside* the backend transaction: there's a real window between "backend committed the payment" and "proxy stored the response in the cache." If the proxy dies in that gap, a retry could reach the backend twice — so the backend must *also* honour the idempotency key as a second line of defence. The gateway cache is a fast, correct optimisation for the common case, not a substitute for an idempotent backend. Treat "the gateway handles idempotency" as "the gateway handles the easy 99%," not "the backend can be naïve."

## The concept

Two coupled state machines drive a payment. The **consent** moves `AwaitingAuthorisation → Authorised → Consumed` (or `→ Rejected` if the PSU declines); the **payment**, created only from an `Authorised` consent, moves through `AcceptedSettlementInProcess → AcceptedSettlementCompleted`, or lands in `Rejected`. The idempotency layer wraps the *creation* of the payment so that re-submitting the same key can never start a second one.

Drive the lifecycle — fire events and watch which transitions the gateway allows:

```widget
{
  "type": "statemachine",
  "title": "Domestic payment: consent + payment lifecycle",
  "start": "awaiting",
  "states": [
    {"id": "awaiting", "label": "Consent: AwaitingAuthorisation"},
    {"id": "authorised", "label": "Consent: Authorised"},
    {"id": "rejected_c", "label": "Consent: Rejected", "terminal": true},
    {"id": "inprocess", "label": "Payment: AcceptedSettlementInProcess"},
    {"id": "completed", "label": "Payment: AcceptedSettlementCompleted", "terminal": true},
    {"id": "rejected_p", "label": "Payment: Rejected", "terminal": true}
  ],
  "events": [
    {"id": "psu_approve", "label": "PSU authorises"},
    {"id": "psu_decline", "label": "PSU declines"},
    {"id": "submit", "label": "POST /domestic-payments (new key)"},
    {"id": "replay", "label": "POST replay (same x-idempotency-key)"},
    {"id": "settle", "label": "Settlement clears"},
    {"id": "fail", "label": "Settlement fails"}
  ],
  "transitions": [
    {"from": "awaiting", "to": "authorised", "event": "psu_approve", "desc": "PSU authenticates and approves; consent now usable for a payment."},
    {"from": "awaiting", "to": "rejected_c", "event": "psu_decline", "desc": "PSU declines — no payment can ever be created from this consent."},
    {"from": "authorised", "to": "inprocess", "event": "submit", "desc": "First submission with a fresh x-idempotency-key. Backend creates the payment; proxy caches the 201."},
    {"from": "inprocess", "to": "inprocess", "event": "replay", "desc": "Replay with the SAME key → cache hit → original 201 + same DomesticPaymentId returned, backend NOT called. No second payment."},
    {"from": "inprocess", "to": "completed", "event": "settle", "desc": "Funds clear; terminal success."},
    {"from": "inprocess", "to": "rejected_p", "event": "fail", "desc": "Settlement fails; terminal rejection."}
  ]
}
```

Notice the self-loop on `inprocess` for `replay`: a repeated submission with the same key is a no-op that returns the original result. That loop *is* idempotency. Trying to `submit` from `awaiting` is correctly disallowed — you cannot pay from an unauthorised consent. (Awareness note: real FAPI payment POSTs also carry an `x-jws-signature` — a detached JWS over the body for non-repudiation; verifying it is its own session, but the header travels with every call here.)

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — payment consent + idempotent submission

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; an OAuth token with the `payments` scope; and a mock backend that returns a fresh `DomesticPaymentId` per call (so a duplicate is *visible*). We focus enforcement at the gateway.

**1. Create the domestic-payment-consent** — the PISP POSTs `Initiation` + `Risk`. The proxy stores the consent in a KVM as `AwaitingAuthorisation`:

```bash
curl -s -X POST "https://$RUNTIME_HOST/pisp/domestic-payment-consents" \
  -H "Authorization: Bearer $AT" \
  -H "x-fapi-interaction-id: $(uuidgen)" \
  -H "x-idempotency-key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"Data":{"Initiation":{"InstructionIdentification":"ACME412","EndToEndIdentification":"INV-9931","InstructedAmount":{"Amount":"42.50","Currency":"GBP"},"CreditorAccount":{"SchemeName":"UK.OBIE.SortCodeAccountNumber","Identification":"08080021325698","Name":"Bills Ltd"},"RemittanceInformation":{"Reference":"INV-9931"}}},"Risk":{"PaymentContextCode":"EcommerceGoods"}}'
# → {"Data":{"ConsentId":"pc-DP-5521","Status":"AwaitingAuthorisation",...}}
```

After the PSU authorises (out of band, as in 5.2), the consent flips to `Authorised` in the KVM.

**2. On the payment POST, look up the idempotency cache first.** In the ProxyEndpoint request PreFlow, before routing, LookupCache keyed by the header:

```xml
<LookupCache name="LC-Idempotency">
  <CacheKey><KeyFragment ref="request.header.x-idempotency-key"/></CacheKey>
  <CacheResource>idempotency-cache</CacheResource>
  <AssignTo>idem.cached</AssignTo>
</LookupCache>
```

**3. On a cache hit, replay the original `201` and skip the backend.** A RaiseFault (used here as a short-circuit responder) returns the stored body and a RouteRule with no target stops the request from reaching the backend:

```xml
<Step>
  <Name>RF-ReplayCached</Name>
  <Condition>idem.cached != null</Condition>
</Step>
```
```xml
<RaiseFault name="RF-ReplayCached">
  <FaultResponse>
    <Set>
      <StatusCode>201</StatusCode>
      <Headers><Header name="x-idempotency-replayed">true</Header></Headers>
      <Payload contentType="application/json">{idem.cached}</Payload>
    </Set>
  </FaultResponse>
</RaiseFault>
```

```xml
<!-- RouteRule: when we already have a cached response, route to no target -->
<RouteRule name="replay-noroute"><Condition>idem.cached != null</Condition></RouteRule>
<RouteRule name="default"><TargetEndpoint>default</TargetEndpoint></RouteRule>
```

**4. Require the key, and guard the consent.** A payment with no `x-idempotency-key`, or one referencing a non-`Authorised` consent, must be rejected (reuse the consent-status check pattern from 5.3):

```xml
<Step>
  <Name>RF-RequireIdemKey</Name>
  <Condition>request.header.x-idempotency-key = null</Condition>
</Step>
```

**5. On a cache miss, after the backend creates the payment, populate the cache** with the response body — so the *next* identical POST hits step 3. Attach PopulateCache in the **response** flow:

```xml
<PopulateCache name="PC-Idempotency">
  <CacheKey><KeyFragment ref="request.header.x-idempotency-key"/></CacheKey>
  <CacheResource>idempotency-cache</CacheResource>
  <Source>response.content</Source>
  <ExpirySettings><TimeoutInSec>86400</TimeoutInSec></ExpirySettings>
</PopulateCache>
```

**6. Deploy, submit once, then replay with the same key:**

```bash
apigeecli apis deploy --name pisp-payments --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

KEY=$(uuidgen)
BODY='{"Data":{"ConsentId":"pc-DP-5521","Initiation":{"InstructionIdentification":"ACME412","EndToEndIdentification":"INV-9931","InstructedAmount":{"Amount":"42.50","Currency":"GBP"},"CreditorAccount":{"SchemeName":"UK.OBIE.SortCodeAccountNumber","Identification":"08080021325698","Name":"Bills Ltd"}}},"Risk":{"PaymentContextCode":"EcommerceGoods"}}'

# first submission → 201, a new DomesticPaymentId
echo "--- first ---"
curl -s -X POST "https://$RUNTIME_HOST/pisp/domestic-payments" \
  -H "Authorization: Bearer $AT" -H "x-fapi-interaction-id: $(uuidgen)" \
  -H "x-idempotency-key: $KEY" -H "Content-Type: application/json" \
  -d "$BODY" | jq '.Data.DomesticPaymentId'

# identical replay, SAME key → same DomesticPaymentId, backend not called
echo "--- replay ---"
curl -s -X POST "https://$RUNTIME_HOST/pisp/domestic-payments" \
  -H "Authorization: Bearer $AT" -H "x-fapi-interaction-id: $(uuidgen)" \
  -H "x-idempotency-key: $KEY" -H "Content-Type: application/json" \
  -d "$BODY" -i | grep -iE "x-idempotency-replayed|DomesticPaymentId"
```

**What success looks like:** the first POST returns `201` with a `DomesticPaymentId` such as `dp-7740`; the replay returns the **same** `dp-7740`, carries `x-idempotency-replayed: true`, and — confirmed in Trace — never reaches the TargetEndpoint. One key, one payment, two identical responses.
</div>

## Verify it

Compare the two `DomesticPaymentId` values from the run above: they must be byte-identical. Because the mock backend mints a *fresh* id per call, an equal id on the replay can only mean the backend was never hit — the cache served it. Confirm directly in Trace: the first call shows the TargetEndpoint request flow executing and `PC-Idempotency` populating; the replay stops at `RF-ReplayCached` with no target step at all.

Now change one byte of the request body but keep the same `x-idempotency-key` and POST again. Per the OBIE contract this is a *misuse* — the same key with a different payload — and a strict implementation should reject it (`400`/`403`) rather than silently replay or silently create a second payment; verify your proxy does not quietly mint `dp-7741`. Finally, POST with **no** `x-idempotency-key` and confirm you get the rejection from `RF-RequireIdemKey`, proving the header is mandatory, not optional.

!!! failure "Common failure modes"
    - **Populating the cache before the backend confirms.** Cache the `201` in the *response* flow, after success — caching in the request flow stores a result for a payment that may never have been made. Symptom: a replay returns a payment id the backend never created.
    - **Keying the cache on the wrong thing.** Using the access token, or the body hash alone, instead of `x-idempotency-key`. Symptom: two genuinely different payments collide, or two retries don't.
    - **Replaying across different payloads.** Returning the cached `201` when the same key arrives with a *different* body hides a client bug and can mask a fraudulent edit. Symptom: a tampered amount silently returns the original payment.
    - **No second line of defence in the backend.** If the proxy dies between backend-commit and cache-populate, a retry double-pays. Symptom: rare duplicate payments under load that the gateway alone can't explain.
    - **Treating the consent POST as the money-mover.** Idempotency that only guards the consent leaves the actual `/domestic-payments` POST unprotected. Symptom: re-submitting the payment, not the consent, creates a duplicate.

!!! stretch "Stretch goal"
    Prove the guarantee end-to-end under stress. Fire the **same** `x-idempotency-key` from ten parallel `curl` processes at once (a `for` loop with `&`), then count distinct `DomesticPaymentId`s in the responses — it must be exactly **one**. The interesting case is the race where several requests miss the cache simultaneously before any has populated it; reason about whether your LookupCache/PopulateCache window can let two reach the backend, and decide what backing your "uniqueness guard" needs (a strongly-consistent KVM/cache, or backend enforcement) to make the answer *always* one, not *usually* one.

## Recap & next

You've built the PISP write path: a domestic-payment-consent carrying `Initiation` + `Risk`, an authorise step, and a payment submission that references the `ConsentId` — all defended by `x-idempotency-key` so a replay returns the original `DomesticPaymentId` instead of moving money twice. Idempotency at the edge is the declarative twin of the dedupe table you'd hand-roll in a Spring payment service, with the caveat that the backend must stay idempotent too.

**Next — 5.5:** the closing piece — **Confirmation of Funds (CBPII)** — and then assembling everything from Part 5 into one regulated end-to-end journey: consent → authorise → confirm funds → pay → confirm settlement, run as a single scripted test.
