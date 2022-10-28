from typing import Any, Tuple

import numpy as np
import pandas as pd
from scipy import optimize

from dagster import AssetIn, asset,  MonthlyPartitionsDefinition

from prophet import Prophet


def model_func(x, a, b):
    return a * np.exp(b * (x / 10**18 - 1.6095))


@asset(
    ins={"daily_order_summary": AssetIn(key_prefix=["analytics"])},
    compute_kind="ml_tool",
    io_manager_key="model_io_manager",
    config_schema={"a_init": int, "b_init": int}
    
)
def order_forecast_model(context, daily_order_summary: pd.DataFrame) -> Any:
    """Model parameters that best fit the observed data"""
    df = daily_order_summary
    p0 = [context.op_config["a_init"], context.op_config["b_init"]]
    coeffs = tuple(
        optimize.curve_fit(
            f=model_func, xdata=df.order_date.astype(np.int64), ydata=df.num_orders, p0=p0
        )[0]
    )
    context.log.info("Starting with: " + str(p0[0]) + " and " + str(p0[1]))
    context.log.info("Ended with: " + str(coeffs[0]) + " and " + str(coeffs[1]))
    return coeffs

@asset(
    ins={"daily_order_summary": AssetIn(key_prefix=["analytics"])},
    compute_kind="ml_tool",
    key_prefix=["forecasting"]
)
def order_prophet_model(context, daily_order_summary: pd.DataFrame) -> pd.DataFrame:
    """Model parameters that best fit the observed data"""
    df = pd.DataFrame({
      'ds': daily_order_summary['order_date'],
      'y': daily_order_summary['num_orders']
    })
    m = Prophet()
    m.fit(df)
    future = m.make_future_dataframe(periods=30)
    forecast = m.predict(future)
    return forecast

@asset(
  ins={
        "daily_order_summary": AssetIn(key_prefix=["analytics"]),
        "order_forecast_model": AssetIn(),
    },
    compute_kind="ml_tool",
    key_prefix=["forecasting"],
    io_manager_key="model_io_manager",
    partitions_def=MonthlyPartitionsDefinition(start_date="2022-01-01")
)
def model_stats_by_day(context, daily_order_summary: pd.DataFrame, order_forecast_model: Tuple[float, float]) -> pd.DataFrame:
    """Model errors by day"""
    a, b = order_forecast_model
    target_date = pd.to_datetime(context.asset_partition_key_for_output())
    target_month = target_date.month
    daily_order_summary['order_date'] = pd.to_datetime(daily_order_summary['order_date'])
    daily_order_summary['order_month'] = pd.DatetimeIndex(daily_order_summary['order_date']).month
    target_orders = daily_order_summary[(daily_order_summary['order_month'] == target_month)]
    date_range  = pd.date_range(
        start=target_date, end=target_date + pd.DateOffset(days=30)
    )
    predicted_orders = model_func(x = date_range.astype(np.int64), a=a, b=b)
    error = sum(target_orders['num_orders']) - sum(predicted_orders)
    context.log.info("Error for " + str(target_date) + ": " + str(error))

    return pd.DataFrame({"error": [error]})


@asset(
    ins={
        "daily_order_summary": AssetIn(key_prefix=["analytics"]),
        "order_forecast_model": AssetIn(),
    },
    compute_kind="ml_tool",
    key_prefix=["forecasting"],
)
def predicted_orders(
    daily_order_summary: pd.DataFrame, order_forecast_model: Tuple[float, float]
) -> pd.DataFrame:
    """Predicted orders for the next 30 days based on the fit paramters"""
    a, b = order_forecast_model
    start_date = daily_order_summary.order_date.max()
    future_dates = pd.date_range(
        start=start_date, end=pd.to_datetime(start_date) + pd.DateOffset(days=30)
    )
    predicted_data = model_func(x=future_dates.astype(np.int64), a=a, b=b)
    return pd.DataFrame({"order_date": future_dates, "num_orders": predicted_data})
