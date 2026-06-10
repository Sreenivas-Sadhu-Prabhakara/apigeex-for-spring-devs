# 5.5 — Confirmation of funds & the end-to-end journey

!!! bottomline "Bottom line"
    Confirmation of Funds (CBPII) is the smallest of the three OB resources: a **funds-confirmation-consent** the PSU authorises once, then a `POST /funds-confirmations` that returns a single boolean — `FundsAvailable: true|false`. It's also the perfect closing piece, because once it's in place you can run the **whole regulated journey** end to end: register a client (5.1), create and authorise consent (5.2), read accounts (5.3), initiate and submit a payment (5.4), and confirm funds — all over one FAPI-secured surface. By the end you'll have a single script that walks the entire journey and gets the OB-shaped response at every step.

## Why this exists

You've now built each OB resource in isolation: DCR in 5.1, the account-access consent state machine in 5.2, the AISP reads in 5.3, and the PISP payment with its idempotency key in 5.4. Each session proved one mechanism. But a TPP doesn't experience your platform as five separate APIs — it experiences it as **one journey**: get onboarded, ask the customer for permission, then do the regulated thing. Confirmation of Funds is the last resource to add, and adding it forces you to notice how uniform the journey has become.

CBPII is the lightest of the OBIE roles. A CBPII (think a card issuer checking a debtor can cover a transaction before authorising it) doesn't read balances or move money — it asks one yes/no question: *is at least this amount available right now?* The bank answers `true` or `false` and nothing else. That deliberate minimalism is privacy-by-design: the CBPII learns availability, never the actual balance. So the resource is tiny, but the **consent-then-act** shape is identical to AIS and PIS — which is exactly the point of this synthesis.

The reason this session exists at the end of Part 5 is that the *journey* is the product, not any single endpoint. Every step shares the same FAPI envelope from Part 4 — `x-fapi-interaction-id`, the mTLS-bound token from 4.4, the entitlement chain from 3.2 deciding which product the app holds — and the same consent discipline from 5.2. Once you see register → consent → AIS → pay → CoF as one threaded sequence with one set of headers, you understand what you actually built: not five proxies, but one coherent, regulated, FAPI-secured surface.

!!! bridge "Spring Boot bridge"
    This is the capstone of the domain APIs — the moment your individual `@RestController` resources compose into one user journey, the way a saga or a `@Service` orchestration method strings several repositories into a single business transaction.

    | The OB journey step | The Spring shape you'd otherwise write | What carries it across the gateway |
    |---|---|---|
    | DCR — register the client (5.1) | client onboarding into a `RegisteredClient` store | a developer App holding an API Product (3.2) |
    | Create + authorise consent (5.2) | a JPA entity with a `@Enumerated` status lifecycle | a consent resource enforced at the edge |
    | AIS read (5.3) | `@GetMapping("/accounts")`, consent-scoped | a token whose scope was minted against that consent |
    | Initiate + submit payment (5.4) | a payment `@Service` with an idempotency table | `x-idempotency-key` deduped at the gateway |
    | Confirm funds (5.5) | `boolean canAfford(amount)` | `POST /funds-confirmations` → `FundsAvailable` |

    The CoF endpoint itself maps to the smallest method you'd write — a `boolean canAfford(Money amount)` on a balance service. What's new is everything *around* it: the consent, the FAPI headers, and the fact that it's one step in a sequence the same client walks.

!!! breaks "Where the analogy breaks"
    A Spring saga or orchestration runs **inside one process**, holding shared state in memory or a transaction, and you control all the participants. The OB journey is the opposite: every step is a separate HTTP call from an *external* TPP you don't trust, with no shared session — the only thread connecting "I authorised consent" to "I'm now reading accounts" is the **token and the consent it was minted against**. There is no orchestrator owning the flow; the gateway enforces each step independently and statelessly, and the journey only hangs together because each request re-presents its credentials and its FAPI envelope. Don't reach for "where's the saga coordinator" — there isn't one, by design. The continuity lives in the token, the consent resource, and the `x-fapi-interaction-id` you trace across the steps.

## The concept

Confirmation of Funds has exactly two resources, mirroring the consent-then-act pattern you've used since 5.2:

- **`POST /cbpii/v1/funds-confirmation-consents`** — the PSU grants a CBPII standing permission to check funds against one account. Like the account-access consent in 5.2, it's created, authorised, then enforced. The consent names the `DebtorAccount` and carries its own `ConsentId` and status (`AwaitingAuthorisation` → `Authorised`).
- **`POST /cbpii/v1/funds-confirmations`** — the actual check. The body carries the `ConsentId`, an `InstructedAmount` (`Amount` + `Currency`), and a `Reference`. The response is a single fact: `Data.FundsAvailable` is `true` or `false`, with a `FundsAvailableDateTime`. No balance, ever.

The end-to-end journey threads all five resources through one FAPI surface. Step through it — the same client app, the same `x-fapi-interaction-id` lineage, the token re-presented at every call:

```widget
{
  "type": "sequence",
  "title": "The full OB journey: register → consent → AIS → pay → confirm",
  "actors": [
    {"id": "t", "label": "TPP (client app)"},
    {"id": "g", "label": "Apigee (ASPSP edge)"},
    {"id": "p", "label": "PSU (customer)"}
  ],
  "steps": [
    {"from": "t", "to": "g", "label": "POST /register  (SSA, mTLS)", "note": "DCR from 5.1 — the Software Statement is validated, a developer App + product are created. The TPP now has a client_id."},
    {"from": "g", "to": "t", "kind": "return", "label": "201  { client_id, client_secret }", "note": "Onboarded. Every later call presents this client and its client cert."},
    {"from": "t", "to": "g", "label": "POST /account-access-consents", "note": "Consent lifecycle from 5.2 — create an AwaitingAuthorisation consent listing the permissions (ReadAccountsDetail, ReadBalances…)."},
    {"from": "p", "to": "g", "label": "authorise (auth-code + PKCE)", "note": "The PSU authenticates and consents at the ASPSP (3.4 / FAPI 4.x). The consent flips to Authorised; a token is minted bound to this ConsentId and to the client cert (4.4)."},
    {"from": "t", "to": "g", "label": "GET /accounts  + FAPI headers", "note": "AIS read from 5.3 — token + consent enforced. Only the accounts the consent covers come back, OB-shaped."},
    {"from": "t", "to": "g", "label": "POST /domestic-payment-consents → authorise → POST /domestic-payments", "note": "PIS from 5.4 — its own consent, then submission with x-idempotency-key. Replays return the original result."},
    {"from": "t", "to": "g", "label": "POST /funds-confirmation-consents → authorise", "note": "CBPII consent from this session — PSU permits funds checks against one DebtorAccount."},
    {"from": "t", "to": "g", "label": "POST /funds-confirmations  { InstructedAmount }", "note": "The check itself. Gateway enforces the CoF consent + FAPI envelope."},
    {"from": "g", "to": "t", "kind": "return", "label": "200  { FundsAvailable: true }", "note": "One boolean — never a balance. Journey complete: registered, consented, read, paid, confirmed."}
  ]
}
```

Notice the rhythm: every regulated action is **consent first, then act**, and every call rides the same FAPI envelope. CoF doesn't introduce a new pattern — it confirms the pattern is the platform.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — implement CoF, then script the whole journey

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported, and your assembled OB proxies from 5.1–5.4 deployed (DCR, the consent flows, AIS, PIS). You'll add the two CBPII operations, then run one script that walks register → consent → AIS → pay → CoF.

**1. Add the two CBPII operations to the product's operation group** so the CBPII role can actually reach them (the entitlement model from 3.2). Update the `cbpii` product:

```bash
apigeecli products create \
  --name ob-cbpii --displayName "OB Confirmation of Funds" --approval auto \
  --envs "$ENV" --scopes "fundsconfirmations" \
  --quota 5000 --interval 1 --unit day \
  --opgrp '{"operationConfigs":[{"apiSource":"ob-cbpii","operations":[{"resource":"/funds-confirmation-consents","methods":["POST"]},{"resource":"/funds-confirmations","methods":["POST"]}]}]}' \
  --org "$ORG" --token "$TOKEN"
```

**2. Enforce the CoF consent + FAPI envelope** on the funds-confirmations flow. Reuse the shared flow from 3.7 that checks `x-fapi-interaction-id` and the mTLS-bound token (4.4), then validate the `ConsentId` is `Authorised` and names a `DebtorAccount` the token is allowed to query. The conditional flow in `ob-cbpii`:

```xml
<Flow name="funds-confirmation">
  <Condition>proxy.pathsuffix MatchesPath "/funds-confirmations" and request.verb = "POST"</Condition>
  <Request>
    <Step><Name>EV-CofRequest</Name></Step>          <!-- pull ConsentId, InstructedAmount -->
    <Step><Name>KVM-GetCofConsent</Name></Step>       <!-- load consent state from a KVM (2.7) -->
    <Step>
      <Name>RF-ConsentNotAuthorised</Name>
      <Condition>cof.consent.status != "Authorised"</Condition>  <!-- FaultRule from the 3.7 taxonomy -->
    </Step>
  </Request>
</Flow>
```

**3. Shape the OB response.** CoF returns exactly one fact. Use an AssignMessage (2.4) to build the OBIE body — here a `true` when the mock balance covers the instructed amount:

```xml
<AssignMessage name="AM-FundsConfirmationResponse">
  <Set>
    <Payload contentType="application/json">{
  "Data": {
    "FundsConfirmationId": "{system.uuid}",
    "ConsentId": "{cof.consent.id}",
    "CreationDateTime": "{system.timestamp}",
    "FundsAvailable": {cof.funds.available},
    "Reference": "{cof.request.reference}",
    "InstructedAmount": { "Amount": "{cof.request.amount}", "Currency": "{cof.request.currency}" }
  },
  "Meta": {}
}</Payload>
  </Set>
  <Set><StatusCode>200</StatusCode></Set>
</AssignMessage>
```

**4. Deploy the CBPII proxy:**

```bash
apigeecli apis create bundle --name ob-cbpii --proxy-folder ./ob-cbpii/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name ob-cbpii --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"
```

**5. Script the whole journey.** One file threads the FAPI headers and the token across every step. Save as `journey.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
BASE="https://$RUNTIME_HOST"
FAPI=(-H "x-fapi-interaction-id: $(uuidgen)" \
      -H "x-fapi-auth-date: $(date -u +%a,\ %d\ %b\ %Y\ %H:%M:%S\ GMT)" \
      -H "x-fapi-customer-ip-address: 198.51.100.7")
AT="$1"                                   # mTLS-bound access token from the auth-code flow (3.4 / 4.4)
auth=(-H "Authorization: Bearer $AT" --cert client.pem --key client.key)

echo "── 1. AIS: read accounts (5.3) ──"
curl -s "${FAPI[@]}" "${auth[@]}" "$BASE/aisp/v3.1/accounts" | jq '.Data.Account[].AccountId'

echo "── 2. PIS: submit a domestic payment (5.4), idempotent ──"
IDEMP=$(uuidgen)
curl -s "${FAPI[@]}" "${auth[@]}" -H "x-idempotency-key: $IDEMP" \
  -H "content-type: application/json" \
  -d '{"Data":{"ConsentId":"pcon-123","Initiation":{"InstructionIdentification":"i1","EndToEndIdentification":"e1","InstructedAmount":{"Amount":"10.00","Currency":"GBP"},"CreditorAccount":{"SchemeName":"UK.OBIE.SortCodeAccountNumber","Identification":"08080021325698","Name":"Bob"}}}}' \
  "$BASE/pisp/v3.1/domestic-payments" | jq '.Data.Status'

echo "── 3. CoF: confirm funds (5.5) ──"
curl -s "${FAPI[@]}" "${auth[@]}" -H "content-type: application/json" \
  -d '{"Data":{"ConsentId":"cofcon-456","Reference":"Purchase01","InstructedAmount":{"Amount":"20.00","Currency":"GBP"}}}' \
  "$BASE/cbpii/v1/funds-confirmations" | jq '{available: .Data.FundsAvailable}'
```

Run it with a freshly minted, consent-bound token: `./journey.sh "$AT"`.

**What success looks like:** the single script walks the full journey and **each step returns the expected OB-shaped response** — a list of `AccountId`s from AIS, a payment `Status` of `AcceptedSettlementInProcess` from PIS, and `{ "available": true }` from CoF — all under one threaded `x-fapi-interaction-id`. A `false`/`429`/`401` is a *real* answer too: it means consent, idempotency, or the FAPI envelope did its job.
</div>

## Verify it

Confirm the privacy property first: a successful `POST /funds-confirmations` response contains `Data.FundsAvailable` and **never** an amount or balance field. If a balance leaks into the body, your AssignMessage is over-sharing — trim it.

Then confirm the consent gate. Replay the CoF call with a `ConsentId` whose status is still `AwaitingAuthorisation` and you should get the `RF-ConsentNotAuthorised` fault from your 3.7 taxonomy (a `403` with an OBIE error body), not a `200`. Finally, re-run `journey.sh` twice with the *same* `x-idempotency-key` on the payment step and confirm the second run returns the original payment result rather than creating a second payment — the dedupe from 5.4 still holds inside the assembled journey.

!!! failure "Common failure modes"
    - **Returning a balance from CoF.** The whole point of CBPII is that it answers `true`/`false` only. Leaking `Balance` into the response breaks the privacy contract. *(Symptom: a card-issuer TPP can reconstruct the customer's balance by binary-searching `InstructedAmount`.)*
    - **Skipping the CoF consent.** Funds confirmation needs its **own** authorised `funds-confirmation-consent` — an AIS or PIS token does not authorise it. *(Symptom: a `POST /funds-confirmations` succeeds with a token that was only consented for account reads.)*
    - **Dropping the FAPI envelope between steps.** The journey only coheres if every call carries `x-fapi-interaction-id` and the mTLS-bound token. *(Symptom: step 1 works, step 3 returns `401`/`400` because the script forgot a header on the later call.)*
    - **Confusing the two CBPII resources.** `funds-confirmation-consents` (the standing permission) is not `funds-confirmations` (the check). Both are `POST`; only the second returns `FundsAvailable`. *(Symptom: you `POST` an `InstructedAmount` to the consents endpoint and get a consent object back, not a boolean.)*
    - **Stateless replay of the token's consent.** A token whose consent was revoked between steps must fail at the gateway, not the backend. *(Symptom: AIS still returns accounts after the consent was revoked because the proxy didn't re-check consent state.)*

!!! stretch "Stretch goal"
    Turn `journey.sh` into a real end-to-end test: wrap it so it mints its own consent-bound token via the auth-code + PKCE flow (3.4), runs all three regulated calls, asserts each response shape with `jq`, and exits non-zero on the first failed assertion. Then run the **full AIS + PIS + CoF journey as one scripted test** in CI (a preview of 6.2) so every proxy change re-proves the whole journey, not just one endpoint. The value isn't the boolean — it's that one command can certify the entire regulated surface still behaves.

## Recap & next

You added the **Confirmation of Funds** resources — the consent-then-act pattern at its smallest, answering one privacy-preserving boolean — and then assembled all five OB resources (DCR, consent, AIS, PIS, CoF) into one coherent, FAPI-secured journey that a single script can walk from registration to confirmation. The lesson of Part 5 is that the **journey is the product**: five endpoints, one token lineage, one FAPI envelope, one consent discipline.

**Next — 6.1:** you've *built* the platform; now you'll learn to **operate** it. You'll promote these proxies across **environments** with no bundle change, and route traffic to each with **environment groups and hostnames** — the grown-up, platform-managed version of the Spring profiles and ingress you'd otherwise wire by hand.
