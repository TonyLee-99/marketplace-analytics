-- Fixes the source's misspelled column names ("lenght") and fills missing categories.
with translation as (
    select product_category_name, product_category_name_english
    from {{ source('olist', 'category_translation') }}
    union all
    select product_category_name, product_category_name_english
    from {{ ref('category_translation_patch') }}
)

select
    p.product_id,
    coalesce(p.product_category_name, 'unknown')                  as category_pt,
    coalesce(t.product_category_name_english,
             case when p.product_category_name is null then 'unknown' end) as category,
    cast(p.product_name_lenght as integer)        as product_name_length,
    cast(p.product_description_lenght as integer) as product_description_length,
    cast(p.product_photos_qty as integer)         as product_photos_qty,
    -- 4 products have weight 0 g: physically impossible -> treat as unknown.
    nullif(cast(p.product_weight_g as double), 0) as product_weight_g,
    cast(p.product_length_cm as double)           as product_length_cm,
    cast(p.product_height_cm as double)           as product_height_cm,
    cast(p.product_width_cm as double)            as product_width_cm
from {{ source('olist', 'products') }} as p
left join translation as t
    on p.product_category_name = t.product_category_name
