# Synthetic ETL fixture

This small, invented example is intended for local review and automated tests. It is not anonymized production data: no real business records were used to create it.

## Files

| File | Role |
|---|---|
| `scopes.json` | Trusted configuration linking each synthetic entity to its customer/project |
| `order-changes.jsonl` | Ordered incoming deliveries, including duplicates, a late version and deletion |
| `expected-current.json` | Independently reviewed expected current records and logical event IDs |

The runner rejects an absent synthetic marker or duplicate ownership mappings. Event ownership is still checked by the production ETL validator against the separate mapping. The marker is a fixture convention, not a general sensitive-data detector.

## Expected result

Nine raw deliveries produce seven unique logical events and two current order lines. The deleted second A order has a retained tombstone and no current row.

| Current entity | Customer/project | Version | Quantity | Extended cost, cents | Extended selling amount, cents |
|---|---|---:|---:|---:|---:|
| ORDER-A001-L1 | CUSTOMER-A / PROJECT-A | 3 | 12,000 | 15,600,000 | 18,000,000 |
| ORDER-B001-L1 | CUSTOMER-B / PROJECT-B | 2 | 4,500 | 3,825,000 | 4,612,500 |

For A, `12,000 * 1,300 = 15,600,000` cents. For B, `4,500 * 1,025 = 4,612,500` cents. The expected totals are written into the fixture, not recalculated with the worker's transform to declare success.

The default demo uses three deliveries per batch so boundaries remain easy to inspect. Tests repeat the same fixture with other batch sizes and verify the same final result.

## Implemented event contract

Every event has `event_id`, `entity_id`, `version`, `operation`, `customer_id` and `project_id`. Upserts also require positive integer `quantity`, `currency` equal to `USD`, decimal-string `unit_cost` and `unit_price`, and `design_version`. Supported monetary amounts have at most two decimal places. Deletes need only identity, ownership, version and operation.

`version` is a source-supplied business version, not event time. The local source assigns monotonic delivery offsets. Event ID reuse with conflicting semantic content is rejected.

This fixture does not contain delivery deadlines, actual fulfillment, capacity, yield, allocation or forecasts. Their absence must not be interpreted as zero or filled with invented facts. Risk features, labels and model training remain planned.

## Review and failure checks

Run `python3.11 -m scripts.run_local` from the project root. The report lists each batch, the final records and reconciliation checks.

The unit suite deliberately changes an event to another customer and checks that nothing is published. It also changes a valid unit amount and confirms that the reviewed expected output catches the discrepancy despite a completed checkpoint. Existing ETL tests cover invalid money, version conflicts, atomic rollback, crash recovery and deletion ordering.

Existing demo workspaces are never reset. Use a new directory for each run. Generated SQLite files remain under ignored runtime artifacts.
