# Routes and internal JSON endpoints

## Scope

The application is a Django HTML application with JavaScript-assisted forms. Its JSON routes are internal page helpers, not a versioned public REST API: there is no public API schema, token-authentication contract, API version prefix, or DRF router in the inspected project. Request/response details that are not listed here should be taken from the owning view and the corresponding template JavaScript.

Root URL prefixes are configured in [`config/urls.py`](../config/urls.py). Route names are declared in each app's `urls.py`.

## Authentication and CSRF

- Login/signup/logout use Django's authentication views and custom wrappers. Most business pages and mutation handlers use `LoginRequiredMixin` or `login_required`.
- Authentication is not uniform across every lookup. In the current URL table, delivery balance/stock-validation lookups and the product stock lookup are implemented as plain function views without a login decorator. Confirm whether those routes should be public before internet exposure.
- Several internal delivery and supplier JSON mutation views are explicitly `csrf_exempt`; other POST handlers rely on Django CSRF protection. `csrf_exempt` does not mean a route is unauthenticated, and a login requirement does not replace CSRF protections.
- Django admin is at `/admin/` and uses Django's normal staff/superuser permission checks.
- Do not treat these routes as a supported third-party API without first defining authentication, authorization, CSRF, validation, compatibility, and rate-limiting requirements.

## Main browser routes

All paths below are relative to the application origin.

| Area | Route | Behavior |
|---|---|---|
| Root | `/` | Redirects to the dashboard route. |
| Admin | `/admin/` | Django admin. |
| Accounts | `/auth/login/`, `/auth/signup/`, `/auth/logout/` | Sign-in, account creation, and sign-out. |
| Dashboard | `/dashboard/` | Business overview. |
| Customers | `/customers/`, `/customers/create/`, `/customers/add/`, `/customers/print/`, `/customers/<uuid>/`, `/customers/<uuid>/edit/`, `/customers/<uuid>/delete/` | Customer list, create aliases, print, profile/detail, edit, delete. |
| Customer ledger/setup | `/customers/ledger/`, `/customers/bf-setup/`, `/customers/<uuid>/update-bf/` | Customer ledger, B.F. setup, and B.F. update. |
| Products | `/products/`, `/products/add/`, `/products/<uuid>/edit/`, `/products/<uuid>/delete/` | Product list, create, edit, delete. |
| Product stock | `/products/stock-details/`, `/products/stock-overview/` | Stock detail and summary reports. |
| Factory fills | `/products/factory-fill/`, `/products/factory-fill/<uuid>/`, `/products/factory-fill/<uuid>/edit/`, `/products/factory-fill/<uuid>/delete/` | Record fills, view factory history, edit or delete a fill. |
| Deliveries | `/deliveries/`, `/deliveries/add/`, `/deliveries/daily/`, `/deliveries/daily/payment/` | Delivery list/form, daily entry, and payment-only entry. |
| Payments | `/payments/`, `/payments/receive/` | Payment list and receive-payment form. |
| Cylinders | `/cylinders/`, `/cylinders/ledger/` | Cylinder dashboard and ledger. |
| Suppliers | `/suppliers/`, `/suppliers/add/`, `/suppliers/edit/<uuid>/`, `/suppliers/delete/<uuid>/` | Supplier list and CRUD. |
| Supplier ledger | `/suppliers/purchase-entry/`, `/suppliers/ledger/` | Purchase entry and supplier/product ledger. |
| Notifications | `/notifications/`, `/notifications/settings/` | Notification list and threshold settings. |
| FBR | `/fbr/`, `/fbr/invoices/`, `/fbr/invoices/manage-numbers/`, `/fbr/ledger/delivery/<uuid>/delete/` | FBR ledger, invoice report, invoice-number management, source delivery removal. |
| Earnings | `/earnings/` | Earnings and expense dashboard. |

Some templates render page actions as POST forms, print buttons, or JavaScript requests. The route table lists the declared paths, not a promise that every URL accepts every HTTP method.

## Internal JSON/look-up endpoints

### Customers

| Path | Purpose |
|---|---|
| `/customers/api/save-bf-customer/` | Save a B.F. setup/customer row from the B.F. setup interface. |

The customer app also uses page views for list filtering, profiles, and ledger data. The `delete` and `update-bf` routes are form/view actions rather than `/api/` endpoints.

### Deliveries and payments

| Path | Purpose |
|---|---|
| `/deliveries/daily/get-customer-balance/` | Return customer balance information for the daily-entry UI. |
| `/deliveries/validate-stock/` | Validate available stock for a delivery workflow. |
| `/deliveries/api/save-entry/` | Create or update one daily entry and synchronize related records. |
| `/deliveries/api/update-entry/` | Update a daily entry. |
| `/deliveries/api/delete-entry/` | Delete a daily entry and reconcile related data. |
| `/deliveries/api/daily-entries/` | Retrieve entries for the daily-entry interface. |
| `/deliveries/api/clear-entries/` | Clear entries for the selected workflow/date. |
| `/deliveries/api/save-payment/` | Save a payment from the daily-entry interface. |

The daily entry request shape is implemented by `templates/deliveries/daily_entry_combined.html` and `apps/deliveries/views.py`; it includes selected date, customer information, product/quantity/return information, price, and payment fields. The handler saves a `Delivery`, updates stock and cylinder movements, synchronizes linked `Payment` records, and refreshes customer activity. Check the current template and view before building another client.

### Products

| Path | Purpose |
|---|---|
| `/products/stock-details/opening-balance/save/` | Save the stock report's category opening balance. |
| `/products/factory-fill/stock/` | Return product stock for factory-fill UI selection. |
| `/products/<uuid>/stock/` | Return product stock and sellable/purchasable flags. This lookup currently has no view-level login decorator. |

### Suppliers

| Path | Purpose |
|---|---|
| `/suppliers/api/supplier-history/` | Return supplier purchase/payment history. |
| `/suppliers/api/save-purchase/` | Create purchase-entry data and related stock/accounting changes. |
| `/suppliers/api/daily-purchases/` | Return purchase entries for the daily purchase interface. |
| `/suppliers/api/delete-purchase/` | Delete purchase entries and reconcile related stock/accounting changes. |
| `/suppliers/api/update-purchase/` | Update purchase entries and reconcile related stock/accounting changes. |
| `/suppliers/api/get-purchase-details/` | Return purchase details for editing. |
| `/suppliers/api/ledger-products/` | Return product choices for the supplier ledger. |
| `/suppliers/api/ledger-suppliers/` | Return supplier choices for the supplier ledger. |

The purchase-entry template sends these requests; the API supports grouped product purchases and supplier-only payments. Mutating supplier endpoints are login-protected and explicitly CSRF-exempt in the current code. Do not assume the same request schema for every operation.

### FBR

| Path | Purpose |
|---|---|
| `/fbr/api/save-selected-customers/` | Save selected-customer state used by the FBR report interface. |
| `/fbr/api/save-customer-setting/` | Save customer-specific FBR settings such as STN/NTN. |
| `/fbr/invoices/manage-numbers/` | POST action to reset or sequentially assign invoice numbers for selected report groups. |

These are local report/number-management actions; they do not submit invoices to an external FBR service.

### Earnings

| Path | Purpose |
|---|---|
| `/earnings/api/details/` | Return income, paid purchases, expenses, partner-account snapshots, opening balance, and net-cash details for a date range. |
| `/earnings/api/expense/add/` | Add an expense. |
| `/earnings/api/expense/add-bulk/` | Validate and add a batch of expenses. |
| `/earnings/api/expense/delete/<int:expense_id>/` | Delete an expense. |
| `/earnings/api/opening-balance/save/` | Save an opening cash balance. |
| `/earnings/api/opening-balance/delete/` | Delete an opening balance. |
| `/earnings/api/partner-account/add/` | Add a partner-account snapshot. |
| `/earnings/api/partner-account/update/<int:account_id>/` | Update a partner-account snapshot. |
| `/earnings/api/partner-account/delete/<int:account_id>/` | Delete a partner-account snapshot. |

The earnings dashboard JavaScript sends CSRF tokens for its write requests and requests selected start/end dates for detail retrieval.

### Notifications and backup

| Path | Purpose |
|---|---|
| `/notifications/count/` | Return a notification count for the page UI. |
| `/notifications/run-checks/` | Run notification checks on demand. |
| `/notifications/mark-read/<uuid>/`, `/notifications/mark-all-read/` | Mark one or all notifications read. |
| `/notifications/delete/<uuid>/`, `/notifications/delete-all/`, `/notifications/delete-read/` | Delete selected notification records. |
| `/notifications/backup/` | Run the email backup workflow. |
| `/notifications/backup/download/` | Stream a local ZIP backup to the browser. |

## Request/response and error handling notes

- Internal JSON uses Django `JsonResponse`; payloads are specific to their page and may contain numbers serialized as strings or numbers.
- Mutation routes are generally intended for the application's own authenticated browser session. Follow the form's method, content type, field names, and CSRF handling.
- Several views return a `success` flag and an `error` or `message` field. HTTP status handling is not uniform; clients should inspect both status and response body.
- The browser templates may use URL reversing, inline JavaScript, or hard-coded app-relative paths. Update the view and template together when changing a route.
