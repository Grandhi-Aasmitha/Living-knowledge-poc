# Folder upload test

Upload the entire `aster-field-ops-test` folder in **Learn from a document**. The folder name should fill the namespace as `aster-field-ops-test`. Keep that namespace selected when asking questions or looking at the graph. The four text files are a connected fictional dataset; no real organization is described.

Expected answers from the source documents:

| Question | Expected answer | Source files |
| --- | --- | --- |
| Who owns Aster Routing Service? | Aster Logistics Team. | 03 |
| Which service consumes Shipment Intent Topic? | Aster Routing Service. | 01 |
| Where does Aster Routing Service store route plans? | Route Plan Database. | 01 |
| Which team owns the service that publishes Shipment Status Topic? | Aster Experience Team owns Aster Tracking Service, which publishes the topic. | 02 + 03 |
| How does Aster Customer Portal get shipment updates? | It consumes Shipment Status Topic, published by Aster Tracking Service. | 02 |
| Which service records accepted returns, and where? | Aster Returns Service writes them to Returns Ledger Database. | 04 |
| Who owns Route Plan Database? | Unknown from these documents. | 03 |

Uploaded file claims start as **PROPOSED**. An answer can cite them while saying they are unconfirmed. Use **Review uploaded claims** to inspect and confirm supported claims if you want the app to treat them as confirmed. Do not confirm claims the source does not support.

## Initial trial result on 2026-10-25

All four files uploaded successfully into `aster-field-ops-test`. The app reported 24 proposed claims, and the graph showed 13 entities and 15 relationship edges. There were no open entity identity questions. The seven questions above produced six expected outcomes: five supported answers and the correct "unknown" response for Route Plan Database ownership.

The two-step question about the team owning the publisher of Shipment Status Topic did **not** succeed. The graph contains both `Aster Tracking Service PUBLISHES_TO Shipment Status Topic` and `Aster Experience Team OWNS Aster Tracking Service`, and direct questions about each fact work. The Assistant did not retrieve both claims together for the composed question, so it returned insufficient knowledge. This is a retrieval limitation, not an upload or extraction failure.

## After the retrieval fix

The Assistant now answers the two-step question with **Aster Experience Team** and cites both the publishing and ownership claims. It still reports the owner of Route Plan Database as unknown, even though it can see which services read and write that database. The claims remain proposed until reviewed.
