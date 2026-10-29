-- 547 orders have more than one review row. Keep the most recently answered one
-- (customers can re-submit the survey); keep the count so the analysis can see it.
with ranked as (
    select
        *,
        row_number() over (
            partition by order_id
            order by review_answered_at desc, review_sent_at desc, review_id
        ) as rn,
        count(*) over (partition by order_id) as n_reviews_for_order
    from {{ ref('stg_olist__reviews') }}
)

select * exclude (rn)
from ranked
where rn = 1
