from dagster import (
    asset,
    build_last_update_freshness_checks,
    build_sensor_for_freshness_checks,
    AssetIn,
    DynamicPartitionsDefinition,
    MetadataValue,
    AssetExecutionContext,
    AssetCheckResult,
    asset_check,
    AssetKey,
    FreshnessPolicy,
    define_asset_job, 
    ScheduleDefinition,
    AssetSelection
)
import pandas as pd
import datetime
from dagster_cloud.anomaly_detection import build_anomaly_detection_freshness_checks

from hooli_data_eng.assets.dbt_assets import allow_outdated_parents_policy


# These assets take data from a SQL table managed by
# dbt and create summaries using pandas
@asset(
    key_prefix="MARKETING",
    auto_materialize_policy=allow_outdated_parents_policy,
    compute_kind="pandas",
    owners=["team:programmers", "lopp@dagsterlabs.com"],
    ins={"company_perf": AssetIn(key_prefix=["ANALYTICS"])},
)
def avg_orders(
    context: AssetExecutionContext, company_perf: pd.DataFrame
) -> pd.DataFrame:
    """Computes avg order KPI, must be updated regularly for exec dashboard"""

    return pd.DataFrame(
        {"avg_order": company_perf["total_revenue"] / company_perf["n_orders"]}
    )


@asset_check(description="check that avg orders are expected", asset=avg_orders)
def check_avg_orders(context, avg_orders: pd.DataFrame):
    avg = avg_orders["avg_order"][0]
    return AssetCheckResult(
        passed=True if (avg < 50) else False,
        metadata={"actual average": avg, "threshold": 50},
    )


@asset(
    key_prefix="MARKETING",
    compute_kind="snowflake",
    owners=["team:programmers"],
    ins={"company_perf": AssetIn(key_prefix=["ANALYTICS"])},
)
def min_order(context, company_perf: pd.DataFrame) -> pd.DataFrame:
    """Computes min order KPI"""
    min_order = min(company_perf["n_orders"])

    context.add_output_metadata({"min_order": min_order})

    return pd.DataFrame({"min_order": [min_order]})


product_skus = DynamicPartitionsDefinition(name="product_skus")


@asset(
    partitions_def=product_skus,
    io_manager_key="model_io_manager",
    compute_kind="hex",
    key_prefix="MARKETING",
    ins={"sku_stats": AssetIn(key_prefix=["ANALYTICS"])},
)
def key_product_deepdive(context, sku_stats):
    """Creates a file for a BI tool based on the current quarters top product, represented as a dynamic partition"""
    key_sku = context.partition_key
    sku = sku_stats[sku_stats["sku"] == key_sku]
    context.add_output_metadata(
        {"sku_preview": MetadataValue.md(sku.head().to_markdown())}
    )
    return sku


min_order_freshness_check = build_last_update_freshness_checks(
    assets=[min_order, 
            AssetKey(["RAW_DATA", "orders"]),
            AssetKey(["RAW_DATA", "users"])
            ],
    lower_bound_delta=datetime.timedelta(
        hours=24
    ),  # expect new data at least once a day
)

avg_orders_freshness_check = build_anomaly_detection_freshness_checks(
    assets=[avg_orders], 
    params=None
)

min_order_freshness_check_sensor = build_sensor_for_freshness_checks(
    freshness_checks=min_order_freshness_check, 
    minimum_interval_seconds=10*60
)

avg_orders_freshness_check_schedule = ScheduleDefinition(
    name="check_avg_orders_freshness_schdule",
    cron_schedule="*/10 * * * *",
    job=define_asset_job(
        "check_avg_orders_freshness_job",
        selection=AssetSelection.checks(avg_orders_freshness_check)
    )
)
