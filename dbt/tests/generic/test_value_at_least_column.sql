{# Row-level rule: column_name >= other_column (nulls ignored). E.g. delivered >= purchased. #}
{% test value_at_least_column(model, column_name, other_column) %}
select *
from {{ model }}
where {{ column_name }} is not null
  and {{ other_column }} is not null
  and {{ column_name }} < {{ other_column }}
{% endtest %}
