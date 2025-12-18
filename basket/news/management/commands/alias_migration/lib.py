import threading
import time
from itertools import chain

from basket.news.backends.braze import braze


def build_alias_operations_from_dataframe(dataframe):
    return list(
        chain.from_iterable(build_alias_operations_from_dataframe_row(row) for row in dataframe.itertuples(index=False)),
    )


def build_alias_operations_from_dataframe_row(row):
    external_id = row.email_id
    basket_token = row.basket_token
    fxa_id = getattr(row, "fxa_id", "")

    alias_operations = [
        {
            "external_id": external_id,
            "alias_label": "basket_token",
            "alias_name": basket_token,
        }
    ]

    if fxa_id:
        alias_operations.append(
            {
                "external_id": external_id,
                "alias_label": "fxa_id",
                "alias_name": fxa_id,
            }
        )
    return alias_operations


def create_batched_chunks(alias_operations, batch_size, chunk_size):
    """
    Takes a flat list of alias_operations and organizes them into batches of chunks.

    Args:
        alias_operations (list): Flat list of alias_operations
        batch_size (int): Number of chunks per batch
        chunk_size (int): Number of alias_operations per chunk

    Returns:
        list: List of batches, where each batch is a list of chunks,
              and each chunk is a list of alias_operations
    """
    chunks = []
    for i in range(0, len(alias_operations), chunk_size):
        chunk = alias_operations[i : i + chunk_size]
        chunks.append(chunk)

    batches = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        batches.append(batch)

    return batches


def fake_add_aliases(alias_opererations):
    time.sleep(0.4)
    return {
        "aliases_processed": len(alias_opererations),
        "message": "success",
    }


def mask(external_id):
    parts = str(external_id).split("-")
    return "-".join(["***"] * 3 + parts[3:])


class ThreadSafeRateLimiter:
    def __init__(self, max_requests=19500, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.time()

            # Remove old requests
            self.requests = [req_time for req_time in self.requests if req_time > now - self.time_window]

            # Check if we can make a request
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                time.sleep(sleep_time)
                return self.acquire()

            self.requests.append(now)


def rate_limited_add_aliases(chunk, rate_limiter):
    rate_limiter.acquire()
    return braze.interface.add_aliases(chunk)
