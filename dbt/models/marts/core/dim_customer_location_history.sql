-- SCD2 address history per person (see int_customer_location_history for logic).
select * from {{ ref('int_customer_location_history') }}
