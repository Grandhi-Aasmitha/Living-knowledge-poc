# Orion Transit test questions and expected answers

Upload **only** `orion-transit-operations-brief.md` to the application, using namespace `orion-transit-lab`. Keep this answer key outside the upload. The answers below are what the document supports; they are a comparison guide, not claims that the AI will always extract every fact correctly. Uploaded claims should initially be **PROPOSED**. A genuine unresolved ownership conflict should appear as **CONFLICTING** after conflict detection. A question the document leaves unanswered should be treated as **INCOMPLETE**, without a guessed name.

## Direct fact questions

| # | Ask Knowledge Assistant | Expected answer from the document | Source section |
|---|---|---|---|
| 1 | Who operates Orion Rider Portal Service? | Orion Digital Experience Team. | Rider entry, identity, and profile |
| 2 | What does the portal call before showing saved trips? | Orion Identity API checks the rider's identity. | Rider entry, identity, and profile |
| 3 | Where are a rider's preferred station and language kept? | Orion Rider Profile Database. | Rider entry, identity, and profile |
| 4 | Which service prepares suggested journeys? | Orion Journey Planner Service. | Route catalog and journey suggestions |
| 5 | Which database supplies current route definitions? | Orion Route Catalog Database. | Route catalog and journey suggestions |
| 6 | Which API quotes a journey price, and who maintains it? | Orion Fare API; Orion Fare Policy Team. | Fare quotation |
| 7 | What happens after Orion Ticketing Service receives a successful payment authorization? | It creates a ticket in Orion Ticket Database and publishes an issue event on Orion Ticket Issued Topic. | Ticket purchase and issue |
| 8 | Which service posts settled payments to the finance ledger? | Orion Payment Reconciliation Service writes matching settlements to Orion Finance Ledger Database. | Settlement and financial records |
| 9 | Which database does the gate service consult to check a ticket? | Orion Ticket Database. | Station gate validation |
| 10 | What topic carries completed gate-check events? | Orion Validation Event Topic. | Station gate validation |
| 11 | Where is the most recent accepted vehicle position saved? | Orion Fleet Database. | Vehicle positions and telemetry |
| 12 | Which service shows arrival estimates on station boards? | Orion Platform Display Service. | Platform displays |
| 13 | Which API reports lift status to the accessibility service? | Orion Elevator Status API. | Accessibility information |
| 14 | Which service handles refund cases and where are decisions recorded? | Orion Refund Case Service; Orion Refund Database. | Refund decisions |
| 15 | Which team operates the audit service? | Orion Compliance Engineering Team. | Audit trail and exports |

## Questions that combine facts across sections

| # | Ask Knowledge Assistant | Expected answer from the document | Source sections |
|---|---|---|---|
| 16 | How does a vehicle position reach a station arrival board? | Orion Vehicle Telemetry Service publishes to Orion Vehicle Position Topic; Orion Arrival Forecast Service consumes that feed and publishes to Orion Arrival Forecast Topic; Orion Platform Display Service consumes the forecast topic and renders the board. | Vehicle positions and telemetry; Arrival estimates; Platform displays |
| 17 | A rider sees a route result but no preferred station. What may be slow? | The lookup from Orion Rider Profile Database can be slow while a fresh route search still works. | Rider entry, identity, and profile |
| 18 | Does a late payment settlement cancel an already issued ticket? | No. Ticket authorization and later financial settlement are separate stages; the issued ticket remains in Orion Ticket Database. | Settlement and financial records; Recovery and operational boundaries |
| 19 | If a forecast is stale, what should a station board show? | It should label the estimate as stale instead of presenting it as a fresh live arrival. | Arrival estimates; Platform displays |
| 20 | Which two topics provide inputs to the arrival forecast service? | Orion Vehicle Position Topic and Orion Stop Update Topic. | Arrival estimates |
| 21 | Which team should investigate a missing journey, and which team a wrong forecast time? | Orion Routing Team investigates a missing journey; Orion Mobility Analytics Team investigates a wrong forecast time. | Route catalog and journey suggestions; Platform displays |
| 22 | Can an accepted refund request prove the rider's bank has completed the transfer? | No. Meridian Refund API accepting the request is not proof of completed bank transfer. | Refund decisions |
| 23 | Which service creates an approved disruption notice, and which service turns it into a rider alert record? | Orion Incident Intake Service publishes the notice to Orion Disruption Topic; Orion Rider Notification Service consumes it and publishes to Orion Rider Alert Topic. | Disruption intake and escalation; Rider notifications |
| 24 | Does the journey planner set fares? | No. The planner suggests journeys; Orion Fare API applies fare rules from Orion Fare Rules Database. | Route catalog and journey suggestions; Fare quotation |

## Conflict and missing-knowledge questions

| # | Ask Knowledge Assistant | Expected answer from the document | Expected result |
|---|---|---|---|
| 25 | Who operates Orion Gate Validation Service? | Two current records disagree: Orion Station Systems Team and Orion Fare Operations Team. Neither is established as the winner. | **CONFLICTING** after conflict detection |
| 26 | Who owns Orion Rider Notification Service? | The runbook does not name an operating team. Do not infer Orion Digital Experience Team from its portal ownership. | **INCOMPLETE** |
| 27 | Which service publishes to Orion Escalation Topic? | The source does not identify a publisher. | **INCOMPLETE** |
| 28 | Which service consumes Orion Refund Decision Topic? | The source does not identify a consumer. | **INCOMPLETE** |
| 29 | Which service consumes Orion Audit Export Topic? | The source does not identify a consumer; a prepared export marker is not proof of delivery. | **INCOMPLETE** |

## Suggested test sequence

1. Upload `orion-transit-operations-brief.md` with namespace `orion-transit-lab`.
2. Check the upload summary and inspect several proposed claims and their exact evidence excerpts.
3. Ask direct questions 1–15, then cross-section questions 16–24.
4. Run conflict detection for `orion-transit-lab` if the application has not run it automatically, then ask question 25.
5. Ask questions 26–29. The assistant should acknowledge missing knowledge rather than create a relationship from a topic's name.
6. Use Knowledge Curator or the review screen to inspect questionable extracted claims. Confirm only a claim supported by its excerpt, and leave the two disputed gate-owner claims unresolved until an authorized source resolves them.

For every supported answer, check that the citation points to the correct section and that the answer still says **proposed/unconfirmed** until its claim is confirmed. A fluent answer without a relevant citation is a failed test.
