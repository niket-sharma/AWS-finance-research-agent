"""Unit tests for tools/kb_retrieve/handler.py — mocked Bedrock KB responses."""

import json
import os
from unittest.mock import MagicMock, patch


def test_no_kb_id_returns_unavailable():
    with patch.dict(os.environ, {}, clear=True):
        from tools.kb_retrieve.handler import retrieve_passages
        result = retrieve_passages("AAPL revenue growth")
        assert result["status"] == "unavailable"
        assert result["passages"] == []


def test_retrieve_passages_success():
    with patch.dict(os.environ, {"KB_ID": "kb-123"}):
        with patch("tools.kb_retrieve.handler._client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.retrieve.return_value = {
                "retrievalResults": [
                    {
                        "content": {"text": "Revenue grew 8% YoY driven by Services."},
                        "location": {"s3Location": {"uri": "s3://research-desk-corpus/aapl-10k-2025.txt"}},
                        "score": 0.87,
                    }
                ]
            }
            mock_client_fn.return_value = mock_client
            from tools.kb_retrieve.handler import retrieve_passages
            result = retrieve_passages("AAPL revenue growth", ticker="AAPL")

            assert result["status"] == "ok"
            assert len(result["passages"]) == 1
            assert result["passages"][0]["text"] == "Revenue grew 8% YoY driven by Services."
            assert result["passages"][0]["source"] == "s3://research-desk-corpus/aapl-10k-2025.txt"
            mock_client.retrieve.assert_called_once()
            call_kwargs = mock_client.retrieve.call_args.kwargs
            assert call_kwargs["knowledgeBaseId"] == "kb-123"
            assert "AAPL" in call_kwargs["retrievalQuery"]["text"]


def test_retrieve_passages_empty_results():
    with patch.dict(os.environ, {"KB_ID": "kb-123"}):
        with patch("tools.kb_retrieve.handler._client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.retrieve.return_value = {"retrievalResults": []}
            mock_client_fn.return_value = mock_client
            from tools.kb_retrieve.handler import retrieve_passages
            result = retrieve_passages("obscure query")
            assert result["status"] == "ok"
            assert result["passages"] == []


def test_retrieve_passages_client_error_degrades():
    from botocore.exceptions import ClientError
    with patch.dict(os.environ, {"KB_ID": "kb-123"}):
        with patch("tools.kb_retrieve.handler._client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.retrieve.side_effect = ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "KB not found"}},
                "Retrieve",
            )
            mock_client_fn.return_value = mock_client
            from tools.kb_retrieve.handler import retrieve_passages
            result = retrieve_passages("AAPL revenue growth")
            assert result["status"] == "unavailable"
            assert result["passages"] == []


def test_lambda_handler_success():
    with patch.dict(os.environ, {"KB_ID": "kb-123"}):
        with patch("tools.kb_retrieve.handler._client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.retrieve.return_value = {"retrievalResults": []}
            mock_client_fn.return_value = mock_client
            from tools.kb_retrieve.handler import lambda_handler
            resp = lambda_handler({"query": "AAPL margins", "ticker": "AAPL"}, None)
            assert resp["statusCode"] == 200
            body = json.loads(resp["body"])
            assert body["status"] == "ok"


def test_lambda_handler_missing_query():
    resp_module_import = __import__("tools.kb_retrieve.handler", fromlist=["lambda_handler"])
    resp = resp_module_import.lambda_handler({}, None)
    assert resp["statusCode"] == 400
