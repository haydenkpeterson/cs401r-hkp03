# Data Contract: processed/customers

**Location:** `s3://northstar-dev-data-<account-id>/processed/customers/` (Parquet, snappy)
**Contract version:** 1.0 (2026-10-02)

## Producer
Team / process: Glue ETL job `northstar-dev-transform`, running as the `northstar-dev-DataEngineer` role.
Source: the `northstar_dev.customers` Glue catalog table, crawled from `raw/customers/`.

## Consumers
- Feature engineering job `northstar-dev-feature-engineer`
- (Future) Direct model training in Lab 3

## Grain
One row per transaction. A customer appears on many rows.

`transaction_id` is the primary key. `customer_id` repeating across rows is expected and is not a defect: that purchase history is what every downstream feature aggregates over.

## Schema
| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `transaction_id` | string | No | Primary key. Format `TXN-` + 12 uppercase alphanumerics. Unique. |
| `customer_id` | string | No | Customer key. Format `CUST-` + 8 digits. Trimmed of whitespace. Repeats across rows. |
| `purchase_date` | date | No | Date of purchase. Normalized from the raw data's two formats (`yyyy-MM-dd` and `MM/dd/yyyy`). |
| `order_value` | double | No | Gross order value in USD. Missing values imputed with the column median. |
| `num_items` | int | No | Line items in the order. Missing values imputed with the rounded column median. |
| `payment_method` | string | No | One of `credit_card`, `debit_card`, `gift_card`, `cash`, or `unknown` if missing. |
| `channel` | string | No | `online` or `store`, or `unknown` if missing. |
| `store_id` | string | No | `STORE-` + 3 digits for in-store orders, `ONLINE` for online orders, or `unknown` if missing. |
| `product_category` | string | No | Primary category: one of 8 (`Apparel`, `Beauty`, `Electronics`, `Footwear`, `Grocery`, `Home`, `Outdoor`, `Toys`), or `unknown` if missing. Consumers counting categories must exclude `unknown`. |

No column is nullable: nulls are either dropped (`customer_id`) or imputed (every other column) before the data is written.

## Quality Guarantees
Each guarantee is checked by the producer before writing. If one fails, the job fails and nothing is written.

- `customer_id` is never null: `COUNT(*) WHERE customer_id IS NULL = 0`.
- No duplicate `transaction_id` rows: `COUNT(DISTINCT transaction_id) = COUNT(*)`. A `customer_id` repeating across rows is expected, not a defect.
- `purchase_date` is a valid ISO 8601 date: `COUNT(*) WHERE purchase_date IS NULL = 0` after parsing, and every value falls in `[2025-04-01, 2026-06-30]`.
- Numeric ranges:
  - `order_value` in `[15.00, 620.00]` USD and never negative.
  - `num_items` is an integer in `[1, 9]`.
- Categorical values come only from the sets listed in the Schema table.
- Transaction grain is preserved: `COUNT(*) > COUNT(DISTINCT customer_id)`. A dataset with one row per customer means the producer deduplicated on the wrong key.
- Row-count sanity: for the current sample, 157,627 rows covering 9,999 customers (from 163,255 raw rows, after dropping 3,265 with no `customer_id` and 2,363 duplicate transactions). A run producing a different count from the same input is a regression.

## SLA
- Data is available in `processed/customers/` within 2 hours of landing in `raw/customers/`.
  - Measured today: the crawler plus the transform job complete in under 5 minutes end to end (transform run time: 119 seconds).
- Each run fully replaces the dataset (`mode("overwrite")`). Consumers must not read while a run is in progress. In practice: check that the latest `northstar-dev-transform` run is `SUCCEEDED` before reading.

## Versioning
- Schema changes require a new S3 prefix (e.g., `processed/customers/v2/`). The current prefix stays in place until every consumer has migrated.
- Breaking changes require consumer notification 5 business days in advance.
  - Breaking: removing or renaming a column, changing a column's type, changing the grain, or narrowing a guarantee (e.g., allowing nulls).
  - Non-breaking: adding a nullable column, or tightening a numeric range. These may be released in place with notice.
- Earlier versions of the data remain recoverable through S3 object versioning for 30 days (lifecycle rule `expire-processed-versions`).
