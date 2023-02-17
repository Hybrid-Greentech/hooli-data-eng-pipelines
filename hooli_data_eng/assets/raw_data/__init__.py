import pandas as pd
from dagster import asset, RetryPolicy, Backoff, Jitter


@asset(
    compute_kind="api",
    required_resource_keys={"data_api"}
)
def users(context) -> pd.DataFrame:
    """A table containing all users data"""
    api = context.resources.data_api
    resp = api.get_users()
    users = pd.read_json(resp.json())
    return users


@asset(
    compute_kind="api",
    required_resource_keys={"data_api"},
    retry_policy=RetryPolicy(
        max_retries=3, 
        delay=1, 
        backoff=Backoff.LINEAR,
        jitter=Jitter.FULL
    ),
)
def orders(context) -> pd.DataFrame:
    """A table containing all orders that have been placed"""
    api = context.resources.data_api
    resp = api.get_orders()
    orders = pd.read_json(resp.json())
    orders['dt'] = pd.to_datetime(orders['dt'], unit = "ms")
    return orders
