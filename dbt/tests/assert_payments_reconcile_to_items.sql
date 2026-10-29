-- Business rule: what the customer paid should equal item price + freight.
-- Known legitimate exception: credit-card instalment interest makes payments exceed items,
-- so orders with >1 instalment may only over-pay. Anything else beyond the tolerance is an
-- exception. Real data has a small number of such exceptions (see docs/DATA_QUALITY.md), so
-- this test WARNS on any exception and only ERRORS if exceptions exceed 0.5% of orders.
{{ config(severity='error', warn_if='>0', error_if='>493') }}
select
    order_id,
    items_total_brl,
    payment_total_brl,
    payment_total_brl - items_total_brl as diff_brl,
    max_installments
from {{ ref('fct_orders') }}
where payment_total_brl is not null
  and n_items > 0
  and abs(payment_total_brl - items_total_brl) > {{ var('payment_tolerance_brl') }}
  and not (max_installments > 1 and payment_total_brl > items_total_brl)
