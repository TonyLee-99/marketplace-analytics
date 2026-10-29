-- depends_on: {{ ref('fct_order_items') }}
-- Fan-out guard: order-level measures must not appear un-prefixed on the item fact.
select column_name
from information_schema.columns
where table_schema = 'marts' and table_name = 'fct_order_items'
  and column_name in ('review_score', 'is_late', 'days_late', 'lane', 'is_delivered')
