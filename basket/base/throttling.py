from ninja.throttling import SimpleRateThrottle


class MultiPeriodThrottle(SimpleRateThrottle):
    """
    Adds support for multiple periods in the rate string.

    This supports the formats: <count> / <multiple><period>

    Where the period can be one of:
    - 's' (second)
    - 'm' (minute)
    - 'h' (hour)
    - 'd' (day)

    Examples:
    - '10/s' (10 per second)
    - '10/1s' (10 per second)
    - '10/5s' (10 per 5 seconds)

    # TODO: Remove when django-ninja is updated > 1.3.0
    """

    _PERIODS = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 60 * 60 * 24,
    }

    def parse_rate(self, rate: str | None) -> tuple[int, int] | tuple[None, None]:
        if rate is None:
            return (None, None)

        try:
            count, rest = rate.split("/", 1)

            if rest[-1] in self._PERIODS:
                multi, period = rest[:-1] if rest[:-1] else 1, self._PERIODS[rest[-1]]
            else:
                multi, period = rest, 1

            return int(count), int(multi) * period

        except ValueError:
            raise ValueError(f"Invalid rate format: {rate}") from None


class TokenThrottle(MultiPeriodThrottle):
    """
    Limits the rate of API calls.

    The basket token will be used as the unique cache key.
    """

    def get_cache_key(self, request) -> str | None:
        # Get the token from the request path params.
        token = request.resolver_match.kwargs.get("token")
        if token is None:
            return None

        return self.cache_format % {
            "scope": "token",
            "ident": token,
        }
