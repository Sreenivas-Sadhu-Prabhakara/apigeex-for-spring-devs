# 2.4 — AssignMessage & ExtractVariables

!!! bottomline "Bottom line"
    **ExtractVariables** reads structured pieces out of a message — a path segment, a query param, a header, a JSON or XML field — and sets them as flow variables. **AssignMessage** writes: it sets/adds/removes/copies headers and payload, assigns variables, retargets the backend, or builds a whole new request or response. Together they are the **core mediation pair** — your declarative answer to a request/response body rewriter — and almost every proxy you ship uses them.

## Why this exists

By now you can route (2.3) and you know the flow-variable model (2.2). What you can't yet do is *change the message*. Real gateways spend most of their lives reshaping: the client speaks one dialect, the backend speaks another, and something in the middle has to translate without either side knowing.

In Spring you reach for a `@ControllerAdvice` with `RequestBodyAdvice` / `ResponseBodyAdvice`, a `ResponseEntity` builder, or hand-rolled header manipulation in a filter. That's imperative Java compiled into your app. Apigee splits the same job into two declarative policies you attach at one of the four points from 2.1: **read** with ExtractVariables, **write** with AssignMessage.

Keeping read and write separate is deliberate. ExtractVariables never mutates the message — it only populates variables — so it's safe to run early and reuse the results in conditions, routing, quotas, and logging. AssignMessage is the only one that mutates. When a transformation misbehaves you immediately know which half to look at.

!!! bridge "Spring Boot bridge"
    This is the gateway's equivalent of a body-rewriting `@ControllerAdvice`, but split into a read half and a write half:

    | Spring | Apigee policy | What it does |
    |---|---|---|
    | `@PathVariable`, `@RequestParam`, `@RequestHeader` binding | **ExtractVariables** | Pulls path segments, query params, headers into named variables |
    | `JsonPath` / `@RequestBody` field access | **ExtractVariables** (JSONPath/XPath) | Reads a field out of the payload |
    | `ResponseEntity.header(...).body(...)` builder | **AssignMessage** (`Set`/`Add`) | Writes headers and payload onto the outgoing message |
    | `RequestBodyAdvice` / `ResponseBodyAdvice` | **AssignMessage** on request / response flow | Rewrites the body before forward / before return |
    | An adapter remapping your model to the downstream client's | **AssignMessage** building a new request | Reshapes the message the backend receives |

!!! breaks "Where the analogy breaks"
    A `@ControllerAdvice` is one Java object that sees both the request and the response and can hold state between them. Apigee has no such object. Each AssignMessage runs at exactly one attach point against exactly one message, and the only thing that survives from the request side to the response side is a **flow variable** you explicitly set. There is no `this.` to stash data on. If you extract an account id inbound and want it in the response, you store it in a variable at point ① and read that variable when you build the response at point ④ — the two halves never share an object, only the variable bag from 2.2.

## The concept

ExtractVariables and AssignMessage attach at the same four points as every other policy — the mediation just *happens* at those points. Read inbound at ①/②, write outbound at ③/④, or reshape the request the backend sees at ②.

<figure class="svg-figure">
<img src="assets/svg/flow-pipeline.svg" alt="Request flows Client → ProxyEndpoint(1) → TargetEndpoint(2) → Backend; response flows Backend → TargetEndpoint(3) → ProxyEndpoint(4) → Client.">
<figcaption>Mediation happens at these attach points. ExtractVariables typically runs at ① to read the inbound message; AssignMessage reshapes the request at ② and the response at ③/④.</figcaption>
</figure>

**ExtractVariables** has one source block per kind. Each match becomes a variable, prefixed by the policy name unless you override it:

```xml
<ExtractVariables name="EV-Request">
  <Source>request</Source>
  <!-- a path segment, by pattern, from the proxy path suffix -->
  <URIPath>
    <Pattern ignoreCase="true">/accounts/{accountId}</Pattern>
  </URIPath>
  <!-- a query param -->
  <QueryParam name="fromBookingDateTime">
    <Pattern>{fromDate}</Pattern>
  </QueryParam>
  <!-- a header -->
  <Header name="x-fapi-interaction-id">
    <Pattern>{interactionId}</Pattern>
  </Header>
  <!-- a JSON body field -->
  <JSONPayload>
    <Variable name="consentId">
      <JSONPath>$.Data.ConsentId</JSONPath>
    </Variable>
  </JSONPayload>
  <VariablePrefix>ev</VariablePrefix>
</ExtractVariables>
```

After it runs you have `ev.accountId`, `ev.fromDate`, `ev.interactionId`, and `ev.consentId` in the flow-variable bag. (For XML payloads you'd use `<XMLPayload>` with `<XPath>` instead; `<FormParam>` handles form bodies.)

**AssignMessage** is the write half. The verbs are the whole policy:

- **`<Set>`** — overwrite headers, query params, payload, verb, path, status.
- **`<Add>`** — append without clobbering an existing value.
- **`<Remove>`** — strip headers/params (e.g. hide an internal header outbound).
- **`<Copy source="...">`** — copy parts from another message.
- **`<AssignVariable>`** — set a flow variable (your `int x = ...`).
- **`<AssignTo createNew="true" type="request">`** — build a brand-new message instead of editing the current one.

A realistic example: at the TargetEndpoint request (point ②) reshape what the backend receives — add a correlation header and rewrite the body into the backend's shape using the variables we extracted:

```xml
<AssignMessage name="AM-BackendRequest">
  <AssignTo type="request"/>
  <Set>
    <Headers>
      <Header name="x-correlation-id">{ev.interactionId}</Header>
    </Headers>
    <Payload contentType="application/json">{
  "accountId": "{ev.accountId}",
  "from": "{ev.fromDate}",
  "requestedBy": "{verifyapikey.VK-Key.developer.email}"
}</Payload>
  </Set>
  <Remove>
    <Headers><Header name="x-api-key"/></Headers>
  </Remove>
</AssignMessage>
```

Curly-brace `{ev.accountId}` is **message templating** — Apigee substitutes the flow variable inline. That's how the read half feeds the write half.

!!! pitfall "Watch out"
    `<Set>` **overwrites** a header while `<Add>` **appends** — reach for `<Add>` on a header the client already sent (or a multi-valued one like `Set-Cookie`) and you get duplicate values, not a replacement. Likewise, `<AssignTo createNew="true">` builds a brand-new message rather than editing the current one, so anything already on the in-flight message (headers, body) is *not* carried over unless you `<Copy>` it. Pick the verb deliberately: mutate the existing message, or start clean.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — extract a path param + a JSON field, then reshape the response

You'll take an inbound `POST /accounts/{accountId}/transactions` carrying a small JSON body, **extract** the account id from the path and a field from the body, then use **AssignMessage** to stamp a header and wrap the backend's response in your own envelope. Reuse the `aisp-accounts` proxy (or your passthrough) with `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported.

**1. ExtractVariables — read the path and the body.** Put this in `apiproxy/policies/EV-Request.xml`:

```xml
<ExtractVariables name="EV-Request">
  <Source>request</Source>
  <URIPath>
    <Pattern ignoreCase="true">/accounts/{accountId}/transactions</Pattern>
  </URIPath>
  <JSONPayload>
    <Variable name="consentId">
      <JSONPath>$.Data.ConsentId</JSONPath>
    </Variable>
  </JSONPayload>
  <VariablePrefix>ev</VariablePrefix>
  <IgnoreUnresolvedVariables>true</IgnoreUnresolvedVariables>
</ExtractVariables>
```

!!! pitfall "Watch out"
    A JSONPath or URIPath pattern that doesn't match sets **no variable** — ExtractVariables silently produces nothing rather than erroring, so `ev.consentId` ends up empty and the gap only shows up as a blank value in a downstream template. The `<IgnoreUnresolvedVariables>true</IgnoreUnresolvedVariables>` flag controls whether an *unresolved input* throws or is tolerated; set it only when an empty result is genuinely acceptable, otherwise you'll mask a broken path. Confirm `ev.accountId` and `ev.consentId` actually populated in Trace before trusting them.

**2. AssignMessage — stamp a request header** from what you extracted. `apiproxy/policies/AM-StampHeader.xml`:

```xml
<AssignMessage name="AM-StampHeader">
  <AssignTo type="request"/>
  <Set>
    <Headers>
      <Header name="x-account-context">{ev.accountId}:{ev.consentId}</Header>
    </Headers>
  </Set>
  <IgnoreUnresolvedVariables>true</IgnoreUnresolvedVariables>
</AssignMessage>
```

**3. AssignMessage — reshape the response body** into a typed envelope on the way out. `apiproxy/policies/AM-Envelope.xml`:

```xml
<AssignMessage name="AM-Envelope">
  <AssignTo type="response"/>
  <Set>
    <Payload contentType="application/json">{
  "Meta": { "AccountId": "{ev.accountId}", "InteractionId": "{messageid}" },
  "Data": {responsecontent}
}</Payload>
  </Set>
  <AssignVariable>
    <Name>responsecontent</Name>
    <Ref>response.content</Ref>
  </AssignVariable>
</AssignMessage>
```

The `AssignVariable` captures the backend body into `responsecontent` *before* `Set` overwrites the payload, so the template can nest it under `Data`. Order inside one AssignMessage is `Remove → Copy → Set → AssignVariable`, so capture the body in a **prior** policy step if you need it; here we keep one policy and rely on the template reading the variable.

**4. Attach them at the right points.** ExtractVariables and the header stamp run on the **request** side; the envelope runs on the **response** side. In `apiproxy/proxies/default.xml`:

```xml
<ProxyEndpoint name="default">
  <PreFlow name="PreFlow">
    <Request>
      <Step><Name>EV-Request</Name></Step>
      <Step><Name>AM-StampHeader</Name></Step>
    </Request>
    <Response>
      <Step><Name>AM-Envelope</Name></Step>
    </Response>
  </PreFlow>
  <HTTPProxyConnection><BasePath>/aisp-accounts</BasePath></HTTPProxyConnection>
  <RouteRule name="default"><TargetEndpoint>default</TargetEndpoint></RouteRule>
</ProxyEndpoint>
```

To keep `responsecontent` captured before the `Set` overwrites it, split the response step into a tiny capture policy that runs first, or move the `AssignVariable` into a separate `AM-Capture` attached just before `AM-Envelope`. Either is valid; one policy works because templates resolve against the variable bag at execution time.

**5. Bundle, deploy, and call it:**

```bash
apigeecli apis create bundle --name aisp-accounts --proxy-folder ./aisp-accounts/apiproxy \
  --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name aisp-accounts --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

curl -s "https://$RUNTIME_HOST/aisp-accounts/accounts/A-12345/transactions" \
  -H "content-type: application/json" \
  -H "x-fapi-interaction-id: $(uuidgen)" \
  -d '{"Data":{"ConsentId":"urn:ob:consent:9981"}}' | jq .
```

**What success looks like:** the JSON response is your envelope — a `Meta` object containing `AccountId: "A-12345"` (proving the path extraction worked) and an `InteractionId`, with the backend's original payload nested under `Data`. In Trace you can see `EV-Request` populate `ev.accountId` and `ev.consentId`, and `AM-StampHeader` add `x-account-context: A-12345:urn:ob:consent:9981` to the request the backend received.
</div>

## Verify it

Open the Trace for the request above and step through the policies in order. After `EV-Request` runs, inspect the variables panel — `ev.accountId` should equal `A-12345` and `ev.consentId` should equal `urn:ob:consent:9981`, read straight from the path pattern and the JSON body. After `AM-StampHeader`, the request's header set should include `x-account-context`. After `AM-Envelope` on the response side, `response.content` is your wrapped JSON, not the raw backend body.

A fast confirmation from the shell that extraction and reshaping both landed:

```bash
curl -s "https://$RUNTIME_HOST/aisp-accounts/accounts/A-99999/transactions" \
  -H "content-type: application/json" \
  -d '{"Data":{"ConsentId":"urn:ob:consent:1"}}' \
  | jq -e '.Meta.AccountId == "A-99999" and (.Data != null)' \
  && echo "extract + reshape OK"
```

A different account id in the path changes `Meta.AccountId` with no redeploy — proof the value came from extraction, not a constant.

!!! pitfall "Watch out"
    Policy order is load-bearing: ExtractVariables must run **before** the AssignMessage that templates its output, or `{ev.accountId}` resolves against an empty bag and renders blank. Templates resolve against the variable values at the moment each policy executes, so an extract step placed after the assign step won't retroactively fill in the header — re-check the Step order in `default.xml`, not just the policy XML.

!!! failure "Common failure modes"
    - **ExtractVariables silently did nothing.** A JSONPath that doesn't match sets no variable, and by default the policy can raise on unresolved input. Symptom: a downstream template renders empty, or a `Failed to resolve variable` fault. Fix the path, and set `<IgnoreUnresolvedVariables>true</IgnoreUnresolvedVariables>` only when an empty result is acceptable.
    - **URIPath pattern matched against the wrong string.** `<URIPath>` matches the **proxy path suffix** (everything after the basepath), not the full URL. Symptom: `ev.accountId` is empty even though the URL clearly contains it. Pattern from the suffix, e.g. `/accounts/{accountId}/...`.
    - **Reading the body too late.** Once `Set` overwrites the payload, `response.content` is your new envelope, not the backend's. Symptom: the nested `Data` is your own envelope, recursively. Capture the original body into a variable *before* the `Set` that overwrites it.
    - **Wrong attach point.** A response-reshaping AssignMessage placed on the request flow never sees the backend body; a request reshaper on the response flow never reaches the backend. Symptom: the change "doesn't happen." Re-check ① ② ③ ④ from 2.1.
    - **Streaming enabled.** With request/response streaming on, `request.content` / `response.content` aren't buffered and body extraction returns nothing. Symptom: payload reads are empty only in one environment. Disable streaming on that proxy if you need body access.

!!! stretch "Stretch goal"
    Take a real `ResponseBodyAdvice` from one of your Spring services — say, one that wraps every controller return value in a standard `ApiResponse<T>` envelope and injects a trace id — and reproduce it **entirely** in a single `AssignMessage` on the ProxyEndpoint response flow (point ④), with no Java. Capture the backend body into a variable, build the envelope with message templating, and inject `{messageid}` as the trace id. Then find the one thing your Java advice does that the policy can't express cleanly (conditional shape per content type is the usual one) and decide whether a JavaScript policy — next session — earns its place, or whether a `Condition` on the step is enough.

## Recap & next

You now own the core mediation pair: **ExtractVariables reads** path segments, query params, headers and payload fields into flow variables; **AssignMessage writes** by setting, adding, removing and copying headers and payload, assigning variables, retargeting the backend, or building a whole new message. You know they're split read-from-write on purpose, that they attach at the four points from 2.1, and that message templating (`{var}`) is the wire between them.

**Next — 2.5:** when the declarative pair isn't enough and you need real logic, you choose between a **JavaScript policy** and a **Java callout**. You'll learn the performance and packaging trade-off — and the rule that you reach for declarative policies first, JS for glue, and Java only when you genuinely must.
