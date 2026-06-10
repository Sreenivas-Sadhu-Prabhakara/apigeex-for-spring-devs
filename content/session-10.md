# 2.5 — JavaScript vs Java callouts: the trade-off

!!! bottomline "Bottom line"
    When a declarative policy can't express your logic, you have two escape hatches: a **JavaScript policy** (a `.js` resource that runs in a sandboxed engine with a `context` object) or a **Java callout** (a packaged JAR implementing `Execution`). The rule of thumb is a ladder: **prefer a config policy first, reach for JavaScript for glue, and use Java only when you genuinely need it** — heavy crypto, a mandated library, or CPU-bound work. JavaScript is lighter to ship and debug; Java is heavier but unconstrained.

## Why this exists

2.4 gave you ExtractVariables and AssignMessage — enough to read and reshape almost anything. But "almost" leaves real gaps: compute a hash, derive a value with a loop, call a sidecar service mid-flow, parse a format no policy understands. For those you need actual code at the edge.

In Spring this choice barely exists — *everything* is Java, compiled into one app, and "add some logic" means writing a method. At the gateway the same instinct is a trap. Custom code on the data path runs on **every request**, inside a multi-tenant runtime, and the wrong choice taxes latency or turns a config change into a build-and-redeploy of a JAR.

So Apigee deliberately offers a cheaper rung before full Java. A JavaScript policy is a small script file you drop in `resources/jsc/`; it loads fast, has direct access to the message via `context`, and edits like config. A Java callout is a compiled artifact with the full JVM and any library you bundle — but you own its packaging, its classpath, and its blast radius. Knowing which rung to stand on is the skill this session builds.

!!! bridge "Spring Boot bridge"
    Think of it as choosing how to add custom logic to your request path:

    | You'd reach for, in Spring | Apigee equivalent | Why |
    |---|---|---|
    | A short helper method / inline lambda in a filter | **JavaScript policy** | Lightweight, edited in place, no build step |
    | A `@Component` bean pulling in a third-party library | **Java callout (JAR)** | Packaged dependency, full JVM, compiled |
    | Bean Validation, Jackson mapping, `@CrossOrigin`, header config | **A declarative policy** (ExtractVariables/AssignMessage/JSONThreatProtection/CORS…) | Don't write code for what config already does |

    A JavaScript policy is the lightweight script; a Java callout is the packaged bean with its dependency JARs. The twist is that one runs in a sandboxed JS engine on the data path and the other as a class you compiled and uploaded — so unlike Spring, the *packaging and deploy story* is part of the decision, not an afterthought.

!!! breaks "Where the analogy breaks"
    In Spring your code runs in *your* JVM with your full classpath, your thread pool, and unlimited time. Apigee custom code runs inside a shared, multi-tenant runtime with hard guardrails. A JavaScript policy is **sandboxed**: no filesystem, no arbitrary sockets (network only via the provided `httpClient`), no `require()` of npm modules, and it's killed if it exceeds a time limit. A Java callout is less constrained but still can't fork processes or open raw OS resources, and you must bundle every dependency into the JAR yourself — there's no Maven resolution at the edge. The Spring reflex "I'll just import a library and call it" only survives the trip if you've packaged that library *into* the callout. Treat the runtime as someone else's process you're a guest in, because you are.

## The concept

Both run as policies you attach at one of the four points from 2.1. The difference is what's underneath and what it costs you. A **JavaScript policy** points at a `.js` resource and exposes the request-scoped `context` object — `context.getVariable(...)`, `context.setVariable(...)`, and the message accessors — plus an `httpClient` for fan-out calls. A **Java callout** points at a JAR whose class implements Apigee's `Execution` interface; you get the same `MessageContext` but in Java, with whatever libraries you bundled.

The decision, across the axes that actually matter:

| Axis | Declarative policy | JavaScript policy | Java callout |
|---|---|---|---|
| **Latency / startup** | Lowest — native | Low — script compiles fast, runs in-engine | Higher — JVM class, watch GC and cold paths |
| **Packaging / deploy** | XML only | One `.js` file in `resources/jsc/`, edit in place | Compiled JAR + bundled deps, rebuild to change |
| **Debuggability** | Trace shows the policy | Trace + `print()` to Trace; readable script | Hardest — compiled, logs via callout, opaque in Trace |
| **Power / libraries** | Fixed verbs | JS stdlib + `httpClient`; **no** npm, **no** filesystem | Full JVM + any library you bundle |
| **Sandbox limits** | n/a | Strict: no FS, no raw sockets, time-boxed | Looser, still no process fork / OS resources |
| **When to use** | Anything config can do | Glue, derive a value, light fan-out, small transforms | Heavy crypto, a mandated SDK, CPU-bound work |

Read it top to bottom as a ladder you climb only as far as you must:

```text
1. Can a declarative policy do it?     → use the policy. (90% of cases)
2. Need a few lines of logic / glue?   → JavaScript policy.
3. Need a heavy library or real CPU?   → Java callout, and own its JAR.
```

In Open Banking terms: normalising a header or building an envelope is **declarative** (2.4); deriving an idempotency key or a request hash is **JavaScript**; verifying a detached JWS signature with a full JOSE library, or doing bulk crypto, is where a **Java callout** finally earns its weight.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — derive an idempotency key in JavaScript and time it in Trace

A common FAPI need: stamp each write with a stable **idempotency key** derived from the caller's identity plus the request body, so retries are safe. That's a few lines of logic — a perfect JavaScript-policy job. You'll write it, attach it, and read its timing in Trace. Reuse `aisp-accounts` with `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported.

**1. Write the script.** Put it at `apiproxy/resources/jsc/deriveIdempotencyKey.js`:

```javascript
// Derive a stable idempotency key from client_id + raw body.
// Uses only the sandboxed JS engine — no require(), no filesystem.
var clientId = context.getVariable('client_id') || 'anon';
var body = context.getVariable('request.content') || '';

// small, dependency-free 32-bit hash (djb2) — fine for a derived key
function hash(s) {
  var h = 5381;
  for (var i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;   // h*33 + c
  }
  return (h >>> 0).toString(16);                // unsigned hex
}

var key = clientId + '-' + hash(clientId + ':' + body);
context.setVariable('derived.idempotencyKey', key);
print('derived idempotency key: ' + key);       // surfaces in Trace
```

**2. The JavaScript policy** referencing that resource. `apiproxy/policies/JS-Idempotency.xml`:

```xml
<Javascript name="JS-Idempotency" timeLimit="200">
  <ResourceURL>jsc://deriveIdempotencyKey.js</ResourceURL>
</Javascript>
```

`timeLimit` (ms) is the sandbox guardrail — exceed it and the policy faults instead of hanging the request.

**3. Surface the derived key on the request** with an AssignMessage (from 2.4) so the backend receives it. `apiproxy/policies/AM-IdempotencyHeader.xml`:

```xml
<AssignMessage name="AM-IdempotencyHeader">
  <AssignTo type="request"/>
  <Set>
    <Headers>
      <Header name="x-idempotency-key">{derived.idempotencyKey}</Header>
    </Headers>
  </Set>
</AssignMessage>
```

**4. Attach both on the request side**, after identity is established so `client_id` exists. In `apiproxy/proxies/default.xml`:

```xml
<ProxyEndpoint name="default">
  <PreFlow name="PreFlow">
    <Request>
      <Step><Name>JS-Idempotency</Name></Step>
      <Step><Name>AM-IdempotencyHeader</Name></Step>
    </Request>
  </PreFlow>
  <HTTPProxyConnection><BasePath>/aisp-accounts</BasePath></HTTPProxyConnection>
  <RouteRule name="default"><TargetEndpoint>default</TargetEndpoint></RouteRule>
</ProxyEndpoint>
```

**5. Bundle, deploy, and call it twice with the same body:**

```bash
apigeecli apis create bundle --name aisp-accounts --proxy-folder ./aisp-accounts/apiproxy \
  --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name aisp-accounts --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

for i in 1 2; do
  curl -s -o /dev/null -w "x-idempotency-key echoed\n" \
    "https://$RUNTIME_HOST/aisp-accounts/headers" \
    -H "content-type: application/json" \
    -d '{"Data":{"Amount":"10.00"}}'
done

# start a Trace session, then send one more request into it
apigeecli apis debug create --name aisp-accounts --env "$ENV" --org "$ORG" --token "$TOKEN"
curl -s "https://$RUNTIME_HOST/aisp-accounts/headers" \
  -H "content-type: application/json" -d '{"Data":{"Amount":"10.00"}}' > /dev/null
```

**What success looks like:** in the Apigee Trace, the `JS-Idempotency` policy shows a **timing** (typically a few milliseconds), your `print(...)` line appears in its output, and `derived.idempotencyKey` is set in the variables panel. Two requests with the *same* body produce the *same* key; change the body and the key changes. The backend (mocktarget `/headers`) echoes the `x-idempotency-key` you added, proving the JS value flowed into the request.
</div>

## Verify it

In Trace, click the `JS-Idempotency` step and read its **elapsed time** — this is the number you'd weigh against the work it does. Confirm your `print(...)` output is attached to that step and that `derived.idempotencyKey` appears in the variables list once the policy has run. Then re-run the call with a *different* `Amount` in the body: the derived key must change, proving it's a function of the body and not a constant.

A shell check that the same input is stable across calls:

```bash
HDRS='-H content-type:application/json -d {"Data":{"Amount":"10.00"}}'
a=$(curl -s "https://$RUNTIME_HOST/aisp-accounts/headers" -H "content-type: application/json" \
      -d '{"Data":{"Amount":"10.00"}}' | jq -r '.headers["x-idempotency-key"]')
b=$(curl -s "https://$RUNTIME_HOST/aisp-accounts/headers" -H "content-type: application/json" \
      -d '{"Data":{"Amount":"10.00"}}' | jq -r '.headers["x-idempotency-key"]')
[ "$a" = "$b" ] && echo "idempotency key stable: $a"
```

(The mocktarget `/headers` endpoint reflects received headers as JSON, so `jq` can read the key straight back.)

!!! failure "Common failure modes"
    - **Reaching for JavaScript when a policy would do.** Re-implementing JSON field extraction or header copying in JS is slower and harder to read than ExtractVariables/AssignMessage. Symptom: a 30-line script doing what one declarative policy does. Climb back down the ladder.
    - **Trying to `require()` an npm module or read a file.** The sandbox has neither. Symptom: `ReferenceError: require is not defined` or a file-access exception. If you truly need a library, that's the signal to use a Java callout — not to fight the sandbox.
    - **Blowing the time limit.** A tight loop or a slow `httpClient` call past `timeLimit` faults the policy. Symptom: intermittent `JavaScript runtime exceeded` / timeout. Bound the work, raise `timeLimit` deliberately, or move heavy work off the data path.
    - **Reading the body when streaming is on, or before it's available.** `request.content` is empty under streaming or if accessed at the wrong point. Symptom: the hash is computed over an empty body, so every key collides. Disable streaming for body-dependent scripts.
    - **Choosing Java for convenience, then owning a JAR forever.** A Java callout means a build, a bundled-dependency classpath, and a redeploy for every change, with the worst Trace visibility. Symptom: a one-line change becomes a release. Only pay that cost when crypto/libraries/CPU genuinely demand it.

!!! stretch "Stretch goal"
    Take a small, pure piece of logic from one of your Spring services — a value derivation, a checksum, a normalisation routine with no I/O — and port it into a JavaScript policy. Attach it, run a few requests, and record its per-call timing from Trace. Then reason about the rung above and below: would this be cheaper as a declarative policy (could you express it with AssignMessage and a condition?), and what specifically would force it up to a Java callout (a JOSE/crypto library, real CPU cost)? Write down the threshold in milliseconds and lines-of-logic at which *you* would change rungs — that number is the whole lesson.

## Recap & next

You can now place custom logic on the right rung: **declarative policy first**, **JavaScript** for glue and light derivation (the sandboxed `context`/`httpClient` model, edited as a `.js` resource, time-boxed and Trace-friendly), and a **Java callout** only when a real library, heavy crypto, or CPU-bound work justifies owning a JAR. You wrote a JS policy, fed its output into the request via AssignMessage from 2.4, and read its timing in Trace — the measurement that should drive every one of these choices.

**Next — 2.6:** protection that doesn't run code at all. You'll meet **Quota** and **SpikeArrest** — distributed, product-scoped rate limiting counted across the whole runtime rather than per-pod like Bucket4j or Resilience4j — and learn why "per-instance" rate limiting quietly lies at the edge.

