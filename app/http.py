import asyncio
import httpx
import logging
from cachetools import TTLCache

logger = logging.getLogger(__name__)

http_client = None

def get_http_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None:
        # Оптимизированный HTTP клиент с пулом соединений для высокой нагрузки
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
            limits=limits
            # HTTP/2 отключен, так как требует дополнительный пакет 'h2'
            # Для установки HTTP/2 поддержки: pip install httpx[http2]
        )
    return http_client

async def close_http_client():
    global http_client
    if http_client:
        await http_client.aclose()
        http_client = None

async def make_request_with_retry(url: str, cache: TTLCache, use_cache: bool = True) -> httpx.Response:
    if use_cache and url in cache:
        logger.debug(f"Взят из кеша: {url}")  # Изменено с INFO на DEBUG
        return cache[url]

    client = get_http_client()
    last_exception = None
    for attempt in range(3):
        try:
            # httpx автоматически следует за редиректами с follow_redirects=True
            response = await client.get(url)
            response.raise_for_status()
            if use_cache:
                cache[url] = response
            logger.debug(f"Успешный запрос (попытка {attempt + 1}): {url}")  # Изменено с INFO на DEBUG
            return response
        except httpx.HTTPStatusError as e:
            # Если это редирект, но мы все равно получили ошибку, пробуем следовать вручную
            if e.response.status_code in (301, 302, 303, 307, 308):
                redirect_url = e.response.headers.get("Location")
                if redirect_url:
                    # Если относительный URL, делаем его абсолютным
                    if redirect_url.startswith("/"):
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
                    logger.debug(f"Следую за редиректом {e.response.status_code}: {url} -> {redirect_url}")  # Изменено с INFO на DEBUG
                    try:
                        # Повторяем запрос по новому URL
                        response = await client.get(redirect_url)
                        response.raise_for_status()
                        if use_cache:
                            cache[url] = response
                        logger.debug(f"Успешный запрос после редиректа: {redirect_url}")  # Изменено с INFO на DEBUG
                        return response
                    except Exception as redirect_error:
                        logger.warning(f"Ошибка после редиректа: {redirect_error}")
                        last_exception = redirect_error
                else:
                    last_exception = e
            else:
                last_exception = e
            if attempt < 2:
                logger.warning(f"Ошибка запроса (попытка {attempt + 1}): {e}. Повтор через {2 ** attempt} сек.")
                await asyncio.sleep(2 ** attempt)
        except (httpx.RequestError, httpx.ConnectError, httpx.ConnectTimeout) as e:
            last_exception = e
            if attempt < 2:
                logger.warning(f"Ошибка запроса (попытка {attempt + 1}): {e}. Повтор через {2 ** attempt} сек.")
                await asyncio.sleep(2 ** attempt)
            else:
                logger.warning(f"Не удалось выполнить запрос после {attempt + 1} попыток: {e}")
    if last_exception:
        raise last_exception
    raise RuntimeError("Неизвестная ошибка при выполнении запроса")


