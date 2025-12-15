"""
Тесты для search_entities: корректная работа с неожиданным Content-Type и ошибкой JSON
"""
import sys
import os
import json
import logging
import httpx
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import schedule
from app.schedule import search_entities


def _make_response(content: str, content_type: str = ""):
    """Утилита для создания httpx.Response с заданным Content-Type."""
    request = httpx.Request("GET", "https://kis.vgltu.ru/list?type=Group")
    headers = {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    return httpx.Response(200, content=content.encode("utf-8"), headers=headers, request=request)


class SearchEntitiesContentTypeTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_missing_content_type(self):
        """Должен успешно распарсить JSON даже при пустом Content-Type и вернуть отфильтрованный список."""
        sample = json.dumps(["ДЗ1-231-ОТ", "ДЗ1-232-ОТ"])
        response = _make_response(sample, "")  # пустой или отсутствующий header

        async def fake_request(url, cache, use_cache=True):
            return response

        with patch.object(schedule, "make_request_with_retry", fake_request), \
             self.assertLogs("app.schedule", level="INFO") as log_capture:
            result, error = await search_entities("231", "Group")

        self.assertIsNone(error)
        self.assertEqual(result, ["ДЗ1-231-ОТ"])
        # Не должно быть предупреждений/ошибок
        self.assertTrue(all(record.levelno < logging.WARNING for record in log_capture.records))

    async def test_handles_invalid_json(self):
        """При некорректном JSON должен вернуть ошибку и залогировать ее."""
        response = _make_response("not a json", "")  # нет json, нет заголовка

        async def fake_request(url, cache, use_cache=True):
            return response

        with patch.object(schedule, "make_request_with_retry", fake_request), \
             self.assertLogs("app.schedule", level="ERROR") as log_capture:
            result, error = await search_entities("231", "Group")

        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertTrue(any("Ошибка парсинга JSON" in record.getMessage() for record in log_capture.records))


if __name__ == "__main__":
    unittest.main()

