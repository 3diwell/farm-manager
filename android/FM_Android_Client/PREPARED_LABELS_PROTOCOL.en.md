[Русский](PREPARED_LABELS_PROTOCOL.md) · **English**

# Prepared labels — protocol 3 and prices in protocol 5

## Add-on 0.8: batch price before receiving

Current package: `dist/inventory-1.7.29-desktop-prices-0.8.0.zip`.
Routes and permissions are the same; `backend.py` matches the NFC 0.7 package byte for byte.
GET `/api/mod/inventory/filament` adds the flag `prepared_label_prices_v5` to `mobile.features`
and the currency of the inventory setting to `mobile.currency`
(`inv_settings.currency`, the previous default value is ILS).
The `mobile.protocol` field stays 1 for compatibility.

Only preparation **with a price** uses `mobile.protocol=5`,
`mobile.operation=prepare_labels` and the existing POST `/api/mod/inventory/spool`.
The other batch fields are the same. The new body field:

```json
{"pricing":{"mode":"total","amount":"12000.00"}}
```

`mode=total` is the sum for the whole batch; `mode=unit` is the price of a whole spool, not of a kilogram.
`amount` is a non-negative decimal string with at most two digits after the point/comma.
The client sends the canonical form with a point. A number instead of a string, extra pricing fields,
an exponent, negative/non-numeric values and a sum above 1 000 000 000 are rejected.
All distribution calculations are done in integer hundredths, without float rounding.
The quantity is the same: 1–500. Zero is allowed; a missing price is not the same as an explicitly entered zero.

Preparation without a price and Android preparation stay on protocol 3 without the `pricing` field.
On a new server, protocol 3 + pricing is rejected with `pricing_requires_protocol_5`.
On an older server, protocol 5 is rejected entirely: the price is not lost silently.
The PC also checks the feature before sending. If the request result is unknown, the exact body
with the price and the original request_id are saved; a retry does not create a new batch.

### Migration and distribution

A repeatable additive migration in a savepoint under `lock_inv` extends only the label registry:

- `inv_mobile_label_batches`: `price_mode`, `price_quantity`, `price_input_minor`,
  `price_total_minor`, `price_currency`.
- `inv_mobile_labels`: `price_minor` (the price of a whole spool in hundredths).

For old batches and labels the numeric fields are NULL; the historical `inv_spools.price` values do not change.
For a new batch the original quantity, mode, sum and currency are saved.
If the sum does not divide evenly by the quantity, the labels last by ordinal get one
extra hundredth each. 100/3 → 33.33, 33.33, 33.34. This is determined at preparation,
not at the time of scanning. Cancellation/partial receiving/restart redistribute nothing.

`claim_label` stays on protocol 3, so Android 0.10 is not updated.
The server takes the price only from the label and writes it to the standard `inv_spools.price`;
price fields inserted into a claim request are not used.
The status transition, price, spool, receipt and idempotency result are committed together.
A retry for an already received label is the earlier no-op; an individually changed price is kept.
With NULL, the earlier zero of the spool field is used. `inv_filaments.price_per_kg` does not change;
the earlier priority of the catalog price in existing calculations does not change either.

The price is stored on the server, not in the QR; the format `fm1:spool:<server_id>:<reserved_id>` is unchanged.
Printed objects/templates do not contain the price. On the PC the price is visible only in the form and the label registry.
The displayed batch sum is the original one, not the value of the remaining or already received labels.
The currency is recorded for reference in the batch; there is no automatic conversion when the shared
FM currency changes, just as in the earlier inventory. Do not change the currency between preparation and receiving.

Editing the price of an already prepared batch and carrying a price over into old batches are not added.
Do not roll the module back to 0.7 while there are pending labels with a price: the old claim handler
does not use the new fields and will receive the spool without this price. Additional columns by themselves
do not ensure that the old handler's behavior is preserved.

The description of the original protocol 3 of version 0.4 is kept below. In the current Android 0.8–0.10
the batch is determined automatically in the shared receiving flow. Print templates since Desktop Labels 0.5.2
do not show weight and diameter; mentions of the old interface below are historical.

## Original protocol 3, extension 0.4

## Compatibility and scope

No new HTTP routes were added: the protected standard POST
`/api/mod/inventory/spool` and its spool creation permission are used. Metadata is returned
through the existing GET `/filament`. Core code, routes, policy_id, print hooks,
the module interface and legacy handlers without mobile were not changed.
Old clients continue with protocols 1/2; new actions are allowed by the feature
`prepared_labels_v3`, and the server strictly checks protocol=3 and an allowed operation.
Protocol 3 cannot be sent through bind; protocols 1/2 cannot be used for the new operations.
Module 0.2 rejects the new requests rather than performing a regular receipt instead of them.

## Data

Two additive tables in the same SQLite under the standard lock_inv:

- inv_mobile_label_batches: id, name, filament_id, caption (snapshot), weight_total_g,
  shared label, created_at.
- inv_mobile_labels: a pre-allocated spool ID, batch_id, ordinal, status
  (prepared/received/cancelled), location_id at receiving, received_at, cancelled_at.

init uses CREATE TABLE IF NOT EXISTS; a repeated run does not change server_id,
spools or old batches. Prepared labels are NOT in inv_spools and do not take part
in remaining amounts/FIFO/write-off/linking. When a new material is prepared, only a catalog
record is created, not an inventory receipt. The whole journal of prepared batches lives in FM, not on the phone.

GET mobile metadata keeps protocol=1 and codes; it additionally returns prepared_batches
and prepared_labels. All batches and labels are returned; server-side pagination is not implemented yet.
Given the client's existing 16 MiB response limit, very large archives will require pagination.

## Operations

Shared mobile envelope: protocol=3, operation, server_id, request_id.

- prepare_labels: name, filament_id OR filament, weight_total_g, quantity 1..500, label.
  The batch/labels/material if needed and the inv_mobile_ops record are created fully atomically.
  Response operation=prepare_labels, batch_id, counts; the spool id is not in the response.
- claim_label: batch_id, location, mobile.code. The QR is strictly `fm1:spool:<server_id>:<reserved_id>`.
  The client does not send the actual weight/material: they are taken from the batch. Checked are
  batch membership, status, shelf, and whether the material is still current relative to the printed caption.
  For prepared, inv_spools with the same ID, a regular in entry in inv_ledger,
  the received transition, location/time and the inv_mobile_ops result are created atomically. For received — a successful no-op
  already_received, even if the spool was deleted/written off. For cancelled — a refusal.
- cancel_labels: batch_id, label_ids (an explicit list of unique IDs 1..500).
  Only prepared ones become cancelled; received ones do not change. An unknown ID cancels
  the whole transaction. cancelled_count and counts are returned.

Idempotency of all actions: BEGIN IMMEDIATE + lock_inv, a hash of the body/operation,
the result in inv_mobile_ops in the same transaction. With the same request_id, the saved
result is returned; a different body is rejected. A new request_id with an old received
label returns a no-op based on the label status. Two clients and a cancel/claim race are serialized.

## Android

The request and context are saved BEFORE sending, by the earlier pending journal. Creating/cancelling/receiving
prepared labels is separate from regular receiving: responses without a spool id do not go into ReceiptBook.
After the operator enables the mode for a specific batch and shelf, a scan immediately sends the claim;
the next scan is allowed after the FM response. The camera does not stay in continuous mode.
Passing QR codes between phones does not carry over sessions/passwords. Labels use the earlier format,
so after a claim they work for the earlier linking. Regular receiving by an arbitrary fm1
is still forbidden; a label is not an authorization and does not make an HTTP call by itself.

A repeated PDF uses the same IDs and excludes cancelled labels. A printed label does not contain
the "pending" status, so that it does not become wrong after receiving; the status is shown only in FM.
The weight in the caption is explicitly marked as the weight at receiving, not the current remaining amount.
