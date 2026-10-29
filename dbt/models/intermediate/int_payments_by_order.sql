with ranked as (
    select
        *,
        row_number() over (partition by order_id order by payment_value_brl desc, payment_sequential) as rn
    from {{ ref('stg_olist__payments') }}
)

select
    order_id,
    sum(payment_value_brl)                            as payment_total_brl,
    count(*)                                          as n_payments,
    max(payment_installments)                         as max_installments,
    max(case when rn = 1 then payment_type end)       as primary_payment_type,
    bool_or(payment_type = 'voucher')                 as used_voucher
from ranked
group by order_id
