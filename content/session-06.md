# 2.1 — The flow model & request/response symmetry

!!! bottomline "Bottom line"
    An Apigee proxy is **two pipelines, run in both directions** — a ProxyEndpoint (client-facing) and a TargetEndpoint (backend-facing), each with a **request** flow and a **response** flow. That's **four attach points**, and knowing which one a policy belongs in is the single most important skill in proxy development. This session corrects the most common Spring misconception: *"it's just a filter chain."*

## Why this exists

In Spring you have one ordered chain of filters wrapping a request. Mentally it's a stack: filters run top-down on the way in, the handler runs, then `afterCompletion` unwinds bottom-up on the way out. One chain, one place to reason about.

Apigee is **not** one chain. The request crosses **two endpoints** — it's processed once as it leaves the client side (ProxyEndpoint), again as it enters the backend side (TargetEndpoint) — and the response is processed twice on the way back. The reason is decoupling: the client-facing contract and the backend-facing contract are *different things you want to evolve independently*. The same separation that makes you put an adapter between your controller and your downstream client — except here it's structural, and symmetric.

## The concept

<figure class="svg-figure">
<img src="assets/svg/flow-pipeline.svg" alt="Request flows Client → ProxyEndpoint(1) → TargetEndpoint(2) → Backend; response flows Backend → TargetEndpoint(3) → ProxyEndpoint(4) → Client.">
<figcaption>The four attach points. <b>1</b> ProxyEndpoint request · <b>2</b> TargetEndpoint request · <b>3</b> TargetEndpoint response · <b>4</b> ProxyEndpoint response. A policy lives at exactly one of these.</figcaption>
</figure>

Within **each** of those four flows, policies run in a fixed sub-order:

- **PreFlow** — always runs first. Cross-cutting things: verify the key, check the quota.
- **Conditional Flows** — at most one matches (by path + verb), like routing to a controller method.
- **PostFlow** — always runs last. Final touches: add a header, shape the body.

So the *full* journey of a request is: `ProxyEndpoint PreFlow → ProxyEndpoint Flows → ProxyEndpoint PostFlow → [RouteRule picks a target] → TargetEndpoint PreFlow → TargetEndpoint Flows → TargetEndpoint PostFlow → backend`. The response retraces it in reverse, target side first.

Step a request through it — click **Send a request**, then click any stage:

```widget
{
  "type": "pipeline",
  "title": "One request, four attach points",
  "stages": [
    {"name": "Proxy PreFlow", "phase": "req", "desc": "ProxyEndpoint request. Cross-cutting inbound policies: VerifyAPIKey, SpikeArrest, CORS. The earliest you can reject a bad request — reject here and the backend is never touched."},
    {"name": "Proxy Flows", "phase": "req", "desc": "ProxyEndpoint request, conditional. The flow whose condition matches the path+verb runs — like dispatching to a @GetMapping method."},
    {"name": "Proxy PostFlow", "phase": "req", "desc": "ProxyEndpoint request, last. Final inbound shaping before routing."},
    {"name": "RouteRule", "phase": "route", "desc": "Choose the TargetEndpoint (or none). This is where the client-facing side hands off to the backend-facing side."},
    {"name": "Target PreFlow", "phase": "req", "desc": "TargetEndpoint request. Backend-facing concerns: add the backend auth header, rewrite the path the backend expects."},
    {"name": "Target Flows + send", "phase": "req", "desc": "TargetEndpoint request flows run, then Apigee calls the backend."},
    {"name": "Target PostFlow", "phase": "res", "desc": "TargetEndpoint response. First chance to act on the backend's reply — normalise its errors before the client side ever sees them."},
    {"name": "Proxy PostFlow", "phase": "res", "desc": "ProxyEndpoint response, last. The client-facing contract: hide internal headers, shape the final body, add correlation IDs."}
  ]
}
```

!!! bridge "Spring Boot bridge"
    A Spring `HandlerInterceptor` gives you `preHandle` (before the controller) and `postHandle` / `afterCompletion` (after). Map them on:

    | Spring `HandlerInterceptor` | Closest Apigee attach point |
    |---|---|
    | `preHandle` | **Proxy PreFlow (request)** — point ① |
    | the controller method | a **conditional Flow** in the ProxyEndpoint |
    | `postHandle` / `afterCompletion` | **Proxy PostFlow (response)** — point ④ |

    The intuition "stuff before, stuff after" is right. What Spring *doesn't* have is the **second endpoint** — points ② and ③ — the backend-facing pipeline.

!!! breaks "Where the analogy breaks"
    Two things have no Spring equivalent, and both bite:

    1. **Symmetry, not a stack.** It is not one chain that unwinds. The request side and response side are *separate flows you configure separately*. A policy in the request flow does **not** automatically have a mirror on the way out — if you set a header inbound and want it gone outbound, that's two policies at two points.
    2. **Two endpoints, two contracts.** Points ②/③ (TargetEndpoint) exist so the backend-facing message can differ from the client-facing one. Rewrite the path for the backend at ②; normalise the backend's ugly 500 into your API's error shape at ③ — *before* the client-facing PostFlow at ④ ever runs. In Spring you'd jam all of this into one filter; here, putting it at the wrong endpoint means it runs against the wrong message.

## Hands-on lab — make all four points visible

You'll attach a trivial `AssignMessage` at each of the four points so that a single request leaves a fingerprint at every stage, then read it in Trace. This makes the abstract flow *concrete*.

<div class="lab" markdown="1">
#### Lab — one header per attach point

**Prereqs:** your eval org from 1.2 and the passthrough proxy from 1.3, with `$ORG`, `$ENV`, `$TOKEN`, and `$RUNTIME_HOST` exported.

**1. Four AssignMessage policies** — each stamps one header so you can see where it ran. Put these in `apiproxy/policies/`:

```xml
<!-- AM-Point1.xml : ProxyEndpoint request -->
<AssignMessage name="AM-Point1">
  <Set><Headers><Header name="x-flow-1-proxy-req">hit</Header></Headers></Set>
</AssignMessage>
```
```xml
<!-- AM-Point2.xml : TargetEndpoint request -->
<AssignMessage name="AM-Point2">
  <Set><Headers><Header name="x-flow-2-target-req">hit</Header></Headers></Set>
</AssignMessage>
```
```xml
<!-- AM-Point3.xml : TargetEndpoint response -->
<AssignMessage name="AM-Point3">
  <Set><Headers><Header name="x-flow-3-target-res">hit</Header></Headers></Set>
</AssignMessage>
```
```xml
<!-- AM-Point4.xml : ProxyEndpoint response -->
<AssignMessage name="AM-Point4">
  <Set><Headers><Header name="x-flow-4-proxy-res">hit</Header></Headers></Set>
</AssignMessage>
```

**2. Attach them at the right points.** In `proxies/default.xml` (the ProxyEndpoint), Step ① goes in the **request** PreFlow, Step ④ in the **response** PreFlow:

```xml
<ProxyEndpoint name="default">
  <PreFlow name="PreFlow">
    <Request><Step><Name>AM-Point1</Name></Step></Request>
    <Response><Step><Name>AM-Point4</Name></Step></Response>
  </PreFlow>
  <HTTPProxyConnection><BasePath>/v1/hello</BasePath></HTTPProxyConnection>
  <RouteRule name="default"><TargetEndpoint>default</TargetEndpoint></RouteRule>
</ProxyEndpoint>
```

In `targets/default.xml` (the TargetEndpoint), Step ② is the **request** side, Step ③ the **response** side:

```xml
<TargetEndpoint name="default">
  <PreFlow name="PreFlow">
    <Request><Step><Name>AM-Point2</Name></Step></Request>
    <Response><Step><Name>AM-Point3</Name></Step></Response>
  </PreFlow>
  <HTTPTargetConnection><URL>https://mocktarget.apigee.net</URL></HTTPTargetConnection>
</TargetEndpoint>
```

**3. Deploy a new revision and start a debug session:**

```bash
apigeecli apis create bundle --name hello-proxy --proxy-folder ./hello-proxy/apiproxy \
  --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name hello-proxy --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

# open a 60s debug session, then send a request into it
apigeecli apis debug create --name hello-proxy --env "$ENV" --org "$ORG" --token "$TOKEN"
curl -s "https://$RUNTIME_HOST/v1/hello/json" -H "x-fapi-interaction-id: $(uuidgen)" -i | grep -i x-flow
```

**What success looks like:** the response carries `x-flow-3-...` and `x-flow-4-...` (the two response-side points the client can see), and the **Trace** in the Apigee UI shows all four AssignMessage executions in order: 1 and 2 on the way in, 3 and 4 on the way out. Seeing them line up — request side, then *backend*, then response side — is the whole point of the session.
</div>

!!! verify "Verify it"
    - In the Trace timeline, `AM-Point1` runs **before** the backend call and `AM-Point3` runs **after** it. If `AM-Point3` shows on the request side, you attached it to the wrong flow.
    - Move `AM-Point2` from the TargetEndpoint request to the ProxyEndpoint request and redeploy: the header still appears, but now the *backend* sees it set one step earlier. That difference — *which message carries the change* — is exactly why the two endpoints exist.

## Common failure modes

!!! failure "Flow-model mistakes"
    - **Right policy, wrong point.** A backend auth header set at point ④ (proxy response) never reaches the backend — it had to be point ② (target request). Symptom: "the backend says 401 but my header is right there in the response."
    - **Assuming a mirror.** Setting something in the request flow does not unset it in the response flow. Outbound cleanup is its own policy at point ③ or ④.
    - **Stuffing everything in Proxy PreFlow.** It runs for *every* path. Endpoint-specific logic belongs in a **conditional Flow**, not PreFlow — otherwise it fires where it shouldn't.
    - **Forgetting PostFlow always runs.** Even when a conditional flow matched, PostFlow still executes. Don't duplicate work you already did in the matched flow.

## Stretch goal

!!! stretch "Stretch goal"
    Take a `HandlerInterceptor` (or `OncePerRequestFilter`) from one of your Spring services and map each of its responsibilities onto one of the four Apigee points. Find the one responsibility that *doesn't* map cleanly to a single point — almost every real interceptor has one — and write down why. That mismatch is usually a sign the interceptor is doing two jobs that Apigee would split across the two endpoints.

## Recap & next

You now hold the keystone: **two endpoints, four attach points, PreFlow/Flows/PostFlow within each**, and you can prove where a policy ran using Trace. Every later session is "which policy, attached where?" — and you can now answer the *where*.

**Next — 2.2:** the **message and flow-variable model** — the typed, request-scoped context (`request.header.*`, `response.status.code`, your own variables) that every policy reads and writes. It's the gateway's answer to `ServletRequest` attributes, and it's how those four points actually talk to each other.
