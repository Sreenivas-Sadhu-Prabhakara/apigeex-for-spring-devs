# 2.2 — The message & flow-variable model

!!! bottomline "Bottom line"
    Every policy in a proxy reads and writes one shared, request-scoped context made of **flow variables** — typed values with **dotted names** like `request.verb`, `response.status.code`, or your own `custom.tppId`. The verb, headers, query params, body and status all live on a **message object** (both the request and the response *are* Messages), and you reach into them with `ref=`. This is the gateway's answer to `ServletRequest` attributes, except the schema is fixed, the names are namespaced, and the lifetime spans all four attach points from 2.1.

## Why this exists

In a Spring controller you rarely think about "the context" as a thing — you have method parameters (`@RequestHeader`, `@RequestBody`, `@PathVariable`), a `HttpServletRequest` you can call `getAttribute`/`setAttribute` on, and a `SecurityContext` off to the side. They're separate APIs you reach for case by case. Apigee unifies all of that into **one flat namespace of flow variables** that every policy shares. There is no "method signature" — a policy doesn't declare what it consumes; it just references the variable it wants by name.

That matters because policies are decoupled XML, not method calls. Session 2.1 gave you *where* a policy runs (four attach points); flow variables are *how those points communicate*. A VerifyAPIKey at point ① doesn't return a value to a Quota policy three steps later — it **populates `verifyapikey.VK-Key.client_id`**, and the Quota reads it. The shared variable bag is the only wiring between policies, so understanding its schema, scope and types is the difference between confidently building flows and poking at a black box.

The reason it's *typed* and *namespaced* (rather than a loose `Map<String,String>`) is that the gateway has to know that `response.status.code` is an integer it can compare with `>=`, that `request.header.x-fapi-interaction-id` might be multi-valued, and that `message.content` is a body it can parse. The dotted name encodes both where the value comes from and what shape it has.

!!! bridge "Spring Boot bridge"
    Flow variables are a request-scoped `Map<String,Object>` — the closest single analogue is `ServletRequest` attributes (`request.setAttribute("k", v)` / `getAttribute("k")`) for your *custom* values, plus the framework-populated accessors for the built-ins. The mapping:

    | Spring | Apigee flow variable | Notes |
    |---|---|---|
    | `request.getMethod()` | `request.verb` | `"GET"`, `"POST"` … a String |
    | `request.getHeader("x-api-key")` | `request.header.x-api-key` | header lookup by name |
    | `request.getParameter("from")` | `request.queryparam.from` | query string |
    | `@RequestBody` / `getInputStream()` | `request.content` | the raw body |
    | `response.getStatus()` | `response.status.code` | an **integer**, not a String |
    | `request.setAttribute("k", v)` | `AssignVariable` → `custom.k` | your own request-scoped value |
    | `request.getAttribute("k")` | `ref="custom.k"` on any later policy | read it back downstream |

    The mental model "set something early, read it later in the same request" transfers exactly. What changes is that the names are **fixed and dotted**, and the framework pre-populates a huge catalogue of them for you (`request.*`, `system.*`, `client.*`) before your first policy ever runs.

!!! breaks "Where the analogy breaks"
    Three mismatches bite. First, **it's not a free-form `Map<String,String>`** — built-in variables are typed (int, boolean, message, collection) and many are **read-only**; trying to `AssignVariable` over `system.time` silently does nothing. Second, **scope and lifetime are flow-wide, not endpoint-wide**: a variable you set at point ① is visible at points ②/③/④, but it lives only for *that one request* and is gone the instant the response leaves — there is no session, no thread-local that outlives the exchange (that's what KVMs and cache are for, in later sessions). Third, **request and response are the same kind of object (a Message), but they are two different instances** — `message.*` resolves to *whichever message the current flow is processing*, so `message.status.code` means nothing in a request flow and everything in a response flow. Reaching for `response.*` while still on the request side gets you an empty value, not an error.

## The concept

A **Message** is the gateway's model of an HTTP message. Both the request and the response are Messages, with the same shape:

| Part of the message | On the request | On the response |
|---|---|---|
| verb (method) | `request.verb` | — |
| status | — | `response.status.code` (int) |
| a header | `request.header.NAME` | `response.header.NAME` |
| all header names | `request.headers.names` | `response.headers.names` |
| a query param | `request.queryparam.NAME` | — |
| the body | `request.content` | `response.content` |
| content length | `request.header.Content-Length` | `response.header.Content-Length` |

The generic prefix **`message.*`** is an alias for "the message the current flow is acting on": in a *request* flow `message` == the request; in a *response* flow `message` == the response. Use `message.*` when a policy should work on both sides; use the explicit `request.*` / `response.*` when you mean one specific message regardless of which flow you're in.

Variables fall into a handful of **namespaces**. Knowing the namespace tells you who owns the value and roughly when it appears:

```text
request.*     verb, headers, queryparams, content, path     (populated as the request arrives)
response.*    status.code, headers, content                  (only meaningful after the backend replies)
message.*     alias → request in req flows, response in res flows
system.*      system.time, system.uuid, system.timestamp     (gateway/runtime facts, read-only)
client.*      client.ip, client.received.start.timestamp      (the TCP/TLS peer)
proxy.*       proxy.pathsuffix, proxy.basepath, proxy.url     (this proxy's routing facts)
target.*      target.url, target.received.status.code         (the backend leg)
custom        (no fixed prefix — whatever YOU name it, e.g. tpp.id, flags.isHighValue)
<policy>.*    verifyapikey.VK-Key.client_id, oauthv2.*, ratelimit.* (a policy's own outputs)
```

You **read** a variable by pointing a policy attribute at it with `ref=` (for example `<APIKey ref="request.header.x-api-key"/>` in 3.2). You **write** a custom variable with **AssignMessage** (`<AssignVariable><Name>…</Name>`) or, more surgically, the **AssignVariable** policy — both covered in depth in 2.4. The key idea for *this* session: a custom variable you set early is just another entry in the same bag, read back later with the same `ref=`.

A few type notes that trip people up:

- `response.status.code` is an **integer** — compare it with `response.status.code >= 500`, not `= "500"`.
- Headers can be **multi-valued**: `request.header.X` gives the first/joined value; `request.header.X.values.count` and `request.header.X.N` (1-indexed) give the parts.
- A variable you reference but never set resolves to **null/empty**, not an error — conditions treat it as false-ish, which is usually what you want but occasionally hides a typo.

!!! pitfall "Watch out"
    Because an unset variable silently resolves to null instead of failing, a typo in a dotted name (`request.headers.x-api-key` plural vs `request.header.x-api-key` singular) produces no error — just a quietly empty value. Guard conditions that read optional values with this in mind, and reach for Trace to confirm a variable actually got populated rather than trusting that the name was right.

## Hands-on lab

You'll set a custom flow variable as early as possible (Proxy request PreFlow, point ① from 2.1), then read it back near the end of the flow (Proxy response PreFlow, point ④), proving the value survives the whole journey. Then you'll watch both the set and the read in a Trace.

<div class="lab" markdown="1">
#### Lab — set a variable early, read it late, see it in Trace

**Prereqs:** the passthrough proxy from 1.3 with `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported.

**1. AssignMessage to mint a custom variable** on the request side. It stamps a request-scoped `custom.tppId` derived from a built-in (the interaction id header), plus a couple of built-ins so you can see types. Save as `apiproxy/policies/AM-SetContext.xml`:

```xml
<AssignMessage name="AM-SetContext">
  <AssignVariable>
    <Name>custom.tppId</Name>
    <Ref>request.header.x-fapi-interaction-id</Ref>
    <Value>anonymous</Value>
  </AssignVariable>
  <AssignVariable>
    <Name>custom.receivedAt</Name>
    <Ref>system.timestamp</Ref>
  </AssignVariable>
  <AssignVariable>
    <Name>custom.isAccountsCall</Name>
    <Template>{proxy.pathsuffix}</Template>
  </AssignVariable>
</AssignMessage>
```

The `<Value>` is the fallback used when the `<Ref>` is null — so a caller that omits the header gets `custom.tppId = anonymous` rather than an empty variable.

!!! pitfall "Watch out"
    Header names look up by `request.header.NAME` (singular), and matching can surprise you: lookups are case-insensitive on the name but a header that arrives **multi-valued** gives you only the first/joined value through `request.header.X` — use `request.header.X.N` (1-indexed) for the parts. Drop the `<Value>` fallback and a missing `<Ref>` leaves the variable empty rather than defaulted, which then propagates silently down the flow.

**2. AssignMessage to read it back** on the response side and surface it to the client as a header, so you can confirm it survived. Save as `apiproxy/policies/AM-EchoContext.xml`:

```xml
<AssignMessage name="AM-EchoContext">
  <Set>
    <Headers>
      <Header name="x-debug-tpp-id">{custom.tppId}</Header>
      <Header name="x-debug-received-at">{custom.receivedAt}</Header>
      <Header name="x-debug-path">{custom.isAccountsCall}</Header>
    </Headers>
  </Set>
</AssignMessage>
```

The `{custom.tppId}` syntax is **message templating** — it inlines the flow variable's value into the header. That's the same read you'd do with `ref=`, expressed in a string context.

**3. Attach them at opposite ends of the flow.** In `proxies/default.xml`, set on the **request** PreFlow (point ①), read on the **response** PreFlow (point ④) — the maximum distance within the proxy endpoint:

```xml
<ProxyEndpoint name="default">
  <PreFlow name="PreFlow">
    <Request><Step><Name>AM-SetContext</Name></Step></Request>
    <Response><Step><Name>AM-EchoContext</Name></Step></Response>
  </PreFlow>
  <HTTPProxyConnection><BasePath>/v1/hello</BasePath></HTTPProxyConnection>
  <RouteRule name="default"><TargetEndpoint>default</TargetEndpoint></RouteRule>
</ProxyEndpoint>
```

**4. Deploy and open a debug session, then send a request into it:**

```bash
apigeecli apis create bundle --name hello-proxy --proxy-folder ./hello-proxy/apiproxy \
  --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name hello-proxy --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

apigeecli apis debug create --name hello-proxy --env "$ENV" --org "$ORG" --token "$TOKEN"
ID="$(uuidgen)"
curl -s "https://$RUNTIME_HOST/v1/hello/json" -H "x-fapi-interaction-id: $ID" -i | grep -i x-debug
```

**What success looks like:** the response carries `x-debug-tpp-id` equal to the UUID you sent (and `anonymous` when you omit the header), a numeric `x-debug-received-at` (proving `system.timestamp` is a real value, not a literal), and `x-debug-path` showing `/json`. In the **Trace**, `AM-SetContext` shows `custom.tppId` *appearing* in the variables panel at point ①, and `AM-EchoContext` *reading the same value unchanged* at point ④ — one request, the bag carried it the whole way.
</div>

## Verify it

In the Apigee Trace, click `AM-SetContext` and inspect the **Variables** tab: you should see `custom.tppId`, `custom.receivedAt`, and `custom.isAccountsCall` listed with their assigned values — they did not exist before this policy ran. Click any later step and confirm they're still present and unchanged, which proves the **lifetime** spans the flow.

!!! pitfall "Watch out"
    A custom variable set on the **request** side (point ①) is still readable on the **response** side (point ④) because scope spans all four attach points for one request — but only for that request. Don't expect it to survive into the *next* call; the instant the response leaves, the whole bag is gone. If you need persistence across requests, that's a Cache or KVM, not a flow variable.

Confirm the **types** behave: omit the interaction-id header and the response shows `x-debug-tpp-id: anonymous`, demonstrating the null-Ref fallback. A quick scripted check that the value round-trips:

```bash
ID="$(uuidgen)"
GOT="$(curl -s "https://$RUNTIME_HOST/v1/hello/json" -H "x-fapi-interaction-id: $ID" -D - -o /dev/null \
  | awk -F': ' 'tolower($1)=="x-debug-tpp-id"{print $2}' | tr -d '\r')"
[ "$GOT" = "$ID" ] && echo "round-trip OK: $GOT" || echo "MISMATCH sent=$ID got=$GOT"
```

It should print `round-trip OK` with your UUID — the variable you set at point ① is the one you read at point ④.

!!! failure "Common failure modes"
    - **Reading `response.*` in a request flow (or vice-versa).** `response.status.code` is empty until the backend replies; referencing it at point ① resolves to null, not an error. Symptom: a header or condition that's mysteriously always empty/false on the request side.
    - **Treating a status as a String.** `response.status.code = "200"` may not match because the variable is an integer. Use numeric comparisons (`response.status.code >= 500`).
    - **Typo in a dotted name.** `request.headers.x-api-key` (plural) vs `request.header.x-api-key` (singular) — the wrong one resolves to null silently. There's no compile-time check; Trace is how you catch it.
    - **Assuming variables outlive the request.** Flow variables vanish when the response leaves. Wanting a value to persist across requests means a Cache or KVM, not a flow variable.
    - **Writing to a read-only built-in.** AssignVariable over `system.time` or `client.ip` is a no-op. Put your value in the `custom` namespace (any name you own).

!!! stretch "Stretch goal"
    Enumerate the built-in variables Apigee populates **after VerifyAPIKey** (`verifyapikey.<name>.client_id`, `.apiproduct.name`, `.developer.email`, `.apiproduct.developer.quota.limit`, and friends — Trace them from the 3.2 lab) and line them up against what your Spring `SecurityContext` / `Authentication` exposes after authentication (`getName()`, `getAuthorities()`, principal details). Note which Apigee variables have **no** SecurityContext equivalent (the quota limit, the product name) — those are the entitlement facts Apigee carries in the same bag as identity, which Spring keeps in a separate config source.

## Recap & next

You now have the second half of the proxy's mental model: **the message object** (request and response are both Messages, with verb/headers/queryparams/content/status), the **flow-variable namespaces** (`request.*`, `response.*`, `message.*`, `system.*`, your `custom` values, and per-policy outputs), how to **read** them with `ref=`/templating and **write** them with AssignMessage/AssignVariable, and the fact that they're **typed** and live for exactly **one request** across all four attach points. Combined with 2.1's *where*, you can now reason about *what data* flows between policies.

**Next — 2.3:** put those variables to work as **predicates** — conditions, RouteRules and conditional flows let you branch and route declaratively (`proxy.pathsuffix MatchesPath "/accounts/*"`, `request.verb = "GET"`) instead of writing if/switch logic in controller code.
