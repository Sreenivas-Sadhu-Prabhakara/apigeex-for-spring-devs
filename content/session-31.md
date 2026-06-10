# 6.3 — Observability, analytics & Advanced API Security

!!! bottomline "Bottom line"
    Every call through Apigee is already being measured — traffic, latency, error rates, and the dimensions you defined (apiproduct, developer, response code) flow into **Analytics** with no instrumentation from you. You shape that into **custom reports**, ship structured request logs to **Cloud Logging** with a `MessageLogging` policy, trace individual calls with **Cloud Trace**, and — at awareness level — let **Advanced API Security** score and flag abusive traffic. This is your Micrometer/Actuator stack, except it lives at the edge and was never something you had to wire up.

## Why this exists

In a Spring service you reach for observability deliberately: add Micrometer, expose `/actuator/metrics` and `/actuator/prometheus`, register a `Timer` around the bits you care about, push to Prometheus, build Grafana panels, and bolt on a logging appender plus an OpenTelemetry agent for traces. It works, but it is *your* code, *your* dependencies, and *your* dashboards — and it only sees the traffic that actually reached your JVM.

Apigee inverts that. The proxy is on the request path for **every** call, so it can measure traffic *before* it reaches any backend — including the calls it rejected at the edge (the 401s from a bad key, the 429s from a tripped quota). That data is collected automatically and aggregated into the **Analytics** subsystem: a managed, queryable store of per-request facts keyed by dimensions like API proxy, API product, developer, environment, and response status code. You don't add a counter; you ask a question.

The pieces split cleanly. **Analytics + custom reports** answer "what is my traffic doing, sliced how I want?" — the metrics/dashboard role. **MessageLogging → Cloud Logging** answers "show me the structured record of *this specific* call" — the log-aggregation role. **Cloud Trace** answers "where did the latency go inside this one request?" — the distributed-tracing role. And **Advanced API Security** is a separate, higher-tier product that consumes the same traffic to flag bots, abuse patterns, and misconfigured proxies — the thing you'd otherwise stand up a WAF or anomaly-detection pipeline for.

!!! bridge "Spring Boot bridge"
    You already own all three observability pillars in Spring; Apigee gives you the edge-side equivalent, pre-wired.

    | Spring / observability stack | Apigee X equivalent | Notes |
    |---|---|---|
    | Micrometer `Counter` / `Timer` + Prometheus scrape | **Analytics** (automatic per-request facts) | No code; every call is already counted and timed |
    | A Grafana dashboard / PromQL query | A **custom report** (dimensions + metrics) | You pick dimensions like `apiproduct`, metrics like error rate |
    | Logback/Log4j2 JSON appender → log aggregator | **MessageLogging** policy → **Cloud Logging** | Emit structured fields (correlation id, status, product) |
    | OpenTelemetry agent + Tempo/Jaeger | **Cloud Trace** (distributed tracing) | Spans for proxy + target legs, latency breakdown |
    | A WAF / anomaly detection you ran beside the app | **Advanced API Security** | Abuse/bot detection, security scoring (awareness) |

!!! breaks "Where the analogy breaks"
    Micrometer measures what your code chose to time, inside the process, after the request got in. Apigee Analytics measures the *edge* — it sees and counts the traffic you rejected, so a spike of 401s or 429s shows up in your reports even though no backend handler ever ran. The dimensions are also fixed-but-rich: you don't invent arbitrary tags at will the way you sprinkle Micrometer tags; you slice by the platform's first-class dimensions (proxy, product, developer, response code, environment) plus a small set of custom ones you collect with a StatisticsCollector policy. And there's a propagation delay — Analytics is a near-real-time aggregate, not the synchronous in-process gauge a `/actuator/metrics` scrape gives you. For "what happened in the last few seconds on this exact call," reach for Trace or Cloud Logging, not a report.

## The concept

Three lanes, one traffic stream. Apigee tees every request into Analytics (aggregate facts), optionally into Cloud Logging (structured per-call records via MessageLogging), and optionally into Cloud Trace (latency spans). Advanced API Security reads the same stream to score it. A custom report is just a saved query over the Analytics store: pick **dimensions** (the GROUP BY) and **metrics** (the aggregate), pick a time range, render.

Below is the analytics view you'd otherwise build in Grafana — request volume against the error rate it implies, the single most useful FAPI operations panel:

```widget
{
  "type": "chart",
  "title": "AISP traffic — volume vs error rate (7 days)",
  "chartType": "line",
  "height": 320,
  "data": {
    "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "datasets": [
      {
        "label": "Requests (thousands)",
        "data": [42, 47, 51, 49, 58, 31, 28],
        "borderColor": "#2563eb",
        "backgroundColor": "rgba(37,99,235,0.12)",
        "yAxisID": "y",
        "tension": 0.3,
        "fill": true
      },
      {
        "label": "Error rate %",
        "data": [1.2, 1.1, 4.8, 1.4, 1.3, 0.9, 1.0],
        "borderColor": "#dc2626",
        "backgroundColor": "rgba(220,38,38,0.0)",
        "yAxisID": "y1",
        "tension": 0.3
      }
    ]
  },
  "options": {
    "scales": {
      "y": {"position": "left", "title": {"display": true, "text": "requests (k)"}},
      "y1": {"position": "right", "grid": {"drawOnChartArea": false}, "title": {"display": true, "text": "error %"}}
    }
  }
}
```

Read it like an on-call dashboard: the Wednesday error-rate spike to ~5% with volume *unchanged* is the signature of a backend or policy problem, not a traffic surge — exactly the pattern a custom report sliced by `apiproduct` and `response.status.code` lets you attribute to one product in seconds.

## Hands-on lab

<div class="lab" markdown="1">
#### Lab — structured Cloud Logging + an error-rate-by-product report

**Prereqs:** `$ORG`, `$ENV`, `$TOKEN`, `$RUNTIME_HOST` exported, a deployed `aisp-accounts` proxy (from 3.2), and a correlation id already on the message — reuse `x-fapi-interaction-id` (FAPI requires it) or a variable you set earlier. The MessageLogging-to-Cloud-Logging integration needs the Apigee runtime service account to have the **Logs Writer** role; grant it once if logs don't appear (see failure modes).

**1. A MessageLogging policy** that writes a single structured (JSON) entry per call to Cloud Logging. Note `CloudLogging` (not the old syslog `<Syslog>` block) — this is the GCP-native path. Put it in `apiproxy/policies/`:

```xml
<!-- ML-CloudLog.xml : structured log to Cloud Logging -->
<MessageLogging name="ML-CloudLog">
  <CloudLogging>
    <LogName>projects/{organization.name}/logs/aisp-accounts</LogName>
    <Message contentType="application/json">{
      "correlationId": "{request.header.x-fapi-interaction-id}",
      "apiproduct":    "{verifyapikey.VK-Key.apiproduct.name}",
      "developer":     "{verifyapikey.VK-Key.developer.email}",
      "status":        "{response.status.code}",
      "proxy":         "{apiproxy.name}",
      "verb":          "{request.verb}",
      "path":          "{proxy.pathsuffix}",
      "latencyMs":     "{client.received.end.timestamp}"
    }</Message>
    <ResourceType>api</ResourceType>
  </CloudLogging>
</MessageLogging>
```

**2. Attach it where it always runs and the status is known** — the ProxyEndpoint **response** PostFlow (point ④ from 2.1), so you log the final status of every call, success or rejection:

```xml
<PostFlow name="PostFlow">
  <Response>
    <Step><Name>ML-CloudLog</Name></Step>
  </Response>
</PostFlow>
```

**3. (Optional) Collect a custom analytics dimension.** A `StatisticsCollector` promotes a flow variable into an Analytics dimension you can group by — here, the consent status, so reports can slice FAPI traffic by it:

```xml
<!-- SC-Consent.xml -->
<StatisticsCollector name="SC-Consent">
  <Statistics>
    <Statistic name="consent_status" ref="flow.consent.status" type="STRING"/>
  </Statistics>
</StatisticsCollector>
```

**4. Redeploy and generate traffic** — drive a mix of 200s and a few 401s so the report has errors to show:

```bash
apigeecli apis create bundle --name aisp-accounts --proxy-folder ./aisp-accounts/apiproxy --org "$ORG" --token "$TOKEN"
apigeecli apis deploy --name aisp-accounts --org "$ORG" --env "$ENV" --ovr --wait --token "$TOKEN"

KEY="<your consumerKey from 3.2>"
for i in $(seq 1 20); do
  curl -s -o /dev/null -H "x-api-key: $KEY" -H "x-fapi-interaction-id: $(uuidgen)" \
    "https://$RUNTIME_HOST/aisp-accounts/accounts"
done
# a few deliberate failures (no key → 401)
for i in $(seq 1 5); do
  curl -s -o /dev/null -H "x-fapi-interaction-id: $(uuidgen)" \
    "https://$RUNTIME_HOST/aisp-accounts/accounts"
done
```

**5. Confirm the structured logs landed** in Cloud Logging via gcloud:

```bash
gcloud logging read \
  'logName="projects/'"$ORG"'/logs/aisp-accounts"' \
  --project "$ORG" --limit 5 --format json | jq '.[].jsonPayload'
```

**6. Define a custom report — error rate by API product.** Create it through the management API: the dimension is `apiproduct`, and the metric is the error-message count, which the report renders as a rate against total traffic:

```bash
cat > report.json <<'JSON'
{
  "displayName": "FAPI error rate by product",
  "metrics": [
    {"name": "message_count", "function": "sum"},
    {"name": "is_error", "function": "sum"}
  ],
  "dimensions": ["apiproduct", "response_status_code"],
  "chartType": "column",
  "timeUnit": "day"
}
JSON

curl -s -X POST \
  "https://apigee.googleapis.com/v1/organizations/$ORG/reports" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @report.json | jq '.name, .displayName'
```

Then open **Analyze → Custom reports** in the Apigee UI, run it over the last 24 hours, and read the error rate per product.

**What success looks like:** `gcloud logging read` returns entries whose `jsonPayload` carries *your* fields — `correlationId`, `apiproduct`, `developer`, `status` — for both the 200s and the 401s; and the custom report renders, showing a measurably higher error rate for the runs without a key, attributed to the right product.
</div>

## Verify it

In Cloud Logging, filter on `jsonPayload.status="401"` and confirm only the no-key runs appear — proof you logged edge rejections the backend never saw, which is the whole edge-observability advantage over an in-process Micrometer counter. Each entry should carry a distinct `correlationId` matching the `x-fapi-interaction-id` you can also find in the proxy's Trace, so you can pivot from a log line straight to the full request in **Cloud Trace** and read the latency split between the proxy and target legs.

For the report, change its dimension from `apiproduct` to `developer` and re-run: the same error count now attributes to the *consumer* rather than the product — the slice-and-dice you'd write a new PromQL query for, done as a saved-query edit.

!!! failure "Common failure modes"
    - **No logs appear in Cloud Logging.** The Apigee runtime service account lacks the `roles/logging.logWriter` role, or the `LogName` project segment is wrong. Symptom: proxy returns 200 but `gcloud logging read` is empty. Grant Logs Writer to the runtime SA and use `projects/{organization.name}/logs/<name>`.
    - **Logging the wrong status.** Attach MessageLogging in a *request* flow and `response.status.code` is unset, so every entry logs a blank or default status. It must run on the **response** side (point ③ or ④).
    - **Expecting the report instantly.** Analytics aggregates with a short propagation delay; a report run seconds after the traffic can show nothing. Wait a few minutes, or use Trace/Cloud Logging for real-time questions.
    - **Inventing dimensions.** You can only group by platform dimensions plus the custom ones a `StatisticsCollector` actually collected. Referencing a dimension you never collected returns an empty or erroring report.
    - **Confusing the three lanes.** Analytics is aggregate, Cloud Logging is per-call records, Trace is one-request latency. Reaching for a custom report to debug a single failing call is the wrong tool — that's a Trace or a log query.

!!! stretch "Stretch goal"
    Build the custom report the curriculum names: **FAPI error rates broken down by API product**, then extend it. Add `response_status_code` as a second dimension so you can see *which* FAPI error dominates per product (the 401s from key/token failures versus the 429s from quota), set the time unit to hour, and decide what error-rate threshold per product would page your on-call. Then map it back to Spring: which Micrometer metric and Grafana alert rule would you have hand-built to get the same signal, and what does the edge see that your in-process metric structurally cannot?

## Recap & next

You can now treat Apigee as a pre-wired observability stack: **Analytics** counts and times every call automatically (your Micrometer, at the edge), **custom reports** are saved queries that slice traffic by dimensions like `apiproduct` and response code (your Grafana panels), a **MessageLogging** policy ships structured JSON to **Cloud Logging** keyed by your correlation id (your JSON appender), **Cloud Trace** breaks down per-request latency (your OpenTelemetry spans), and **Advanced API Security** scores the same traffic for abuse and bots — awareness for now, a higher tier when you need it.

**Next — 6.4:** the layer with no Spring analogue at all. You'll **productise** the AISP API — bundle its operations into a sellable, governed **API product**, publish an OpenAPI spec to a **developer portal** where a TPP can self-serve a key, survey **monetization** rate plans, and catalogue everything in **API hub**.
