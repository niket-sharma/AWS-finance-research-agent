"""Unit tests for shared/cache.py — graceful degradation on DynamoDB failure."""

from unittest.mock import MagicMock, patch


def test_cache_miss_returns_none():
    with patch("shared.cache._table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_table_fn.return_value = mock_table
        from shared.cache import get
        result = get("tool", "AAPL", "2025-01-01")
        assert result is None


def test_cache_hit_returns_value():
    import json
    import time
    with patch("shared.cache._table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "pk": "tool#AAPL#2025-01-01",
                "payload": json.dumps({"price": 180.0}),
                "ttl": int(time.time()) + 3600,
            }
        }
        mock_table_fn.return_value = mock_table
        from shared.cache import get
        result = get("tool", "AAPL", "2025-01-01")
        assert result == {"price": 180.0}


def test_cache_expired_returns_none():
    import json
    import time
    with patch("shared.cache._table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "pk": "tool#AAPL#2025-01-01",
                "payload": json.dumps({"price": 180.0}),
                "ttl": int(time.time()) - 10,  # expired
            }
        }
        mock_table_fn.return_value = mock_table
        from shared.cache import get
        result = get("tool", "AAPL", "2025-01-01")
        assert result is None


def test_cache_dynamodb_error_returns_none():
    from botocore.exceptions import ClientError
    with patch("shared.cache._table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.get_item.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Table not found"}},
            "GetItem",
        )
        mock_table_fn.return_value = mock_table
        from shared.cache import get
        result = get("tool", "AAPL", "2025-01-01")
        assert result is None


def test_cache_put_silent_on_error():
    from botocore.exceptions import ClientError
    with patch("shared.cache._table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "service down"}},
            "PutItem",
        )
        mock_table_fn.return_value = mock_table
        from shared.cache import put
        # Should not raise
        put("tool", "AAPL", "2025-01-01", {"price": 180.0})
