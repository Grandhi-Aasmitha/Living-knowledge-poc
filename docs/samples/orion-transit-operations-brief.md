# Orion Transit Operations Knowledge Brief

These notes describe the current operating model for the fictional Orion City Transit network. They combine service runbooks, station procedures, and team registers. A service or team name in a heading is a navigation aid; the statements in each section describe the actual work. Two current registers disagree about the operating team for gate validation. The disagreement has not been settled. Several other responsibilities are deliberately absent from the available records so that a reader can distinguish a known fact from an unanswered question.

## Rider entry, identity, and profile

Orion Rider Portal Service is the first application most riders see when they plan a trip or inspect a ticket. Orion Digital Experience Team keeps the portal available and handles its production incidents. The portal sends a sign-in request to Orion Identity API before it shows a rider's saved trips. Orion Identity API returns an identity result; it does not calculate fares or decide whether a ticket is valid at a station gate. The portal can show public route information to a visitor, but a stored ticket is shown only after identity has been checked.

For a signed-in rider, Orion Rider Portal Service reads saved preferences from Orion Rider Profile Database. The database holds the preferred station and notification language, not the ticket purchase ledger. If a profile lookup is slow, the portal can still show a fresh route search, but it cannot prefill the rider's preferred station until the profile response arrives. Orion Digital Experience Team also maintains the profile database's application access rules. The team does not operate the external payment network mentioned later in this brief.

## Route catalog and journey suggestions

Orion Journey Planner Service prepares suggested journeys from the stop and route definitions in Orion Route Catalog Database. Orion Routing Team is responsible for the planner and for publishing the current route catalog. The planner also listens to Orion Stop Update Topic, where approved stop closures and platform changes appear. A closure update can remove a stop from a proposed journey even when the underlying route remains in the catalog. The planner's output is a journey suggestion; it is not a ticket, a fare quote, or a promise that a vehicle will arrive at a particular minute.

Orion Route Catalog Database is updated after routing staff approve a new timetable. The planner reads the last approved catalog during a catalog refresh rather than inventing a route from an incomplete update. Operations staff can compare a journey suggestion with the catalog revision recorded in the planner log. Orion Routing Team investigates a missing journey by checking both the catalog revision and recent events on Orion Stop Update Topic. Station staff cannot correct a route by changing a display board directly; the approved route or stop update must reach the planner first.

## Fare quotation

When a rider chooses a suggested journey, Orion Rider Portal Service asks Orion Fare API for a price. Orion Fare API applies the current zone table and concession rules from Orion Fare Rules Database. Orion Fare Policy Team maintains the fare rules and owns the API's production behavior. A route suggestion by itself carries no price, and Orion Journey Planner Service does not apply the fare table. A quote contains the fare amount and a short expiry time so that a later purchase can be checked against the price the rider saw.

The fare API may reject a quote request when a concession cannot be verified. In that case the portal displays the reason supplied by the API rather than silently charging a standard fare. A slow fare response can delay the purchase screen while public journey results remain available. Orion Fare Rules Database is the source for current zone prices; Orion Finance Ledger Database, described later, records settled money and does not replace the fare table. Orion Fare Policy Team reviews rule changes before they become active.

## Ticket purchase and issue

Orion Ticketing Service receives an accepted fare quote and asks Meridian Payments Gateway to authorize the rider's payment. Meridian Payments Gateway is an external system; the gateway returns an authorization result but does not create Orion tickets. Orion Ticketing Service creates the ticket only after the payment authorization succeeds. It writes the ticket identifier, permitted journey, and validity window to Orion Ticket Database, then publishes an issue event on Orion Ticket Issued Topic. Orion Ticketing Team operates the service and checks failed authorization attempts.

If authorization is declined, Orion Ticketing Service does not publish an issue event. A rider can retry a purchase without receiving a second ticket for the same successful authorization because the service checks the authorization reference before creating a new ticket. The portal reads the resulting ticket from Orion Ticket Database for the rider's account. Station gates use that database for a different purpose: they verify the ticket presented at entry. The issue topic is a handoff to downstream processing, not a replacement for the ticket record.

## Settlement and financial records

Meridian Payments Gateway later sends settlement notices to Orion Payment Settled Topic. Orion Payment Reconciliation Service consumes those notices and compares the settled amount with the authorization reference attached to an issued ticket. Orion Finance Team operates the reconciliation service. It writes a settled entry to Orion Finance Ledger Database when the reference and amount agree. The ledger is used for finance reporting; it is not consulted by a gate to decide whether a ticket can admit a rider.

A delayed settlement notice does not erase an already issued ticket. Finance staff investigate a notice that has no matching authorization before posting an entry. They can trace a ledger row back to the gateway settlement reference and the ticket issue event. Orion Payment Reconciliation Service leaves a mismatched amount for investigation rather than changing the fare quote retrospectively. The brief does not specify how long the external gateway retains its own records, so that retention period should not be inferred from Orion's ledger procedure.

## Station gate validation

Orion Gate Validation Service receives a ticket identifier from a station reader. It reads Orion Ticket Database to check the permitted journey and validity window, and it sends the admit or reject result back to the reader. Every completed check produces a validation event on Orion Validation Event Topic. An offline reader may queue a check locally for a short period, but the central service does not treat a missing database response as proof of a valid ticket. The gate result therefore depends on the ticket record, not on the finance ledger.

Station operations monitor rejection rates and reader connectivity through the gate service dashboard. A rejected ticket does not mean a payment was declined; the ticket might be expired, outside its permitted journey, or absent from the database. Orion Audit Trail Service later consumes the validation events for an audit record. Two current team registers assign operation of Orion Gate Validation Service to different teams; their statements appear near the end of this brief. This section describes the service's behavior without choosing between those ownership records.

## Vehicle positions and telemetry

Orion Vehicle Telemetry Service receives position reports from vehicles and publishes normalized updates to Orion Vehicle Position Topic. Orion Fleet Systems Team operates the telemetry service. It also writes the most recent accepted position to Orion Fleet Database so dispatchers can inspect a vehicle's last known location after a restart. A report with an invalid vehicle identifier is quarantined rather than published as a normal position update. The fleet database is a recovery and inspection store, while the topic is the live feed used by downstream services.

Position updates can arrive out of order when a vehicle reconnects after a tunnel. Orion Vehicle Telemetry Service uses the report timestamp to avoid replacing a newer position with an older one. Dispatchers can see the rejected report in the telemetry log, but a platform display does not receive that raw log. No rider-facing screen calls the telemetry service for each refresh. The arrival forecast path described below consumes the topic and produces a separate rider-facing estimate.

## Arrival estimates

Orion Arrival Forecast Service listens to Orion Vehicle Position Topic and Orion Stop Update Topic. It combines accepted vehicle positions with the approved stop sequence to estimate arrival times, then publishes the estimates to Orion Arrival Forecast Topic. Orion Mobility Analytics Team operates the forecast service and reviews its model behavior after major timetable changes. The service does not sell tickets or change a route catalog entry. Its output is an estimate that may change as fresh vehicle positions arrive.

If position reports stop, Orion Arrival Forecast Service marks an estimate stale rather than presenting the old time as a fresh prediction. The stale marker travels with the estimate on Orion Arrival Forecast Topic. A stop closure can also change which arrival is relevant to a rider even when the vehicle continues along the same corridor. Analysts compare the forecast's input timestamps with the displayed estimate when investigating an apparent jump in arrival time. The forecast service has no direct write path to a station display database.

## Platform displays

Orion Platform Display Service consumes Orion Arrival Forecast Topic and renders the current estimate on station boards. It reads layout and accessibility settings from Orion Display Configuration Database. Orion Station Presentation Team operates the display service and maintains the configuration database. When an estimate carries a stale marker, a board labels it as stale instead of showing it as a confident live arrival. The display service does not query Orion Vehicle Telemetry Service directly for raw vehicle coordinates.

A station board can continue showing its last received layout during a configuration outage, but it cannot invent a new arrival estimate when the forecast topic stops. Station staff report a blank board to Orion Station Presentation Team with the station identifier and the last displayed timestamp. A wrong journey suggestion is routed to Orion Routing Team, whereas a wrong forecast time is routed to Orion Mobility Analytics Team. These routes help staff diagnose a visible problem without treating every board symptom as a display software defect.

## Disruption intake and escalation

Orion Incident Intake Service records operator-approved disruption notices and publishes them to Orion Disruption Topic. Orion Network Operations Team operates the intake service. A notice includes the affected corridor, start time, and a rider-safe summary. The intake service can amend a notice after an operator confirms a changed impact, but it does not automatically close an incident simply because a vehicle resumes reporting positions. Orion Journey Planner Service may use approved stop changes, while rider notifications use the disruption notice itself.

The operations runbook also mentions Orion Escalation Topic as a place where urgent escalation messages can appear. It does not identify the service that publishes those messages. An analyst should not assign a producer based only on the topic name or on the fact that Orion Incident Intake Service handles ordinary disruptions. The runbook names a human duty officer who checks urgent messages, but it does not state that a software service consumes Orion Escalation Topic. Those two omissions are open questions for the network operations group.

## Rider notifications

Orion Rider Notification Service consumes Orion Disruption Topic and Orion Arrival Forecast Topic. It selects affected riders using saved station preferences from Orion Rider Profile Database and publishes a notification record to Orion Rider Alert Topic. A disruption notice can produce an alert even when there is no current arrival estimate. A stale forecast is labelled as such in the alert record. The notification service cannot create a new disruption; it passes along approved disruption information and relevant forecast context.

The current runbook explains this flow but does not name an operating team for Orion Rider Notification Service. Orion Digital Experience Team operates the portal and profile access rules, yet that fact alone does not establish ownership of the notification service. A team assignment should be recorded separately before anyone marks a notification ownership claim as confirmed. The runbook also does not promise that every rider has opted in to receive an alert; it describes creation of the alert record for eligible preferences.

## Accessibility information

Orion Accessibility Service asks Orion Elevator Status API for the current status of station lifts. Orion Accessibility Team operates the service. The API is maintained by a station facilities system outside the rider application group. After receiving a confirmed lift outage, Orion Accessibility Service publishes an accessibility notice to Orion Accessibility Notice Topic. The notice names the affected station and an effective time. It does not alter a ticket's validity or change a fare.

Orion Rider Portal Service can show an accessibility notice beside a journey suggestion. Orion Platform Display Service can also show a station-specific notice when its configuration permits the accessibility panel. If the lift API is unavailable, Orion Accessibility Service does not claim a lift is operating; it marks the last known status as unverified. Facilities staff resolve the physical fault, while Orion Accessibility Team handles the service's notice flow. These are related responsibilities, but the software service does not control the lift itself.

## Refund decisions

Orion Refund Case Service receives a rider's refund request and retrieves the ticket record from Orion Ticket Database. Orion Customer Care Team operates the case service. A case worker may approve a refund after checking the journey and disruption evidence. When approval is recorded, Orion Refund Case Service asks Meridian Refund API to initiate the transfer and writes the decision and transfer reference to Orion Refund Database. Meridian Refund API is an external interface; an accepted request is not itself proof that the rider's bank has completed the transfer.

The case service publishes a decision event to Orion Refund Decision Topic after recording the approved or denied decision. A denied case has no transfer request, but it still has a decision record for later inquiry. Support staff can inspect Orion Refund Database to explain the decision date and transfer reference. The document does not specify which downstream service, if any, consumes Orion Refund Decision Topic. Do not infer a consumer from the topic's existence or from the finance team's settlement work.

## Support desk and rider inquiries

Orion Support Desk Service consumes Orion Rider Alert Topic so agents can see the disruption information that a rider may have received. Orion Customer Care Team operates the desk service. The service reads Orion Refund Database when an agent investigates a refund decision, but it cannot approve a refund by changing the database directly. Approval belongs to the case workflow. Agents can also look up a ticket in Orion Ticket Database when a rider reports that a gate rejected it.

If a rider asks why an arrival time changed, the desk first checks whether the alert or platform display carried a stale forecast marker. The desk can then route a forecast investigation to Orion Mobility Analytics Team. If the complaint concerns a missing route, it routes the issue to Orion Routing Team. These routing steps are operational guidance, not evidence that the support desk generates forecasts or maintains route definitions. An agent should preserve the event timestamp when escalating so the responsible team can inspect the correct record.

## Audit trail and exports

Orion Audit Trail Service consumes Orion Validation Event Topic and stores a record of gate checks in Orion Audit Database. Orion Compliance Engineering Team operates the audit service. An audit record includes the event identifier, ticket reference, gate result, and time received. The audit service does not decide whether a gate should admit a rider; that decision was made by Orion Gate Validation Service. Audit staff use the stored event to investigate a later dispute about a rejected ticket.

Orion Audit Trail Service also publishes a daily export marker to Orion Audit Export Topic after a complete audit batch. This brief does not identify any software service that consumes Orion Audit Export Topic. A daily marker shows that an export batch was prepared; it does not prove that another system received or archived it. Compliance staff can compare the marker with the batch in Orion Audit Database. A missing marker is investigated by Orion Compliance Engineering Team before the batch is treated as complete.

## Recovery and operational boundaries

During a station network interruption, the last approved route catalog and the last received display layout remain available locally for a short period. Orion Journey Planner Service can continue using the approved catalog, but a disconnected board cannot claim a new live forecast. Orion Vehicle Telemetry Service may receive delayed position reports after connectivity returns and must reject an older report when a newer position is already stored. These recovery behaviors preserve the distinction between a last known value and a fresh operational result.

An issued ticket persists in Orion Ticket Database even if a settlement notice is late, because ticket authorization and financial settlement are separate stages. A refund decision persists in Orion Refund Database even if the external transfer takes longer to complete. An audit export marker is not a substitute for a confirmed downstream consumer. These boundaries matter when answering incident questions: a service's ability to continue in a degraded mode should not be described as evidence that every downstream dependency is healthy.

## Current station operations ownership record

The current station operations register assigns Orion Gate Validation Service to Orion Station Systems Team. According to that register, Orion Station Systems Team is responsible for gate reader integration, production incident response, and the validation service's station rollout schedule. The register treats the team as the operating owner of the software service, not merely as a recipient of validation events. Its entry is still marked current in the station operations archive.

The same register assigns Orion Platform Display Service to Orion Station Presentation Team, consistent with the display runbook. It does not assign Orion Rider Notification Service to either station team. A reader should not extend the gate assignment to the notification service just because both can affect a rider at a station. Station operations asks that a conflict about a service owner be reviewed against the other current team records before one assignment is treated as confirmed.

## Current fare operations ownership record

The current fare operations register instead assigns Orion Gate Validation Service to Orion Fare Operations Team. That register says Orion Fare Operations Team receives the on-call page for validation failures and is accountable for restoring the central gate check after a database outage. It describes the same Orion Gate Validation Service named by the station register, not a separate service with a similar name. The fare operations entry is also marked current and gives no rule for taking precedence over the station operations entry.

Fare operations maintains its own incident rota, while Orion Fare Policy Team maintains Orion Fare API and fare rules. Those are different responsibilities. Neither register explains why the gate validation assignment differs, and no authorized reviewer has resolved the discrepancy in these notes. A careful answer to an ownership question should report both current assignments and their conflict. It should not choose a winner from the order in which the records appear.
