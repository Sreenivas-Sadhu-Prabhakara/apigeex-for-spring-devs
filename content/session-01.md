# 1.1 — What an API-gateway *product* actually is

!!! bottomline "Bottom line"
    Apigee X is not a gateway you **write** — it's a gateway you **configure and operate**. By the end of this session you can explain what an API-management *product* adds on top of a hand-rolled Spring Cloud Gateway, and name the concerns you'll stop re-implementing in every service.

## Why this exists

You already have a way to put cross-cutting behaviour in front of your services. Maybe it's a Spring Cloud Gateway app, maybe an nginx box, maybe each service doing its own auth and rate limiting. It works — until you have twenty services, three teams, external consumers, an audit, and a regulator.

An **API-management product** exists because "a gateway" is only ~20% of the problem. The other 80% is everything *around* the proxy: who is allowed to call it, how you publish and version it, how you onboard and throttle consumers, how you see what's happening, and how you do all of that **without redeploying a service every time a business rule changes**. Apigee X is that product. The proxy is just the part you can already picture.

!!! bridge "Spring Boot bridge"
    **Spring Cloud Gateway** is a gateway you *code*: routes and filters in Java or YAML, built into a jar, deployed and scaled by you. **Apigee X** is a gateway you *configure*: the same routing and filtering expressed as **policies** in a proxy bundle, but the platform owns runtime, scaling, the analytics pipeline, the developer portal, and an OAuth server. You move from *"I wrote the gateway"* to *"I operate the gateway and own only its configuration."*

| You'd reach for… (Spring) | Apigee X gives you… |
|---|---|
| `GatewayFilter` / `OncePerRequestFilter` | **Policies** attached to a flow |
| Resilience4j `RateLimiter` (per pod) | **Quota** / **SpikeArrest** (distributed) |
| Spring Authorization Server | Built-in **OAuthV2** token server |
| Hand-built API-key table | **API products + apps + developers** |
| Micrometer + a dashboard you wire up | **Analytics** captured at the edge |
| A wiki page of "how to call our API" | A generated **developer portal** |

!!! breaks "Where the analogy breaks"
    Spring Cloud Gateway is **code you control end to end** — you can drop to Java for anything. Apigee proxies are **configuration first**: you compose declarative policies, and custom logic is the *exception* (a JavaScript or Java callout), not the default. If your instinct is "I'll just write a filter for that," pause — most of what you need is a policy you configure, and reaching for code too early is the #1 way Spring developers make Apigee proxies hard to operate.

## The concept

Every Apigee proxy has the same shape: a request enters, travels through configured policies, hits a backend, and the response travels back out through more policies. You'll dissect the four attach points in **session 2.1** — for now, just hold the silhouette:

<figure class="svg-figure">
<img src="assets/svg/flow-pipeline.svg" alt="A request flows Client → ProxyEndpoint → TargetEndpoint → Backend, and the response flows back, with four numbered attach points.">
<figcaption>The shape of every Apigee proxy. A passthrough proxy attaches <em>no</em> policies — it just forwards. Everything this course teaches is "what policy do I attach, and at which of these four points?"</figcaption>
</figure>

The mental shift: in Spring you think *"what code runs for this request?"* In Apigee you think *"what is **configured** to run, and where in the flow?"* Same outcome, different unit of work — a **policy** instead of a bean.

!!! pitfall "Watch out"
    "We already have a gateway" (an nginx box, a Spring Cloud Gateway app) is **not** the same as having API management. A reverse proxy moves bytes; the *product* adds consumers, entitlements, analytics, and lifecycle. Don't let an existing proxy convince the team there's nothing here to adopt — that's how the 80% gets re-built by hand, badly.

## Hands-on lab — audit before you build

You provision your free org in the next session (1.2), so this lab needs no Apigee account. It's the highest-leverage 20 minutes in the course: figure out *what you'd actually move to the edge*.

<div class="lab" markdown="1">
#### Lab — inventory your gateway-able concerns

**1. Pick one real Spring service** you know well. List every cross-cutting concern it currently implements itself. Be honest — most services hide more than you'd think:

```text
[ ] API-key / token validation
[ ] CORS handling
[ ] Rate limiting / throttling
[ ] Request/response logging & correlation IDs
[ ] Payload size limits / input validation
[ ] Response shaping for external consumers
[ ] Retry / circuit-breaking to downstreams
[ ] Caching of idempotent GETs
```

**2. For each, write where it lives today** and whether *every other service re-implements it*. The duplicated ones are your edge candidates.

!!! pitfall "Watch out"
    Be ruthless about the line between *mediation* and *business logic*. "Response shaping for external consumers" is an edge concern; "decide whether this customer is overdrawn" is not. If a concern needs your domain model to do its job, it stays in the service — putting it at the edge couples the gateway to your data and is the single most common Apigee design mistake.

**3. Read the anatomy of a proxy bundle** — this is the artifact you'll be editing for the rest of the course. A passthrough proxy is just this:

```text
apiproxy/
├── my-first-proxy.xml          # the proxy: name, basepath, which policies exist
├── proxies/
│   └── default.xml             # ProxyEndpoint: the client-facing flow + RouteRule
├── targets/
│   └── default.xml             # TargetEndpoint: the backend URL + backend-facing flow
└── policies/                   # (empty for a passthrough — you add policies here)
```

**4. Read the two files that define behaviour.** The ProxyEndpoint declares the basepath and where to route:

```xml
<ProxyEndpoint name="default">
  <HTTPProxyConnection>
    <BasePath>/v1/hello</BasePath>     <!-- clients call https://HOST/v1/hello -->
  </HTTPProxyConnection>
  <RouteRule name="default">
    <TargetEndpoint>default</TargetEndpoint>
  </RouteRule>
</ProxyEndpoint>
```

The TargetEndpoint declares the backend — the one URL this proxy forwards to:

```xml
<TargetEndpoint name="default">
  <HTTPTargetConnection>
    <URL>https://mocktarget.apigee.net</URL>
  </HTTPTargetConnection>
</TargetEndpoint>
```

**What success looks like:** you can point at each file and say *"this is the route"* and *"this is the backend,"* and you have a written list of 3–8 concerns your Spring services duplicate that belong at the edge. You'll attach a real policy to exactly this skeleton in session 1.3.
</div>

!!! verify "Verify it"
    You're ready to move on when you can answer, without looking back:

    - What's the difference between a **gateway** and an **API-management product**? *(The product is the 80% around the proxy: consumers, publishing, analytics, lifecycle.)*
    - In Apigee, what is the **unit of work** you author instead of a Java filter? *(A **policy**, attached to a point in the flow.)*
    - Which file says *"clients call `/v1/hello`"* and which says *"forward to `mocktarget`"*? *(ProxyEndpoint basepath; TargetEndpoint URL.)*

## Common failure modes

!!! failure "What trips up Spring developers first"
    - **"I'll just code it."** Treating the proxy as a place to write Java. Custom code is the exception; reach for a configured policy first. *(Symptom: a proxy that's 90% JavaScript callouts.)*
    - **Putting business logic at the edge.** The gateway mediates and protects; it does not own domain logic. Order calculation stays in your service. *(Symptom: the proxy "knows" about your data model.)*
    - **Thinking per-instance.** Your Resilience4j limiter counts per pod; Apigee Quota counts across the whole runtime. Expecting per-instance behaviour gives surprising numbers. *(Covered in 2.6.)*
    - **Conflating proxy and product.** The proxy is the runtime; the **API product** is who-can-call-what. They're different objects — that distinction unlocks everything in Part 3.

## Stretch goal

!!! stretch "Stretch goal"
    Take the list of duplicated concerns from the lab and sketch a one-page "edge vs service" boundary for your team: which concerns move to Apigee, which stay in the service, and *why*. Bring a concrete one (say, API-key validation) all the way through to the question: *what breaks in our services the day we delete that code and trust the edge instead?* You'll have a real answer by the end of Part 3.

## Recap & next

You can now articulate what a gateway *product* adds over a coded gateway, name the policy as Apigee's unit of work, and read a passthrough bundle. You also have a list of concerns worth moving to the edge — the backlog this whole course works through.

**Next — 1.2:** stand up the platform itself. You'll map Apigee's control-plane / runtime split and the **org → environment → environment group → instance** hierarchy (your Spring profiles, promoted to first-class platform objects) and provision a **free evaluation org** you'll use for every lab from here on.
