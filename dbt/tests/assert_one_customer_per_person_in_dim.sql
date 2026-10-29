-- Every person who placed an order appears in dim_customers exactly once.
select o.customer_unique_id
from (select distinct customer_unique_id from {{ ref('fct_orders') }}) o
left join {{ ref('dim_customers') }} d using (customer_unique_id)
where d.customer_unique_id is null
