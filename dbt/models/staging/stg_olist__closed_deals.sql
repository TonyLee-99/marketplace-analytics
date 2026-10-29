select
    mql_id,
    seller_id,
    sdr_id,
    sr_id,
    cast(won_date as timestamp)                     as won_at,
    business_segment,
    lead_type,
    lead_behaviour_profile,
    business_type,
    cast(declared_monthly_revenue as double)        as declared_monthly_revenue_brl
from {{ source('olist', 'closed_deals') }}
