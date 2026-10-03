# Data Contract: processed/customers

This is an agreement between the job that creates the clean purchase data and the jobs that use it.

### Producer
The Glue job `northstar-dev-transform`. It cleans the raw CSV and saves the result in `processed/customers/`.

### Consumers
- Feature engineering job `northstar-dev-feature-engineer`
- (Future) Direct model training in Lab 3

### Grain
One row per transaction. A customer appears on many rows.

### Schema
| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `transaction_id` | string | No | Unique ID for each purchase |
| `customer_id` | string | No | ID of the customer who bought |
| `purchase_date` | date | No | Date of the purchase |
| `order_value` | double | No | Total price of the order, in USD |
| `num_items` | int | No | Number of items in the order |
| `payment_method` | string | No | `credit_card`, `debit_card`, `gift_card`, or `cash` |
| `channel` | string | No | `online` or `store` |
| `store_id` | string | No | Store that made the sale, or `ONLINE` |
| `product_category` | string | No | Main type of product, or `unknown` if missing |

### Quality Guarantees
- `customer_id` is never null (0 empty values).
- No duplicate `transaction_id` rows (every ID appears exactly once). A `customer_id` repeating across rows is expected, not a defect.
- `order_value` is between 15.00 and 620.00, and `num_items` is between 1 and 9.
- `purchase_date` is a valid ISO 8601 date between 2025-04-01 and 2026-06-30.

### SLA
- Data is available in `processed/customers/` within 2 hours of landing in `raw/customers/`.

### Versioning
- Schema changes require a new S3 prefix (e.g., `processed/customers/v2/`).
- Breaking changes require consumer notification 5 business days in advance.
