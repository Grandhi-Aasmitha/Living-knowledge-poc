# Cedar Retail Platform Knowledge Brief

These operational notes combine service runbooks and team registers from Cedar Retail. The final two records disagree about the operating team for one service; the teams have not yet settled that assignment.

## Checkout and pricing

Cedar Commerce Team is accountable for keeping Cedar Checkout Service available during customer purchases. Engineers usually shorten the service name to Checkout in meeting notes. The service accepts a customer's basket, asks Cedar Pricing API for a current total, and then presents the calculated amount before the customer commits. Pricing is a separate interface maintained by Cedar Finance Team, so a slow pricing response can delay checkout without stopping the rest of the storefront.

A basket stays in Cedar Cart Database until the purchase is accepted. Checkout needs that database to recover a basket when a customer returns to the page, and the purchase cannot be completed while the database is unavailable. Once the purchase succeeds, Checkout places an order event on Cedar Order Topic. The event contains the order identifier and the amount that was accepted; it is the handoff used by later processing rather than a direct call to the warehouse.

## Fulfillment and shipment records

Cedar Logistics Team runs Cedar Fulfillment Service. The service listens for new order events on Cedar Order Topic and turns each eligible order into a shipment request. It saves the allocated shipment details in Cedar Shipment Database so the warehouse can resume work after a restart. The fulfillment process does not query the customer's basket directly; its starting point is the order event supplied by Checkout.

For stock availability, Fulfillment reaches Cedar Inventory API. That interface is maintained with the warehouse systems and reports whether the requested items can be reserved. A shipment is held when Inventory says that stock is not available. The shipment record remains in Cedar Shipment Database, allowing the team to inspect what happened without reconstructing the customer's checkout session.

## Receipts and reporting

Cedar Messaging Service watches Cedar Order Topic for completed purchases. It turns those events into receipt notices on Cedar Receipt Topic. Cedar Customer Portal Service listens to the receipt feed and shows the resulting notice to the customer. Cedar Support Team operates the Customer Portal, while Cedar Messaging Service currently has no operating group recorded in this note.

Cedar Analytics Service also follows Cedar Order Topic. It stores a daily aggregate in Cedar Reporting Database for analysts who need purchase trends. The aggregate is derived from order events; it is not the source used by Fulfillment to ship an individual order. Cedar Data Team is responsible for the Analytics service and its reporting schedule.

## Risk signals and returns

Cedar Risk Service reads alerts from Cedar Fraud Topic before a flagged purchase is released for manual inspection. This note identifies the service that reads the alert stream but does not identify the system that puts alerts on Cedar Fraud Topic. Risk staff can inspect the alert and the related order identifier, yet no owning team for Cedar Risk Service is recorded here.

When a return is approved, Cedar Returns Service puts a return notice onto Cedar Return Topic. The notice gives the order identifier and the amount to be refunded. These notes do not name a consumer for Cedar Return Topic. The service records the accepted return in Cedar Returns Database so a later refund inquiry can find the decision and its date.

## Support ownership record

The current support roster places Cedar Returns Service under Cedar Support Team. Support's roster says that team is responsible for incidents affecting the return workflow and for the first response when return notices stop appearing. This is the ownership shown in the support record, not a description of which team built the software.

## Logistics ownership record

The current logistics register instead assigns Cedar Returns Service to Cedar Logistics Team. Logistics uses that assignment when routing on-call pages for the same Returns service. The two current records therefore identify different operating teams for one service; the register does not explain which assignment should take precedence.
