-- SCD2 integrity: exactly one current row per person and no overlapping validity windows.
with cur as (
    select customer_unique_id, count(*) filter (where is_current) as n_current
    from {{ ref('dim_customer_location_history') }} group by 1
),
overlap as (
    select a.customer_unique_id
    from {{ ref('dim_customer_location_history') }} a
    join {{ ref('dim_customer_location_history') }} b
      on a.customer_unique_id = b.customer_unique_id
     and a.version_number < b.version_number
     and coalesce(a.valid_to, timestamp '9999-12-31') > b.valid_from
)
select customer_unique_id, 'not exactly one current row' as problem from cur where n_current <> 1
union all
select customer_unique_id, 'overlapping windows' from overlap
