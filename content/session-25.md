# 5.2 — The account-access consent lifecycle

!!! bottomline "Bottom line"
    Before a TPP can read a customer's accounts it must hold an **account-access consent** the customer authorised — a stateful resource with a strict lifecycle: created `AwaitingAuthorisation`, the PSU authorises it to `Authorised`, and only then do reads succeed; it can later be `Revoked`, `Rejected`, or `Expired`. By the end you can `POST /account-access-consents` to create one, transition it to `Authorised`, persist its state in a KVM keyed by `ConsentId`, and reject any read that runs against a consent which is not `Authorised`.

## Why this exists

Tokens prove *who* is calling (5.1) but not *what the customer agreed to*. In Open Banking the customer — the PSU — must explicitly consent to a TPP reading specific data (`ReadAccountsDetail`, `ReadBalances`, `ReadTransactionsDetail`) for a bounded period. That consent is a **first-class resource**, not a flag on a token: the OBIE AISP spec defines `POST /open-banking/v3.1/aisp/account-access-consents`, which creates a consent with the requested `Permissions` and an `ExpirationDateTime`, and returns a `ConsentId` in status `AwaitingAuthorisation`. Nothing can be read yet — the consent exists, but the customer hasn't said yes.

The customer says yes out-of-band: the TPP sends the PSU through an authorisation journey (the FAPI redirect/PAR flow from Part 4), at the end of which your authorization server marks the consent `Authorised`. From that moment, and only that moment, the AISP's read calls to `/accounts`, `/balances`, and `/transactions` are permitted — and only within the `Permissions` and `ExpirationDateTime` the consent carries. Revoke it (the PSU changes their mind, or the TPP releases it) and it becomes `Revoked`; reads stop immediately.

The non-negotiable part is that the **transitions are constrained**. You cannot read against an `AwaitingAuthorisation` consent, you cannot re-authorise a `Revoked` one, and an `Expired` consent is dead. This is a state machine, and the gateway is where it's enforced — because the read APIs in 5.3 will simply ask "is the consent behind this token currently `Authorised`?" and trust the answer.

!!! bridge "Spring Boot bridge"
    Model the consent exactly like a **JPA entity with a status enum and a state machine** — the kind you'd build with Spring Statemachine or a hand-rolled `@Enumerated` guard. The difference is *where the machine runs*: not in your service, but at the gateway, with the store being a KVM (2.7) instead of a table.

    | Spring | Apigee X (consent) |
    |---|---|
    | `@Entity Consent { @Id String consentId; @Enumerated Status status; }` | A KVM entry keyed by `ConsentId` holding the consent JSON |
    | `enum Status { AWAITING_AUTH, AUTHORISED, REVOKED, EXPIRED, REJECTED }` | the `Status` field of the stored consent |
    | `@PostMapping` creating it in `AWAITING_AUTH` | `POST /account-access-consents` → `AwaitingAuthorisation` |
    | A service method guarding `authorise()` transitions | a condition checking the *current* stored status before writing the new one |
    | `@PreAuthorize` on the read endpoint | a gateway check that the consant's stored `Status == "Authorised"` |

!!! breaks "Where the analogy breaks"
    A JPA state machine lives next to the data it guards: the same transaction that flips the status also owns the rows being read, so the guard and the read are atomic. At the gateway they are split — the consent lives in a KVM, the account data lives behind a backend the gateway only proxies, and the "is this `Authorised`?" check is a *separate* lookup the gateway performs before it forwards the read. There is no `@Transactional` boundary wrapping both. That means you must treat the consent store as the single source of truth and re-check it on **every** read (a token alone is never sufficient), and you must accept eventual-consistency realities a KVM has that a row lock does not. The lifecycle is the same shape you know; the *enforcement seam* sits between two systems instead of inside one.

## The concept

A consent moves through a small, strict set of states. Click the events below to walk it — and notice which transitions the machine refuses. The illegal ones (reading before authorisation, re-authorising a revoked consent) are exactly what the gateway must reject.

```widget
{
  "type": "statemachine",
  "title": "Account-access consent lifecycle",
  "start": "awaiting",
  "states": [
    {"id": "awaiting", "label": "AwaitingAuthorisation"},
    {"id": "authorised", "label": "Authorised"},
    {"id": "rejected", "label": "Rejected", "terminal": true},
    {"id": "revoked", "label": "Revoked", "terminal": true},
    {"id": "expired", "label": "Expired", "terminal": true}
  ],
  "events": [
    {"id": "authorise", "label": "PSU authorises"},
    {"id": "reject", "label": "PSU rejects"},
    {"id": "revoke", "label": "Revoke"},
    {"id": "expire", "label": "ExpirationDateTime passes"}
  ],
  "transitions": [
    {"from": "awaiting", "event": "authorise", "to": "authorised", "desc": "PSU completes the FAPI authorisation journey — reads now permitted."},
    {"from": "awaiting", "event": "reject", "to": "rejected", "desc": "PSU declines at the consent screen — terminal, no reads ever."},
    {"from": "awaiting", "event": "expire", "to": "expired", "desc": "Never authorised before ExpirationDateTime — terminal."},
    {"from": "authorised", "event": "revoke", "to": "revoked", "desc": "PSU or TPP withdraws consent — reads stop immediately."},
    {"from": "authorised", "event": "expire", "to": "expired", "desc": "ExpirationDateTime passes — reads stop."}
  ]
}
```

Reading is gated on exactly one fact: **is the stored consent `Authorised`?** The read APIs in 5.3 don't re-derive permission from the token; they look the consent up by `ConsentId` in the KVM and check its `Status`. Everything in this session exists to make that one lookup trustworthy.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — create a consent, authorise it, store it in a KVM, and enforce status on use

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported; a `consent` proxy serving `/open-banking/v3.1/aisp/account-access-consents`; FAPI headers enforced from Part 4 (notably `x-fapi-interaction-id`). An environment KVM named `account-consents` (created per 2.7).

**1. Create the consent.** On `POST`, mint a `ConsentId`, stamp the requested `Permissions` and `ExpirationDateTime`, and persist as `AwaitingAuthorisation`. Build the resource:

```xml
<AssignMessage name="AM-NewConsent">
  <AssignVariable>
    <Name>consent.id</Name>
    <Template>aac-{createUUID()}</Template>
  </AssignVariable>
  <AssignVariable>
    <Name>consent.json</Name>
    <Template>{"Data":{"ConsentId":"{consent.id}","Status":"AwaitingAuthorisation","CreationDateTime":"{system.timestamp}","Permissions":{request.content.Data.Permissions},"ExpirationDateTime":{request.content.Data.ExpirationDateTime}}}</Template>
  </AssignVariable>
</AssignMessage>
```

**2. Persist it in the KVM, keyed by `ConsentId`** — this is the source of truth every read will consult:

```xml
<KeyValueMapOperations name="KVM-Put-Consent" mapIdentifier="account-consents">
  <Scope>environment</Scope>
  <Put override="true">
    <Key><Parameter ref="consent.id"/></Key>
    <Value ref="consent.json"/>
  </Put>
</KeyValueMapOperations>
```

Return `201` with the consent body so the TPP gets its `ConsentId`.

**3. Authorise it — but only from a legal source state.** When the PSU finishes the authorisation journey, your AS calls a status update. Read the *current* stored consent first, then refuse the transition unless it is `AwaitingAuthorisation`:

```xml
<KeyValueMapOperations name="KVM-Get-Consent" mapIdentifier="account-consents">
  <Scope>environment</Scope>
  <Get assignTo="consent.stored">
    <Key><Parameter ref="consentId"/></Key>
  </Get>
</KeyValueMapOperations>
```

```xml
<!-- guard: only AwaitingAuthorisation may move to Authorised (illegal transition rejected) -->
<RaiseFault name="RF-IllegalTransition">
  <Condition>JSONPath("$.Data.Status", consent.stored) != "AwaitingAuthorisation"</Condition>
  <FaultResponse>
    <Set>
      <StatusCode>409</StatusCode>
      <ReasonPhrase>Conflict</ReasonPhrase>
      <Payload contentType="application/json">{"Code":"OB.Field.Unexpected","Message":"consent not in AwaitingAuthorisation"}</Payload>
    </Set>
  </FaultResponse>
</RaiseFault>
```

If the guard passes, write the consent back with `Status: "Authorised"` via another `KVM Put` (same key, new value).

**4. Enforce status on use.** Before any AISP read flow forwards to the backend, look the consent up by the `ConsentId` the token carries and reject unless it is `Authorised`:

```xml
<RaiseFault name="RF-ConsentNotAuthorised">
  <Condition>JSONPath("$.Data.Status", consent.stored) != "Authorised"</Condition>
  <FaultResponse>
    <Set>
      <StatusCode>403</StatusCode>
      <ReasonPhrase>Forbidden</ReasonPhrase>
      <Headers><Header name="x-fapi-interaction-id">{request.header.x-fapi-interaction-id}</Header></Headers>
      <Payload contentType="application/json">{"Code":"OB.Resource.InvalidConsentStatus","Message":"consent is not Authorised"}</Payload>
    </Set>
  </FaultResponse>
</RaiseFault>
```

**5. Deploy and walk the lifecycle:**

```bash
apigeecli apis create bundle --name consent --proxy-folder ./consent/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name consent --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

BASE="https://$RUNTIME_HOST/open-banking/v3.1/aisp"
FAPI="-H x-fapi-interaction-id:$(uuidgen) -H Authorization:Bearer\ $AT"

# create → AwaitingAuthorisation, returns ConsentId
CID=$(curl -s -X POST "$BASE/account-access-consents" $FAPI \
  -H "Content-Type: application/json" \
  -d '{"Data":{"Permissions":["ReadAccountsDetail","ReadBalances","ReadTransactionsDetail"],"ExpirationDateTime":"2026-12-31T00:00:00Z"}}' \
  | jq -r '.Data.ConsentId')
echo "ConsentId=$CID"
```

**6. Prove the gate — read before authorisation is rejected, after it is allowed:**

```bash
# read BEFORE authorisation → 403 (consent is AwaitingAuthorisation)
curl -s -o /dev/null -w "before authorise: %{http_code}\n" "$BASE/accounts" $FAPI

# authorise (the AS does this post-journey); here, hit the status-update flow
curl -s -X PUT "$BASE/account-access-consents/$CID/authorise" $FAPI > /dev/null

# read AFTER authorisation → 200
curl -s -o /dev/null -w "after authorise:  %{http_code}\n" "$BASE/accounts" $FAPI
```

**What success looks like:** creating returns a `ConsentId` with `Status: AwaitingAuthorisation`; reading `/accounts` before authorisation returns **403** (`InvalidConsentStatus`); after the authorise transition the same read returns **200**. And the KVM entry for `$CID` shows `Status` flipping `AwaitingAuthorisation → Authorised` — the state machine, enforced at the edge.
</div>

## Verify it

Read the stored consent straight from the KVM and watch the `Status` field change across the lifecycle. After step 5 it must be `AwaitingAuthorisation`; after the authorise call it must be `Authorised`. Confirm the gate with the two reads from step 6: the pre-authorisation read returns `403` with `OB.Resource.InvalidConsentStatus`, the post-authorisation read returns `200`. Then prove the illegal transition is refused — `PUT .../authorise` a second time (the consent is already `Authorised`, not `AwaitingAuthorisation`) and confirm `RF-IllegalTransition` fires a `409`. In a Trace, `KVM-Get-Consent` should populate `consent.stored` *before* either `RaiseFault` evaluates, and every error response must echo the request's `x-fapi-interaction-id`.

!!! failure "Common failure modes"
    - **Trusting the token, not the consent store.** A valid token does not mean an authorised consent — the consent may be `Revoked` or `Expired` since the token was minted. Symptom: revoked consents still read data. Re-check the stored `Status` on every read, not just at authorisation.
    - **No transition guard.** Writing the new status without checking the current one. Symptom: a `Revoked` consent can be flipped back to `Authorised`. The `KVM Get` + status condition must run before every `Put`.
    - **`ExpirationDateTime` never enforced.** Storing it but never comparing to now. Symptom: a long-expired consent still reads. Check expiry on use, or run a sweep that flips expired consents to `Expired`.
    - **Race on concurrent updates.** Two updates reading the same stale KVM value and both writing. Symptom: a lost transition under load. KVMs aren't transactional — serialise updates or accept and detect the conflict; don't assume `@Transactional` semantics.
    - **Leaking another PSU's consent.** Reading a `ConsentId` that doesn't belong to the calling client. Symptom: cross-customer data exposure. Bind the consent to the `client_id`/PSU and reject mismatches, not just non-`Authorised` status.

!!! stretch "Stretch goal"
    Draw the consent state machine from the widget as a diagram for your team, then pick one illegal transition — re-authorising a `Revoked` consent is the sharpest — and prove your proxy rejects it: revoke an `Authorised` consent, attempt `PUT .../authorise` again, and confirm a `409` from `RF-IllegalTransition` with the KVM still showing `Revoked`. Then add the `Expired` path: a scheduled job (or an on-read check) that compares `ExpirationDateTime` to now and transitions stale consents to `Expired`, so an expired consent fails the read gate exactly like a revoked one.

## Recap & next

You modelled the **account-access consent** as the stateful resource it is. `POST /account-access-consents` creates it `AwaitingAuthorisation` with its `Permissions` and `ExpirationDateTime`, persisted in a KVM keyed by `ConsentId`; an authorise transition — guarded so only a legal source state may move — flips it to `Authorised`; and every read is gated on that stored status, returning `403` for any consent that is not `Authorised`. The JPA-style state machine you know now lives at the gateway, with the KVM as its source of truth and illegal transitions refused at the edge.

**Next — 5.3:** with an authorised consent in hand, you build the AISP reads themselves — **Accounts, Balances & Transactions** (`/open-banking/v3.1/aisp/accounts` and friends). They look like ordinary `@GetMapping` resources, but authorization is **consent-scoped**, not role-scoped: a token may read only the data its consent's `Permissions` allow, and only the accounts that consent named.
