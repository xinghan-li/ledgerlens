# Store Receipt Configs (Config-Driven Pipeline)

One config per chain/banner drives the generic wash-data + parse pipeline.  
No per-store Python scripts; add new stores by adding a JSON config.

## Config file naming

- `{chain_slug}.json` — e.g. `island_gourmet_markets.json`, `tt_supermarket.json`
- Chain slug: lowercase, alphanumeric + underscore

## Config structure (see schema and island_gourmet_markets.json)

- **identification**: names/aliases to match this chain
- **header**: where header ends (Inv#, Trs#, separator)
- **items**: item format (quantity/unit price, name+amount, Code, discounts, fees)
- **totals**: subtotal → total calculation (tax, bottle deposit, env fee)
- **payment**: markers and fields to aggregate after TOTAL SALES
- **wash_data**: exclude patterns so non-amounts (SC-1, Points, etc.) don’t pollute sums

## Aggregated output

Pipeline output conforms to `aggregated_receipt_schema.json` for storage and CSV export.
