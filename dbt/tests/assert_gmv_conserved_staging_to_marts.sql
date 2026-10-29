-- Conservation check: no item revenue is lost or duplicated between staging and marts.
with s as (select sum(price_brl) as v, count(*) as n from {{ ref('stg_olist__order_items') }}),
     m as (select sum(price_brl) as v, count(*) as n from {{ ref('fct_order_items') }}),
     o as (select sum(items_price_brl) as v from {{ ref('fct_orders') }})
select * from s, m, o
where s.v <> m.v or s.n <> m.n or s.v <> o.v
