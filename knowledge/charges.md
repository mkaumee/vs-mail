# Terminal handling and local charges

## What ocean freight covers

The ocean freight rate covers carriage from the load port to the discharge
port. It does not cover moving the container across the terminal at either
end, and it does not cover documentation.

Terminal handling charges are **billed separately from ocean freight** and
appear as their own lines on the invoice. A freight rate quoted as "all-in"
still excludes THC unless the quotation says otherwise in writing.

## The usual separate lines

| Charge | Where | What it is |
|---|---|---|
| Origin THC (OTHC) | Load port | Lifting the container on and moving it within the terminal |
| Destination THC (DTHC) | Discharge port | The same at the other end |
| Documentation fee | Origin | Issuing the bill of lading |
| Seal fee | Origin | The container seal |
| Telex release fee | Origin | Releasing cargo without surrendering an original BL |
| BL amendment fee | Origin | Correcting a bill of lading after issue |

## Who pays which end

Which party carries origin and destination THC follows the Incoterm on the
booking, not the freight rate. See `incoterms.md`.

Under **CFR** and **CIF** the seller pays ocean freight and origin THC; the
buyer pays destination THC. Under **FOB** the buyer pays freight and both
terminal charges from the ship's rail onward. This is the single most common
source of a THC query: a consignee billed destination THC on a CFR shipment is
being billed correctly, and usually does not expect it.

## Answering a breakdown request

A request for "the breakdown" wants the invoice's charge lines with amounts
and the currency, not an explanation of what THC is. Give the lines from the
record, then the Incoterm that decides who carries them.

If the charge lines are not available, say that rather than describing the
policy as though it answered the question.
