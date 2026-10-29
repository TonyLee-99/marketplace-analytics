select
    product_id,
    category,
    category_pt,
    product_name_length,
    product_description_length,
    product_photos_qty,
    product_weight_g,
    product_length_cm,
    product_height_cm,
    product_width_cm,
    product_length_cm * product_height_cm * product_width_cm as product_volume_cm3
from {{ ref('stg_olist__products') }}
