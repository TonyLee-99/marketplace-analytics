select
    seller_id,
    seller_zip_code_prefix                  as seller_zip_prefix,
    lower(strip_accents(trim(seller_city))) as seller_city,
    upper(seller_state)                     as seller_state
from {{ source('olist', 'sellers') }}
