from contextvars import ContextVar

# False while a vcr-auto walk still has a later Model ID: the pool must not queue.
wait_for_pool_slot: ContextVar[bool] = ContextVar("wait_for_pool_slot", default=True)
