-- review_id is NOT unique in the source (the same survey answer can be attached to several
-- orders), so the grain here is (review_id, order_id).
select
    review_id || '-' || order_id                     as review_key,
    review_id,
    order_id,
    cast(review_score as integer)                    as review_score,
    nullif(trim(review_comment_title), '')           as review_title,
    nullif(trim(review_comment_message), '')         as review_message,
    cast(review_creation_date as timestamp)          as review_sent_at,
    cast(review_answer_timestamp as timestamp)       as review_answered_at
from {{ source('olist', 'order_reviews') }}
