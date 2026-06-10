# 1.5 — The Trace tool is your gateway debugger

!!! bottomline "Bottom line"
    When a proxy doesn't behave the way your `curl` predicted, **Trace** (the Debug API) is how you see inside the running request. It records every policy that executed, in order, with the full set of flow variables *before and after* each step — the gateway's equivalent of stepping through code with a breakpoint and a watch window. By the end you can open a session, fire a request into it, and point at exactly which policy ran and what each one changed.

## Why this exists

When a Spring request misbehaves, you don't read it back from the logs and guess. You set a breakpoint, you step, and you *watch* the variables mutate line by line — you see the value go wrong at a specific frame. The bug stops being "the response is 401" and becomes "this filter set `authenticated=false` *here*."

A gateway needs the same thing, because a proxy is even more opaque than your code: there's no source file to step through, just a chain of declarative policies you didn't write line-by-line, mutating a shared message as it flows. Logs tell you the *outcome*; they don't tell you that `ExtractVariables` populated an empty string because the JSONPath missed, which made the condition on the next policy fall through, which is why the wrong target was chosen. **Trace** captures that entire causal chain for a single request: each policy as a timeline step, and the flow variables snapshotted at every step so you can see the exact moment a value became wrong.

It's the tool you'll reach for in nearly every later session — when a condition doesn't match, when a header isn't where the backend expects it, when a token verifies in `curl` but not through the proxy. Learn it now, on a trivial proxy, so it's reflex when the proxy is complicated.

!!! bridge "Spring Boot bridge"
    Trace maps almost one-to-one onto the debugger you already use:

    | IDE debugger | Apigee Trace |
    |---|---|
    | A breakpoint on a line | A **policy step** in the transaction timeline |
    | The call stack / step-over | The ordered list of executed policies |
    | The **Variables / watch** pane | Flow variables snapshotted at each step |
    | Conditional breakpoint | A flow **condition** that did or didn't match |
    | "Step into" the framework | Seeing PreFlow → Flows → PostFlow expand |

    The instinct "set a breakpoint, then look at the variables right there" is exactly right. The difference is that Trace is *retrospective and per-request* — you don't pause the world; you record one request and read the whole filmstrip afterward.

!!! breaks "Where the analogy breaks"
    A debugger pauses execution — the thread is frozen on the line, the rest of the system waits, and you can change values and resume. Trace never pauses anything: the request runs to completion at full speed and Trace hands you the *recording*. You cannot edit a variable mid-flight or "resume," and you can't step backward into a branch that wasn't taken. It's also sampled and bounded — a debug session captures a fixed number of transactions (default around ten) over a short window, then stops on its own; it is a diagnostic, never something you leave running in production. And because it records *everything*, by default it captures sensitive values too — masking those (tokens, PANs, consent data) is its own concern, covered in **3.1**, and you should assume an unmasked Trace is as sensitive as a heap dump.

## The concept

Trace records one journey through the same pipeline you'll dissect in 2.1. For now, hold the silhouette: a request enters, crosses the attach points, hits the backend, and the response retraces them. Trace's job is to tell you *which policy ran at each of these points, and what the variables were when it did*.

<figure class="svg-figure">
<img src="assets/svg/flow-pipeline.svg" alt="A request flows Client → ProxyEndpoint → TargetEndpoint → Backend and the response flows back, with four numbered attach points.">
<figcaption>Trace shows you <em>which policy executed at each of these points</em>, in order, with the flow-variable values it read and set. You don't need the four attach points memorised yet — that's session 2.1. Today you just read the recording.</figcaption>
</figure>

Mechanically: you **start a debug session** on a specific revision in a specific environment. That opens a short recording window. Any request that hits that revision while the window is open is captured as a **transaction** — an ordered timeline of every policy that executed, each step carrying the flow variables as they stood at that moment. You then **read** the session: walk the timeline, click a step, and compare the variable state before and after to see precisely what that policy mutated.

!!! pitfall "Watch out"
    A debug session is **time-boxed and samples traffic**, not a permanent tap — it captures a fixed number of transactions over a short window, then closes itself. A request can be perfectly valid and still never appear in the trace because it landed after the window closed, or hit a different instance/environment than the one you're recording. "Nothing captured" usually means a session problem, not a proxy bug.

Three reading moves cover almost everything:

- **Step** — walk the timeline top to bottom. The order *is* the execution order, so a policy you expected that isn't in the list simply never ran (usually a condition that didn't match).
- **Watch** — pick a variable (say `request.header.x-fapi-interaction-id` or your own `extracted.account`) and follow its value down the timeline to find the step where it first appears or goes wrong.
- **Inspect** — open a single step and read the full variable set and the policy's own status, including any fault it raised.

!!! pitfall "Watch out"
    Trace records *everything*, so an unmasked recording captures tokens, PANs, and consent data in plaintext — treat `trace.json` as sensitive as a heap dump, and don't paste it into a ticket. Masking is its own concern, covered in **3.1**. Trace also adds per-request overhead, so it's a diagnostic you open and close — never something you leave running in production.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — open a Trace and read what each policy did

You'll start a debug session on `hello-proxy`, send one request into it, and read back the timeline — then add a tiny `AssignMessage` and watch the variable it sets appear at exactly one step.

**Prereqs:** `hello-proxy` deployed in `eval` (from 1.3/1.4) with `$ORG`, `$ENV`, `$TOKEN`, and `$RUNTIME_HOST` exported, and the deployed revision known. Capture it so the commands target the right artifact:

```bash
REV=$(apigeecli apis listdeploy --name hello-proxy --org "$ORG" --token "$TOKEN" \
  | jq -r '.deployments[] | select(.environment=="'"$ENV"'") | .revision')
echo "tracing revision $REV"
```

**1. Open a debug session** on that revision. The returned session id is the recording window's handle:

```bash
SESSION=$(apigeecli apis debug create --name hello-proxy --rev "$REV" \
  --env "$ENV" --org "$ORG" --token "$TOKEN" | jq -r '.name')
echo "session: $SESSION"
```

!!! pitfall "Watch out"
    Open the session and fire the request **promptly, in this order** — the recording window starts closing the moment you create it. If you pause too long (or send the request first), the window can lapse and `debug list` comes back empty even though the `curl` succeeded. Derive `$REV` from `listdeploy` too: trace the *deployed* revision, or your requests hit a revision the session isn't watching.

**2. Send a request into the open window** so there's a transaction to capture. The interaction id gives you something distinctive to watch later:

```bash
IID=$(uuidgen)
curl -s -o /dev/null "https://$RUNTIME_HOST/v1/hello/json" \
  -H "x-fapi-interaction-id: $IID"
echo "sent $IID"
```

**3. List the captured transactions, then fetch one** to read its timeline. Each transaction id is one recorded request:

```bash
apigeecli apis debug list --name hello-proxy --rev "$REV" \
  --session "$SESSION" --env "$ENV" --org "$ORG" --token "$TOKEN"

# grab the first transaction id from that list, then pull the full recording
TX="<paste a transaction id>"
apigeecli apis debug get --name hello-proxy --rev "$REV" \
  --session "$SESSION" --transaction "$TX" \
  --env "$ENV" --org "$ORG" --token "$TOKEN" > trace.json
```

**4. Read the timeline.** The recording is an ordered list of execution points. List what ran, and confirm your interaction id is in the captured variables:

```bash
# the ordered execution points (PreFlow, RouteRule, target request/response, …)
jq -r '.point[].id' trace.json

# prove Trace captured the variable you sent — your interaction id
grep -o "$IID" trace.json && echo "Trace captured this request"
```

For the same request in the Apigee UI, open **Debug → start a session** on `hello-proxy` / `eval`, replay the `curl`, and click each step in the transaction map. The UI's variable pane is the "watch window"; the `trace.json` above is the same data, scriptable.

**5. Now make a policy *do* something, and watch it in the trace.** Add `apiproxy/policies/AM-Stamp.xml` that copies the interaction id into a variable of your own:

```xml
<AssignMessage name="AM-Stamp">
  <AssignVariable>
    <Name>trace.demo.iid</Name>
    <Ref>request.header.x-fapi-interaction-id</Ref>
  </AssignVariable>
</AssignMessage>
```

Attach it in the ProxyEndpoint request PreFlow, redeploy (this mints a new revision per 1.4), recapture `$REV`, and re-run steps 1–4. In the new `trace.json`, your variable now appears — and only *after* the `AM-Stamp` step:

```bash
jq -r '.. | objects | select(.name=="trace.demo.iid") | .value' trace.json | head -1
```

**What success looks like:** you can point at the ordered list of execution points and name what ran where; you can find your `x-fapi-interaction-id` in the captured variables; and after step 5 you can show that `trace.demo.iid` is *absent* before `AM-Stamp` and *present* after it — you watched a single policy mutate the message, exactly like watching a variable change one line at a time in your IDE.
</div>

## Verify it

You should be able to answer "what ran, in what order, and what did it change?" entirely from the recording:

- The order of `point[].id` in the trace *is* the execution order. A policy you expected but don't see in the list never executed — almost always a condition that evaluated false (you'll branch deliberately in 2.3).
- Pick any one step and you can read the variable set as it stood *at that step* — that before/after delta is how you attribute a change to a specific policy rather than guessing.

If you just want a quick scripted check that a session captured anything at all:

```bash
apigeecli apis debug list --name hello-proxy --rev "$REV" \
  --session "$SESSION" --env "$ENV" --org "$ORG" --token "$TOKEN" \
  | jq '.[] | length'
```

A non-zero count means your request landed inside the open window. Zero almost always means the window closed, or you traced the wrong revision.

!!! failure "Common failure modes"
    - **Empty trace — no transactions captured.** The session expired (it auto-closes after a short window / a fixed transaction count) before your request arrived, so the recording is empty. Symptom: `debug list` returns nothing. Open the session and send the request promptly, in that order.
    - **Tracing the wrong revision.** You started the session on the deployed revision but tested against a freshly-minted-but-undeployed one (or vice versa). Symptom: requests succeed yet never appear in the trace. Always derive `$REV` from `listdeploy`, as in the lab.
    - **Expecting a pause.** Treating Trace like a breakpoint and waiting for execution to "stop." It never stops — the request completes and you read the recording afterward. Symptom: "my curl returned but the debugger didn't break."
    - **Reading the response and ignoring the request side.** A value that looks wrong in the response was often already wrong inbound. Walk the timeline from the *first* point, not from the response. Symptom: blaming a response policy for a value an earlier request policy set.
    - **Leaving sensitive data unmasked.** A raw trace of a real OAuth/Open Banking call captures tokens and account data in plaintext. Don't share `trace.json` casually; masking is configured in 3.1. Symptom: secrets sitting in a file you were about to paste into a ticket.

!!! stretch "Stretch goal"
    Capture a full Trace session, export the transaction to a file (the `debug get … > trace.json` above), and annotate it the way you'd comment a stack trace: for each policy step, write one line saying *which flow variable it read, which it wrote, and why that step exists*. Pick a proxy with at least three policies so there's a real chain to narrate. The exercise that pays off later is finding the single step where a variable first becomes wrong — that's the gateway equivalent of locating the frame where your Spring object went null, and doing it on a trivial proxy now is what makes you fast on a FAPI proxy in Part 4.

## Recap & next

Trace is your gateway debugger: start a debug session on a deployed revision, fire a request into the recording window, then read the ordered timeline of every policy that executed with its flow variables snapshotted at each step. **Step** the timeline, **watch** a variable down it, **inspect** a single step — the same three moves you make in an IDE — and you can attribute any change to the exact policy that made it. You'll use this in nearly every session from here.

**Next — 2.1:** you've been reading a pipeline you haven't formally dissected. Part 2 opens with **the flow model & request/response symmetry** — the two endpoints and four attach points that those Trace steps were running at all along.
