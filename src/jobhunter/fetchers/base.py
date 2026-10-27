import time

import requests

USER_AGENT = "Job-Hunter/0.1 (personal job search)"
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


class BoardNotFound(FetchError):
    pass


def get_json(url, params=None, retries=3, timeout=30, session=None):
    client = session or requests
    last_error = None
    for attempt in range(retries):
        try:
            response = client.get(
                url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT}
            )
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2**attempt)
            continue
        if response.status_code == 404:
            raise BoardNotFound(url)
        if response.status_code in _RETRY_STATUSES:
            last_error = FetchError(f"HTTP {response.status_code} from {url}")
            time.sleep(2**attempt)
            continue
        try:
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise FetchError(f"{url}: {exc}") from exc
    raise FetchError(f"{url}: gave up after {retries} attempts ({last_error})")
