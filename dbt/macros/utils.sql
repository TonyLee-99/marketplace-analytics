{# Whole calendar days between two timestamps/dates (b - a), on the DATE level. #}
{% macro day_diff(a, b) -%}
    date_diff('day', cast({{ a }} as date), cast({{ b }} as date))
{%- endmacro %}

{# Fractional days between two timestamps (b - a). #}
{% macro frac_days(a, b) -%}
    (epoch(cast({{ b }} as timestamp)) - epoch(cast({{ a }} as timestamp))) / 86400.0
{%- endmacro %}

{# Great-circle distance in km. #}
{% macro haversine_km(lat1, lng1, lat2, lng2) -%}
    2 * 6371 * asin(sqrt(
        pow(sin(radians({{ lat2 }} - {{ lat1 }}) / 2), 2)
        + cos(radians({{ lat1 }})) * cos(radians({{ lat2 }}))
        * pow(sin(radians({{ lng2 }} - {{ lng1 }}) / 2), 2)
    ))
{%- endmacro %}
