"""Azure AI Search tool for querying the product catalog index."""

from __future__ import annotations

import json
import os
from typing import Any

from agent_framework import ai_function
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient


def _get_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    return value


def _make_search_client() -> SearchClient | None:
    endpoint = _get_env("AZURE_SEARCH_ENDPOINT")
    index_name = _get_env("AZURE_SEARCH_INDEX_NAME")

    if not endpoint or not index_name:
        return None

    api_key = _get_env("AZURE_SEARCH_API_KEY")
    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()

    return SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)


def _get_field(doc: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in doc:
            return doc[name]
    lower_map = {k.lower(): k for k in doc.keys()}
    for name in names:
        key = lower_map.get(name.lower())
        if key is not None:
            return doc[key]
    return None


@ai_function(
    name="search_catalog",
    description=(
        "Search the product catalog (Azure AI Search) and return matching products with details"
    ),
)
def search_catalog(query: str, top: int = 5) -> str:
    """Query Azure AI Search for products.

    Expects an existing Azure AI Search index (ideally populated by a blob indexer scheduled daily).

    Env vars:
    - AZURE_SEARCH_ENDPOINT
    - AZURE_SEARCH_INDEX_NAME
    - AZURE_SEARCH_API_KEY (optional; if omitted uses DefaultAzureCredential)
    """

    client = _make_search_client()
    if client is None:
        return json.dumps(
            {
                "error": "Azure Search is not configured. Set AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_INDEX_NAME (and optionally AZURE_SEARCH_API_KEY).",
            }
        )

    query = (query or "").strip()
    if not query:
        return json.dumps({"error": "Query is required"})

    top = int(top) if isinstance(top, int | float | str) else 5
    if top <= 0:
        top = 5
    if top > 20:
        top = 20

    try:
        results_iter = client.search(
            search_text=query,
            top=top,
            include_total_count=True,
        )

        results: list[dict[str, Any]] = []
        for r in results_iter:
            doc = dict(r)
            results.append(
                {
                    "productId": _get_field(doc, "ProductID", "productId", "id"),
                    "name": _get_field(doc, "ProductName", "name"),
                    "category": _get_field(doc, "ProductCategory", "category"),
                    "price": _get_field(doc, "Price", "price"),
                    "description": _get_field(doc, "ProductDescription", "description"),
                    "punchLine": _get_field(doc, "ProductPunchLine", "punchLine"),
                    "imageUrl": _get_field(doc, "ImageURL", "imageUrl"),
                    "score": getattr(r, "@search.score", None) if hasattr(r, "__getattr__") else doc.get("@search.score"),
                }
            )

        return json.dumps(
            {
                "query": query,
                "count": len(results),
                "results": results,
            }
        )

    except HttpResponseError as e:
        return json.dumps({"error": f"Azure Search error: {e.message if hasattr(e, 'message') else str(e)}"})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e)})
