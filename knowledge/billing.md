# Goods receipt, PGI and billing

## The sequence

Billing a shipment depends on two postings happening first, in order:

1. **PGI — post goods issue.** The stock leaves inventory. This is what
   records that the goods physically went.
2. **GR — goods receipt.** The receiving side confirms what arrived, against
   the purchase order.

The invoice cannot be raised until both exist. An invoice sitting unbilled
almost always means one of them is missing, and it is nearly always the GR.

## "The GR is still missing"

The most common chaser in this inbox, and it is a request for an action rather
than a question. The sender wants the goods receipt posted so billing can
proceed.

Three reasons a GR does not get posted:

- **The receiving party has not confirmed** what arrived. Nothing can be done
  from our side until they do.
- **A quantity mismatch** between the PO and what was delivered. The GR cannot
  be posted against a PO it does not reconcile to; the PO has to be amended or
  the difference explained.
- **The PO was closed** before the delivery landed, so there is nothing open
  to receive against. It must be reopened.

A useful reply states which of these applies, and who has to act. "We will
look into it" moves nothing.

## Cancelling an invoice and reversing the PGI

Requested when a booking is amended after billing has already run — a changed
vessel, a changed quantity, a split shipment.

The order matters and cannot be shortcut:

1. Cancel the invoice. It cannot be edited, only cancelled and reissued.
2. Reverse the PGI, which puts the stock back.
3. Amend the booking.
4. Re-run PGI and re-raise the invoice against the corrected booking.

A PGI cannot be reversed while an invoice still refers to it, which is why a
cancellation request always names both. If the accounting period has closed
since the invoice was raised, the reversal posts into the current period
instead, and finance should be told.

## What blocks a cancellation

- The invoice has already been **paid** — it becomes a credit note, not a
  cancellation.
- The invoice has been **exported to the customer's system** and acknowledged.
- The period is **locked** and finance has not opened it.
