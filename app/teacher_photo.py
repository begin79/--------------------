"""
Модуль для получения фотографий и профилей преподавателей
"""
import logging
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from requests.utils import quote

from .config import BASE_URL_VGLTU
from .http import make_request_with_retry
from cachetools import TTLCache

logger = logging.getLogger(__name__)

teacher_photo_cache = TTLCache(maxsize=200, ttl=86400)  # 24 часа
teacher_profile_cache = TTLCache(maxsize=200, ttl=86400)  # 24 часа

async def get_teacher_profile_url(teacher_name: str) -> Optional[str]:
    """
    Ищет URL профиля преподавателя на сайте vgltu.ru

    Args:
        teacher_name: Имя преподавателя в формате "Фамилия И.О."

    Returns:
        URL профиля или None если не найдено
    """
    if not teacher_name or teacher_name == "-":
        return None

    cache_key = f"profile_{teacher_name.lower().strip()}"
    if cache_key in teacher_profile_cache:
        cached_url = teacher_profile_cache[cache_key]
        return cached_url if cached_url else None

    try:
        # Пробуем найти через раздел сотрудников
        employees_url = f"{BASE_URL_VGLTU}/sveden/employees/"
        temp_cache = TTLCache(maxsize=10, ttl=3600)
        response = await make_request_with_retry(employees_url, temp_cache, use_cache=True)
        soup = BeautifulSoup(response.text, "html.parser")

        # Ищем ссылки с именем преподавателя
        links = soup.find_all("a", href=True)
        surname = teacher_name.split()[0] if teacher_name.split() else ""
        name_parts = teacher_name.split()

        for link in links:
            link_text = link.get_text(strip=True)
            # Проверяем совпадение по фамилии и инициалам
            if surname.lower() in link_text.lower():
                # Дополнительная проверка на совпадение инициалов
                if len(name_parts) > 1:
                    initials = "".join([part[0].upper() for part in name_parts[1:] if part])
                    if initials and initials in link_text:
                        href = link.get("href", "")
                        if href.startswith("/"):
                            page_url = f"{BASE_URL_VGLTU}{href}"
                        elif href.startswith("http"):
                            page_url = href
                        else:
                            continue

                        teacher_profile_cache[cache_key] = page_url
                        logger.info(f"Найден профиль преподавателя {teacher_name}: {page_url}")
                        return page_url
                else:
                    # Если только фамилия, проверяем более тщательно
                    href = link.get("href", "")
                    if href.startswith("/") and "employee" in href.lower():
                        page_url = f"{BASE_URL_VGLTU}{href}"
                        teacher_profile_cache[cache_key] = page_url
                        logger.info(f"Найден профиль преподавателя {teacher_name}: {page_url}")
                        return page_url

        # Пробуем через поиск
        search_url = f"{BASE_URL_VGLTU}/search/?q={quote(teacher_name)}"
        response = await make_request_with_retry(search_url, temp_cache, use_cache=True)
        soup = BeautifulSoup(response.text, "html.parser")

        # Ищем ссылки на профили
        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            link_text = link.get_text(strip=True)
            if surname.lower() in link_text.lower() and ("employee" in href.lower() or "staff" in href.lower() or "преподаватель" in link_text.lower()):
                if href.startswith("/"):
                    page_url = f"{BASE_URL_VGLTU}{href}"
                elif href.startswith("http"):
                    page_url = href
                else:
                    continue

                teacher_profile_cache[cache_key] = page_url
                logger.info(f"Найден профиль преподавателя {teacher_name} через поиск: {page_url}")
                return page_url

    except Exception as e:
        logger.warning(f"Ошибка при поиске профиля преподавателя {teacher_name}: {e}")

    teacher_profile_cache[cache_key] = None
    return None

async def get_teacher_photo_url(teacher_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Ищет URL фотографии и профиля преподавателя на сайте vgltu.ru

    Args:
        teacher_name: Имя преподавателя в формате "Фамилия И.О."

    Returns:
        Tuple[photo_url, profile_url] или (None, None) если не найдено
    """
    if not teacher_name or teacher_name == "-":
        return None, None

    cache_key = teacher_name.lower().strip()

    # Проверяем кеш
    if cache_key in teacher_photo_cache:
        cached_photo = teacher_photo_cache[cache_key]
        cached_profile = teacher_profile_cache.get(f"profile_{cache_key}")
        return (cached_photo if cached_photo else None), (cached_profile if cached_profile else None)

    photo_url = None
    profile_url = None

    # Сначала пытаемся найти профиль
    profile_url = await get_teacher_profile_url(teacher_name)

    # Если нашли профиль, пытаемся найти фото на странице профиля
    if profile_url:
        try:
            temp_cache = TTLCache(maxsize=10, ttl=3600)
            page_response = await make_request_with_retry(profile_url, temp_cache, use_cache=True)
            page_soup = BeautifulSoup(page_response.text, "html.parser")

            # Ищем фото на странице
            photos = page_soup.find_all("img")
            for photo in photos:
                src = photo.get("src", "")
                if any(keyword in src.lower() for keyword in [".jpg", ".jpeg", ".png"]):
                    if src.startswith("/"):
                        photo_url = f"{BASE_URL_VGLTU}{src}"
                    elif src.startswith("http"):
                        photo_url = src
                    else:
                        continue

                    # Пропускаем маленькие иконки и логотипы
                    if "icon" not in src.lower() and "logo" not in src.lower() and "avatar" not in src.lower():
                        # Проверяем размер изображения через атрибуты
                        width = photo.get("width", "")
                        height = photo.get("height", "")
                        if width and height:
                            try:
                                w, h = int(width), int(height)
                                if w > 100 and h > 100:  # Минимальный размер
                                    teacher_photo_cache[cache_key] = photo_url
                                    logger.info(f"Найдена фотография преподавателя {teacher_name} на странице профиля: {photo_url}")
                                    return photo_url, profile_url
                            except:
                                pass
                        else:
                            # Если размеров нет, но это не иконка - сохраняем
                            teacher_photo_cache[cache_key] = photo_url
                            logger.info(f"Найдена фотография преподавателя {teacher_name} на странице профиля: {photo_url}")
                            return photo_url, profile_url
        except Exception as e:
            logger.debug(f"Ошибка при загрузке страницы профиля преподавателя {teacher_name}: {e}")

    # Если не нашли через профиль, пробуем через поиск
    try:
        search_url = f"{BASE_URL_VGLTU}/search/?q={quote(teacher_name)}"
        temp_cache = TTLCache(maxsize=10, ttl=3600)
        response = await make_request_with_retry(search_url, temp_cache, use_cache=True)
        soup = BeautifulSoup(response.text, "html.parser")

        # Ищем изображения на странице
        images = soup.find_all("img")
        for img in images:
            src = img.get("src", "")
            alt = img.get("alt", "").lower()

            # Проверяем, что это фотография преподавателя
            if teacher_name.lower() in alt or any(word.lower() in alt for word in teacher_name.split()[:2]):
                if src.startswith("/"):
                    full_url = f"{BASE_URL_VGLTU}{src}"
                elif src.startswith("http"):
                    full_url = src
                else:
                    continue

                # Проверяем, что это действительно фото (не иконка)
                if any(keyword in src.lower() for keyword in [".jpg", ".jpeg", ".png"]) and "icon" not in src.lower() and "logo" not in src.lower():
                    photo_url = full_url
                    teacher_photo_cache[cache_key] = photo_url
                    logger.info(f"Найдена фотография преподавателя {teacher_name}: {photo_url}")
                    return photo_url, profile_url
    except Exception as e:
        logger.warning(f"Ошибка при поиске фотографии преподавателя {teacher_name}: {e}")

    # Если ничего не нашли, кешируем None
    teacher_photo_cache[cache_key] = None
    return None, profile_url
