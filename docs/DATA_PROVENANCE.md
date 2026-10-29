# Data provenance

## What the data is
- **Olist Brazilian E-Commerce Public Dataset**, published by Olist (Brazilian marketplace
  integrator) on Kaggle: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce .
  About 100k real orders placed 2016-09 to 2018-10 on multiple Brazilian marketplaces, anonymised
  (company names in review text replaced by Game of Thrones house names, which is why "lannister" and
  "stark" appear in the reviews).
- **Olist Marketing Funnel** (closed deals + marketing qualified leads):
  https://www.kaggle.com/datasets/olistbr/marketing-funnel-olist .
- **License: CC BY-NC-SA 4.0** (attribution, non-commercial, share-alike), as published by Olist on
  Kaggle. This repository is a non-commercial portfolio project; raw files are not committed
  (`data/` is gitignored) and are downloaded by `make ingest`.

## Where the files were obtained
Kaggle needs credentials we did not have, so the files were taken from public mirrors and
verified against each other and against the published row counts.

| Data | Primary mirror (downloaded) | Independent verification mirrors |
|---|---|---|
| E-commerce (9 tables) | https://huggingface.co/datasets/aviahYadler/Olist_Ecommerce_Dataset | https://huggingface.co/datasets/bulutttt/olist-raw-data , https://huggingface.co/datasets/MafiaAzulBr/olistcsv |
| Marketing funnel (2 tables) | https://github.com/mara/mara-olist-ecommerce-data (data/olist-marketing-funnel) | https://github.com/patterns-app/public_data (data/olist) |

## Verification performed (2026-10-29)
1. **Byte identity across mirrors.** For the 4 LFS files the SHA-256 published by the Hugging
   Face API for both verification mirrors equals the SHA-256 of our download; for the 5 small
   files the git blob hash (`git hash-object`) of our download equals the blob id on both
   verification mirrors. Funnel files: SHA-256 identical between the two GitHub mirrors.
2. **Row counts** equal the published originals: orders 99,441; order_items 112,650;
   payments 103,886; reviews 99,224; customers 99,441; sellers 3,095; products 32,951;
   geolocation 1,000,163; category translation 71; closed deals 842; MQLs 8,000.
3. **Schema unmodified**: column names and order match the original Kaggle headers (including the
   source's own misspellings `product_name_lenght` / `product_description_lenght` and the UTF-8
   BOM in the translation file, which a re-saved copy would usually lose).

All of this is pinned in `data_manifest.json` (sha256, bytes, rows, columns) and re-checked on
every `make ingest`, which refuses to load a file that differs.
