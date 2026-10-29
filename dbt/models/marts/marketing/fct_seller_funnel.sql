-- Grain: one row per marketing-qualified lead (8,000). Tracks MQL -> closed deal -> first sale.
select
    m.mql_id,
    m.first_contact_date,
    m.origin,
    d.seller_id,
    d.won_at,
    d.business_segment,
    d.lead_type,
    d.mql_id is not null                          as is_won,
    date_diff('day', m.first_contact_date, cast(d.won_at as date)) as days_to_close,
    s.first_sale_at,
    s.n_orders                                    as seller_orders,
    s.gmv_brl                                     as seller_gmv_brl,
    s.first_sale_at is not null                   as has_sold
from {{ ref('stg_olist__mqls') }} as m
left join {{ ref('stg_olist__closed_deals') }} as d using (mql_id)
left join {{ ref('dim_sellers') }} as s on d.seller_id = s.seller_id
