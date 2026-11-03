# Data model

This page describes the Django models declared by the application. Django's built-in authentication, session, permission, and migration tables also exist but are not duplicated here. Field definitions and migration history remain authoritative in each app's `models.py` and `migrations/`.

## Relationship diagram

```mermaid
erDiagram
    CUSTOMER ||--o{ DELIVERY : receives
    PRODUCT ||--o{ DELIVERY : sold_as
    CUSTOMER ||--o{ PAYMENT : pays
    DELIVERY o|--o{ PAYMENT : linked_receipts_or_refunds
    CUSTOMER ||--o{ CYLINDER_LEDGER : owns_movements
    PRODUCT o|--o{ CYLINDER_LEDGER : movement_product
    DELIVERY o|--o{ CYLINDER_LEDGER : source_delivery

    SUPPLIER ||--o{ PURCHASE : supplies
    PRODUCT o|--o{ PURCHASE : purchased_product

    FACTORY ||--o{ FACTORY_FILL_TRANSACTION : receives_fill_work
    PRODUCT ||--o{ FACTORY_FILL_TRANSACTION : filled_product

    CUSTOMER ||--o| FBR_CUSTOMER_SETTING : has_tax_settings
    PRODUCT ||--o{ FBR_PRODUCT_MAPPING : mapped_as
    CUSTOMER ||--o{ FBR_INVOICE : has_invoice_record
    FBR_INVOICE ||--o{ FBR_INVOICE_ITEM : contains
    DELIVERY o|--o{ FBR_INVOICE_ITEM : source_delivery

    CUSTOMER o|--o{ NOTIFICATION : subject
    PRODUCT o|--o{ NOTIFICATION : stock_subject

    AUTH_USER o|--o{ DELIVERY : created_by
    AUTH_USER o|--o{ PAYMENT : created_by
    AUTH_USER o|--o{ PURCHASE : created_by
    AUTH_USER o|--o{ EXPENSE : created_by
    AUTH_USER o|--o{ OPENING_BALANCE : created_by
    AUTH_USER o|--o{ PARTNER_ACCOUNT_BALANCE : created_by

    DAILY_EARNING_SUMMARY {
        date unique
        decimal total_income
        decimal total_purchases
        decimal total_expenses
        decimal net_cash
    }
    STOCK_OPENING_BALANCE {
        string category unique
        decimal quantity
    }
    NOTIFICATION_SETTINGS {
        integer singleton_pk
        integer threshold_hours
        decimal payment_threshold
    }
    DELIVERY_INVOICE_SEQUENCE {
        integer singleton_pk
        integer next_number
    }
```

`o|` indicates an optional foreign key. Relationships shown without an optional marker are required by the model. The diagram omits reverse names and routine timestamps for readability.

## Business entities

### Customers — `apps/customers`

`Customer` uses a UUID primary key and a generated, unique customer code. Its identity/contact information includes name, mobile numbers, address, area, notes, registration date, STN, and NTN. Financial/cylinder opening information includes:

- `previous_balance` and `bf_balance` decimal amounts.
- `advance_balance` decimal amount.
- `bf_cylinders`, a JSON object of product-name-to-quantity entries.
- B.F. description/date, security deposit, and customer-owned personal cylinder count.
- `last_activity_date` and `is_walkin`.

The model provides helpers for active/inactive/not-coming status, total deliveries, totals paid/billed, outstanding balance, and cylinder balances overall or before a date. The ordinary customer display status helper uses age thresholds in the model; the dashboard separately uses configurable notification thresholds.

`Customer.get_or_create_walkin()` reuses an existing walk-in identity matching its supplied name/mobile rules. A separate `create_walkin_customer` command creates a default walk-in record if one does not already exist.

### Products, stock, and factory fills — `apps/products`

`Product` uses a UUID primary key and unique uppercase-normalized name and product code. Its attributes distinguish sellable/purchasable products, quantity-only sales, and filling-only products. It stores sale/purchase prices, full and empty stock quantities, opening full/empty quantities, minimum stock, unit weight, and total stock weight.

Related records:

- `StockOpeningBalance`: one editable decimal opening quantity per report category.
- `Factory`: a named factory with optional contact details.
- `FactoryFillTransaction`: date, factory, product, empty cylinders sent, full cylinders received, invoice number, notes, and optional creator.

Factory and product references on a fill transaction use `PROTECT`, preventing deletion while fill history references the record.

### Deliveries and invoice numbering — `apps/deliveries`

`Delivery` is the sale/source transaction. It has required customer and product references, date, decimal quantity, unit price, calculated delivery amount, full/empty return counts, invoice fields, optional payment amount/type, charges, and creator/timestamps.

Additional delivery fields preserve guarantee/deposit information, damage charges and description, low-pressure pricing detail JSON, full-cylinder return value/payment status, descriptive notes, and cylinder ownership movement type. `has_returns` is derived from the empty-return count when the model saves.

`DeliveryInvoiceSequence` stores a single next-number counter used by FBR-oriented numbering. A pre-save signal is registered by the FBR app; it assigns or reuses FBR invoice numbers for eligible customer/date/product-category groups. See [invoice-number workflow](features-and-workflows.md#fbr-oriented-reports-and-invoice-numbers).

The model calculates `delivery_amount` when saved:

```text
product charge (with low-pressure line adjustments, when present)
+ delivery charges
+ damage charges
- value credited for full cylinders returned
```

This is the delivery's billed amount. A cash refund for a full-cylinder return can also be represented as a negative linked `Payment`; it is not the same thing as the delivery amount calculation.

### Payments — `apps/payments`

`Payment` has a generated unique daily payment number, customer, date, decimal amount, payment type, optional invoice number/notes, and optional link to a `Delivery`. Delivery-linked records are used to synchronize delivery receipts and cash refunds; standalone customer receipts are also supported. `matched_amount` and `advance_amount` are stored separately.

Payments belong to a customer (`CASCADE`) and an optional delivery (`CASCADE`). They are ordered newest first.

### Cylinder movements — `apps/cylinders`

`CylinderLedger` records customer/product/date, full cylinders out, empty cylinders in, guarantee deposit, notes, optional source delivery, and optional cylinder-ownership movement. The net helper is `full_out - empty_in`. Ownership movement entries separately distinguish customer-owned cylinders received/returned; the customer cylinder-balance helper incorporates those entries.

The customer and ledger use `CASCADE`; a deleted product or delivery can leave the optional reference empty (`SET_NULL`).

### Suppliers and purchases — `apps/suppliers`

`Supplier` has a UUID key, supplier code, identity/contact information, B.F. payable balance, tax identifiers, notes, and optional creator.

`Purchase` records a supplier, optional product, date, quantity, unit price, calculated subtotal/tax/total, amount paid, payment type, invoice, and descriptive fields. A null product permits supplier-only payment entries. It also stores sales-tax controls, delivery/extra charges, gas-specific quantities and cylinder measures, and a generated purchase number/group identifier.

The model's `save()` calculates product purchase amounts using product-name rules:

- Oxygen/nitrogen quantities are converted to cubic meters using fixed conversion factors in the model.
- CO2 and standard products use quantity times unit price.
- Argon/mixture-family purchases can use cylinder count and total cubic meters.
- LPG has cylinder-weight and per-kilogram handling.
- `with_tax` applies the configured purchase sales-tax rate; delivery and extra charges are added to the total.

Purchase-entry views—not just the model—also adjust product stock. Review both `Purchase.save()` and the supplier purchase views when changing these rules.

### FBR records and settings — `apps/fbr`

- `FBRCustomerSetting`: one-to-one customer setting for STN, NTN, a starting invoice number, and per-row invoice-number overrides.
- `FBRProductMapping`: product-to-display-name/unit/tax-rate mapping.
- `FBRInvoice` and `FBRInvoiceItem`: invoice/item record models with customer, date, totals, item arithmetic, and optional source delivery.

The current report views primarily calculate and render their rows from `Delivery` records and save customer settings/number assignments. The presence of invoice and mapping models does not mean the report handler submits an invoice externally or persists every displayed report row as an `FBRInvoice`.

### Notifications — `apps/notifications`

`Notification` stores type, title, message, unread/read state, optional customer/product, optional link, and timestamps.

`NotificationSettings` is a singleton-style row with pending-payment, cylinder-due, inactivity, not-coming, backup reminder, and weekly-reminder thresholds/toggles. Its `save()` forces the primary key to `1`; `get_solo()` creates that settings row if it does not exist.

### Earnings — `apps/earnings`

- `Expense`: dated operating expense, amount, description, and optional creator.
- `OpeningBalance`: dated starting cash amount and optional creator.
- `PartnerAccountBalance`: dated partner/bank account snapshot, amount, and description.
- `DailyEarningSummary`: one summary per date with income, purchases, expenses, and net cash.

The daily API calculates totals from source delivery/purchase/payment fields and expense records. Partner account snapshots are returned as separate data; they are not added into the net-cash calculation shown by the earnings view.

## Relationships and deletion behavior

| Parent and child | Cardinality / deletion behavior |
|---|---|
| Customer → Delivery | One customer has many deliveries; deleting the customer cascades to deliveries. |
| Product → Delivery | One product has many deliveries; deleting the product cascades to deliveries. |
| Customer → Payment | One customer has many payments; deleting the customer cascades to payments. |
| Delivery → Payment | A payment can have no delivery or one delivery; deleting that delivery cascades to linked payments. |
| Delivery → CylinderLedger | A ledger entry can be linked to a delivery; deleting a delivery clears that reference. |
| Customer/Product → CylinderLedger | Customer deletion cascades; product deletion clears the optional product reference. |
| Supplier → Purchase | Supplier deletion cascades to its purchases. |
| Product → Purchase | Purchase product is optional; product deletion cascades to purchases that reference it. |
| Factory/Product → FactoryFillTransaction | Both references are protected from deletion while transactions exist. |
| Customer → FBRCustomerSetting | One-to-one; customer deletion cascades. |
| Product → FBRProductMapping | Product deletion cascades to mappings. |
| FBRInvoice → FBRInvoiceItem | Deleting an invoice cascades to its items; source delivery is optional and set null on delivery deletion. |
| Notification → Customer/Product | Optional associations; deleting the related record clears the reference. |

These are model-level rules. Deleting a business record can have cross-app effects; inspect the owning view and model signals before deleting live records or changing `on_delete`.

## Numeric and time conventions

- Monetary and many quantity values use `DecimalField`; JSON/API serialization may convert values to strings or floats depending on the handler.
- Customer, product, delivery, supplier, purchase, and payment identifiers commonly use UUID primary keys. Earnings IDs are ordinary integer keys.
- Application dates use Django timezone utilities and the configured `Asia/Karachi` timezone.
- Some calculations convert values to Python `float`; do not assume every calculation is decimal-only solely because model fields are `DecimalField`.
