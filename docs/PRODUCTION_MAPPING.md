# How this maps to production at a large company
- **Kimball dimensional modelling.** Conformed dims and transaction-grain facts, with an SCD2 address
  history (R. Kimball & M. Ross, *The Data Warehouse Toolkit*, 3rd ed., Wiley 2013).
- **dbt Labs best practices.** The staging/intermediate/marts layering and naming follow
  ["How we structure our dbt projects"](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview).
  The project also uses tests, source freshness, exposures and snapshots.
- **Governed metrics.** One definition, consumed everywhere, as in Airbnb's Minerva
  (["How Airbnb achieved metric consistency at scale"](https://medium.com/airbnb-engineering/how-airbnb-achieved-metric-consistency-at-scale-f23cc53dea70))
  and the [dbt Semantic Layer / MetricFlow](https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl).
  Here a small YAML compiler plays that role.
- **Data team handbooks.** GitLab's public [data team handbook](https://handbook.gitlab.com/handbook/enterprise-data/)
  (dbt guide, trusted data framework, KPI definitions with owners). Shopify's data engineering
  posts on dbt and modelling standards ([shopify.engineering](https://shopify.engineering/)).
- **Root cause.** LinkedIn ThirdEye (open-sourced anomaly detection and root-cause analysis) and
  Bhagwan et al., *Adtributor: Revenue Debugging in Advertising Systems* (NSDI 2014), the source
  of the explanatory-power and surprise (JS divergence) ranking used here.
- **Promise calibration.** Retailers' delivery-date promises are quantile forecasts. The conversion
  upside assumption comes from Fisher, Gallino & Xu, *The Value of Rapid Delivery in Omnichannel
  Retailing*, J. Marketing Research 56(5), 2019: +1.45% sales per business day faster. Conformalised
  quantiles follow Romano, Patterson & Candès, *Conformalized Quantile Regression*, NeurIPS 2019.
- **Monitoring.** STL decomposition (Cleveland et al., 1990) with robust z-scores on one-step-ahead
  errors and an event calendar, the usual "expected vs actual with known-event suppression" pattern
  in BI alerting.
