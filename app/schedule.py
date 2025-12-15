import re
import logging
import datetime
from typing import List, Tuple, Optional, Literal, Dict
from bs4 import BeautifulSoup
from urllib.parse import quote
from cachetools import TTLCache

from .config import BASE_URL_SCHEDULE, BASE_URL_LIST
from .constants import (
    API_TYPE_GROUP,
    API_TYPE_TEACHER,
    GROUP_NAME_PATTERN,
    SUBGROUP_PATTERN,
    PAIR_EMOJIS,
)
from .http import make_request_with_retry

logger = logging.getLogger(__name__)

# Увеличенные размеры кешей для работы с большим количеством пользователей
schedule_cache = TTLCache(maxsize=500, ttl=600)  # Увеличено с 100 до 500
list_cache = TTLCache(maxsize=50, ttl=3600)  # Увеличено с 10 до 50

def parse_date_from_html(day_date_str: str) -> Optional[datetime.date]:
    """
    Парсит дату из строки HTML (например, "03.11.2025", "11 ноября 2025" или "Понедельник, 03.11.2025")
    Возвращает объект date или None, если не удалось распарсить
    """
    if not day_date_str:
        return None

    try:
        # Пытаемся найти дату в формате DD.MM.YYYY
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', day_date_str)
        if date_match:
            day, month, year = map(int, date_match.groups())
            result = datetime.date(year, month, day)
            logger.debug(f"Распарсена дата из '{day_date_str}': {result}")
            return result

        # Пытаемся найти дату в русском формате "11 ноября 2025"
        months_ru = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
            'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
        }

        # Ищем паттерн: число + название месяца + год
        date_match_ru = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', day_date_str.lower())
        if date_match_ru:
            day = int(date_match_ru.group(1))
            month_name = date_match_ru.group(2)
            year = int(date_match_ru.group(3))

            if month_name in months_ru:
                month = months_ru[month_name]
                result = datetime.date(year, month, day)
                logger.debug(f"Распарсена дата из '{day_date_str}': {result}")
                return result

        logger.warning(f"Не удалось найти дату в формате DD.MM.YYYY или 'DD месяца YYYY' в строке: '{day_date_str}'")
    except Exception as e:
        logger.warning(f"Ошибка при парсинге даты из '{day_date_str}': {e}")
    return None

async def get_schedule(date_str: str, query_value: str, entity_type: Literal["Group", "Teacher"], use_cache: bool = True) -> Tuple[Optional[List[str]], Optional[str]]:
    if entity_type == API_TYPE_TEACHER:
        url = f"{BASE_URL_SCHEDULE}?teacher={quote(query_value)}&date={date_str}"
        not_found_msg = f"Расписание не найдено для преподавателя '{query_value}' на {date_str} 🫤"
    elif entity_type == API_TYPE_GROUP:
        url = f"{BASE_URL_SCHEDULE}?date={date_str}&group={query_value}"
        not_found_msg = f"Расписание не найдено для группы '{query_value}' на {date_str} 🫤"
    else:
        return None, "Внутренняя ошибка."

    try:
        response = await make_request_with_retry(url, schedule_cache, use_cache=use_cache)
    except Exception as e:
        return None, f"😔 Не удалось загрузить расписание. Попробуйте позже.\n\n💡 Возможные причины:\n• Сайт ВГЛТУ временно недоступен\n• Проблемы с интернет-соединением"

    soup = BeautifulSoup(response.text, "lxml")
    # Ищем div с расписанием
    days_html = find_schedule_divs(soup)
    if not days_html:
        return [not_found_msg], None

    # УБИРАЕМ СТРОГУЮ ФИЛЬТРАЦИЮ ПО ДАТЕ - обрабатываем все дни, которые вернул API
    # Это позволяет создавать несколько страниц для листания

    pages: List[str] = []
    for day_div in days_html:
        try:
            date_header = day_div.find("strong")
            day_date_str = date_header.text.strip() if date_header else "Неизвестная дата"

            # УБИРАЕМ СТРОГУЮ ФИЛЬТРАЦИЮ ПО ДАТЕ - обрабатываем все дни, которые вернул API
            # Это позволяет создавать несколько страниц для листания
            # Если запрошена конкретная дата, API все равно может вернуть несколько дней

            weekday_divs = day_div.find_all("div")
            weekday = weekday_divs[1].text.strip() if len(weekday_divs) > 1 else ""
            pairs_html = day_div.find_all("tr")

            # Пропускаем дни без пар
            if not pairs_html:
                continue

            # Проверяем, есть ли реальные пары (не пустые строки)
            has_real_pairs = False
            for pair_tr in pairs_html:
                try:
                    tds = pair_tr.find_all("td")
                    if tds:
                        # Проверяем, есть ли содержимое в ячейках
                        content = "".join([td.text.strip() if td.text else "" for td in tds])
                        if content and content.strip():
                            has_real_pairs = True
                            break
                except Exception:
                    # Пропускаем проблемные строки
                    continue

            # Пропускаем дни без реальных пар
            if not has_real_pairs:
                continue

            day_text = f"<b>{day_date_str} ({weekday})</b>:\n\n"
            last_time_value = ""
            last_counted_time = ""
            pair_counter = 0

            for pair_tr in pairs_html:
                try:
                    tds = pair_tr.find_all("td")
                    if not tds:
                        continue

                    if len(tds) == 1:
                        time = last_time_value or "-"
                        content_td = tds[0]
                        extra_td = None
                    else:
                        time_candidate = tds[0].text.strip() if len(tds) > 0 else ""
                        if time_candidate:
                            last_time_value = time_candidate
                        time = last_time_value or time_candidate or "-"
                        content_td = tds[1] if len(tds) > 1 else tds[0]
                        extra_td = tds[2] if len(tds) > 2 else None

                    if time and time != last_counted_time:
                        pair_counter += 1
                        last_counted_time = time

                    try:
                        details_lines = [line.strip() for line in content_td.text.strip().split("\n") if line.strip()]
                        subject = re.sub(SUBGROUP_PATTERN, r"\1 \2", details_lines[0] if details_lines else "-")
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке предмета: {e}")
                        subject = "-"

                    auditorium_link = "-"
                    try:
                        auditorium_a = pair_tr.find("a", href=lambda href: href and "map/rasp?auditory=" in href)
                        if auditorium_a and auditorium_a.has_attr('href'):
                            href = auditorium_a['href']
                            full_href = f"https://vgltu.ru{href}" if not href.startswith('http') else href
                            auditorium_link = f'<a href="{full_href}">{auditorium_a.text.strip()}</a>'
                        elif extra_td is not None and extra_td.text.strip():
                            text = extra_td.text.strip()
                            auditorium_link = f'<a href="https://vgltu.ru/map/rasp?auditory={quote(text)}">{text}</a>'
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке аудитории: {e}")

                    try:
                        groups = [p.strip() for p in content_td.decode_contents().split("<br/>") if re.fullmatch(GROUP_NAME_PATTERN, p.strip())]
                        group_names = ", ".join(groups) if groups else "-"
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке групп: {e}")
                        group_names = "-"

                    idx = pair_counter - 1
                    pair_emoji = PAIR_EMOJIS[idx] if 0 <= idx < len(PAIR_EMOJIS) else f" {idx+1}."
                    pair_info = f"{pair_emoji} <b>{time}</b>\n  📖 {subject}\n  📍 {auditorium_link}\n"

                    if entity_type == API_TYPE_GROUP and len(details_lines) > 1:
                        try:
                            last_line = details_lines[-1]
                            if last_line != subject and not re.fullmatch(GROUP_NAME_PATTERN, last_line):
                                pair_info += f"  👤 {last_line}\n"
                        except Exception as e:
                            logger.warning(f"Ошибка при обработке преподавателя: {e}")
                    if group_names != "-":
                        pair_info += f"  👥 {group_names}\n"

                    day_text += pair_info + "\n——————————————————————\n"
                except Exception as e:
                    logger.error(f"Ошибка при обработке пары: {e}", exc_info=True)
                    continue

            # Убираем последний разделитель, если он есть (совместимость с Python < 3.9)
            day_text_cleaned = day_text.strip()
            if day_text_cleaned.endswith("——————————————————————"):
                day_text_cleaned = day_text_cleaned[:-len("——————————————————————")].strip()
            pages.append(day_text_cleaned)
        except Exception as e:
            logger.error(f"Ошибка при обработке дня: {e}", exc_info=True)
            # Добавляем сообщение об ошибке, но продолжаем обработку других дней
            pages.append(f"<b>Ошибка при обработке расписания</b>\n\nНе удалось обработать день: {str(e)}")

    # Если все дни были пропущены (нет дней с парами), возвращаем сообщение
    if not pages:
        return [not_found_msg], None

    return pages, None

def find_schedule_divs(soup: BeautifulSoup) -> List:
    """
    Находит div-блоки с расписанием на странице.
    Использует несколько стратегий поиска для надежности.
    """
    # Стратегия 1: Поиск по стилю (оригинальный метод)
    days_html = soup.find_all("div", style=lambda x: x and "margin-bottom: 25px" in x)
    if days_html:
        return days_html

    # Стратегия 2: Поиск по структуре (div > strong с датой)
    # Ищем div, который содержит strong, текст которого похож на дату
    candidates = []
    for div in soup.find_all("div"):
        strong = div.find("strong", recursive=False)
        if strong:
            text = strong.text.strip()
            # Простая проверка: содержит цифры и точки или название месяца
            if re.search(r'\d{2}\.\d{2}\.\d{4}', text) or \
               re.search(r'\d+\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)', text.lower()):
                candidates.append(div)

    if candidates:
        logger.debug(f"Найдено {len(candidates)} дней по альтернативной стратегии (strong tag)")
        return candidates

    return []

async def get_schedule_structured(date_str: str, query_value: str, entity_type: Literal["Group", "Teacher"]) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Получить структурированное расписание (для экспорта)
    ВАЖНО: Проверяет, что дата из HTML соответствует запрошенной дате,
    чтобы избежать привязки пар к неправильным дням.

    Returns:
        Dict с ключами:
        - date: дата
        - weekday: день недели
        - pairs: List[Dict] где каждый Dict содержит time, subject, groups, auditorium, teacher
    """
    if entity_type == API_TYPE_TEACHER:
        url = f"{BASE_URL_SCHEDULE}?teacher={quote(query_value)}&date={date_str}"
    elif entity_type == API_TYPE_GROUP:
        url = f"{BASE_URL_SCHEDULE}?date={date_str}&group={query_value}"
    else:
        return None, "Внутренняя ошибка."

    try:
        response = await make_request_with_retry(url, schedule_cache, use_cache=True)
    except Exception as e:
        return None, "😔 Не удалось загрузить расписание. Попробуйте позже."

    soup = BeautifulSoup(response.text, "lxml")

    # Ищем div с расписанием
    days_html = find_schedule_divs(soup)
    if not days_html:
        logger.warning(f"Для {date_str} не найдено div с расписанием в HTML")
        return None, "Расписание не найдено"

    # Парсим запрошенную дату для сравнения
    try:
        requested_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None, f"Неверный формат даты: {date_str}"

    logger.debug(f"🔍 Ищем расписание для даты {date_str} ({requested_date}), найдено {len(days_html)} дней в HTML")

    # Ищем день с правильной датой (API может вернуть несколько дней)
    day_div = None
    day_date_str = None
    weekday = ""

    candidate_by_day = None
    candidate_by_weekday = None

    for div in days_html:
        date_header = div.find("strong")
        if not date_header:
            continue

        html_date_str = date_header.text.strip()
        html_date = parse_date_from_html(html_date_str)

        # Если дата совпадает с запрошенной, используем этот день
        if html_date and html_date == requested_date:
            day_div = div
            day_date_str = html_date_str
            weekday_divs = div.find_all("div")
            weekday = weekday_divs[1].text.strip() if len(weekday_divs) > 1 else ""
            logger.debug(f"✅ Найден день с совпадающей датой: {html_date_str}")
            break
        elif html_date and html_date.day == requested_date.day and html_date.month == requested_date.month and not candidate_by_day:
            candidate_by_day = (div, html_date_str)
        elif html_date and html_date.weekday() == requested_date.weekday() and not candidate_by_weekday:
            candidate_by_weekday = (div, html_date_str)

    # Если не нашли точное совпадение даты, пробуем найти по дню недели
    if day_div is None:
        if candidate_by_day:
            logger.debug(f"✅ Используем день с совпадающим числом месяца: {candidate_by_day[1]}")
            day_div = candidate_by_day[0]
            day_date_str = candidate_by_day[1]
            weekday_divs = day_div.find_all("div")
            weekday = weekday_divs[1].text.strip() if len(weekday_divs) > 1 else ""
        elif candidate_by_weekday:
            logger.debug(f"✅ Используем день с совпадающим днём недели: {candidate_by_weekday[1]}")
            day_div = candidate_by_weekday[0]
            day_date_str = candidate_by_weekday[1]
            weekday_divs = day_div.find_all("div")
            weekday = weekday_divs[1].text.strip() if len(weekday_divs) > 1 else ""
        elif len(days_html) == 1:
            logger.debug(f"⚠️ Используем единственный день из ответа: {date_str}")
            day_div = days_html[0]
            date_header = day_div.find("strong")
            day_date_str = date_header.text.strip() if date_header else "Неизвестная дата"
            weekday_divs = day_div.find_all("div")
            weekday = weekday_divs[1].text.strip() if len(weekday_divs) > 1 else ""
        else:
            logger.debug(f"⚠️ Не найден подходящий день для {date_str}. Возвращаем пустое расписание.")
            return None, None

    pairs = []
    pairs_html = day_div.find_all("tr")

    # УПРОЩЕННАЯ ПРОВЕРКА: если есть строки в таблице, обрабатываем их
    # Проверку на "Нет пар" делаем позже, при парсинге конкретных пар
    if not pairs_html:
        logger.info(f"Для даты {date_str} нет строк <tr> в таблице")
        return None, None

    logger.debug(f"Для даты {date_str} найдено {len(pairs_html)} строк <tr> в таблице")

    # УБИРАЕМ ПРЕДВАРИТЕЛЬНУЮ ПРОВЕРКУ - просто обрабатываем все строки
    # Проверку на "Нет пар" сделаем при парсинге конкретных пар

    last_time_value = ""

    for pair_tr in pairs_html:
        tds = pair_tr.find_all("td")
        if not tds:
            continue

        if len(tds) == 1:
            time = last_time_value or "-"
            content_td = tds[0]
            extra_td = None
        else:
            time_candidate = tds[0].text.strip()
            if time_candidate:
                last_time_value = time_candidate
            time = last_time_value or time_candidate or "-"
            content_td = tds[1]
            extra_td = tds[2] if len(tds) > 2 else None

        details_lines = [line.strip() for line in content_td.text.strip().split("\n") if line.strip()]
        subject = re.sub(SUBGROUP_PATTERN, r"\1 \2", details_lines[0] if details_lines else "-")

        # Проверяем, что это не строка "Нет пар"
        row_text_full = "".join([td.text.strip() if td.text else "" for td in tds]).lower().strip()
        if row_text_full in ["нет пар", "нет занятий", "занятий нет"]:
            logger.debug(f"Пропускаем строку 'Нет пар' для {date_str}")
            continue

        # Пропускаем только если предмет явно "Нет пар" и нет времени
        if not time or time == '-':
            if subject and subject.lower().strip() in ["нет пар", "нет занятий", "занятий нет"]:
                logger.debug(f"Пропускаем пару 'Нет пар' без времени для {date_str}")
                continue

        auditorium = "-"
        auditorium_a = pair_tr.find("a", href=lambda href: href and "map/rasp?auditory=" in href)
        if auditorium_a:
            auditorium = auditorium_a.text.strip()
        elif extra_td is not None and extra_td.text.strip():
            auditorium = extra_td.text.strip()

        groups = [p.strip() for p in content_td.decode_contents().split("<br/>") if re.fullmatch(GROUP_NAME_PATTERN, p.strip())]

        teacher = ""
        if entity_type == API_TYPE_GROUP and len(details_lines) > 1:
            last_line = details_lines[-1]
            if last_line != subject and not re.fullmatch(GROUP_NAME_PATTERN, last_line):
                teacher = last_line

        pairs.append({
            "time": time,
            "subject": subject,
            "groups": groups,
            "auditorium": auditorium,
            "teacher": teacher,
        })

    # Если после парсинга нет пар, возвращаем None
    if not pairs:
        logger.info(f"Для даты {date_str} после парсинга нет пар (обработано {len(pairs_html)} строк)")
        return None, None

    logger.debug(f"✅ Для даты {date_str} успешно распарсено {len(pairs)} пар")

    parsed_day_date = parse_date_from_html(day_date_str) if day_date_str else None
    date_iso = parsed_day_date.isoformat() if parsed_day_date else requested_date.isoformat()

    return {
        "date": day_date_str,
        "date_iso": date_iso,
        "weekday": weekday,
        "pairs": pairs
    }, None

async def search_entities(query: str, entity_type: Literal["Group", "Teacher"]) -> Tuple[Optional[List[str]], Optional[str]]:
    url = f"{BASE_URL_LIST}?type={entity_type}"
    try:
        response = await make_request_with_retry(url, list_cache)

        # Проверяем Content-Type заголовка, но не прерываем выполнение, если он не json
        content_type = response.headers.get('Content-Type', '') or ''
        content_type_lower = content_type.lower()
        is_json_content_type = 'application/json' in content_type_lower or 'text/json' in content_type_lower

        # Пытаемся получить JSON вне зависимости от заголовка
        try:
            entities = response.json()
        except ValueError as e:
            logger.error(
                f"Ошибка парсинга JSON: {e}, content-type: '{content_type}', response text: {response.text[:200]}"
            )
            return None, "Ошибка: Сервер вернул данные в неожиданном формате."

        # Если заголовок неожиданный, но JSON успешно распаршен, логируем на уровне INFO без прерывания
        if not is_json_content_type:
            logger.info(f"Неожиданный Content-Type (но JSON получен): '{content_type}'")

        # Проверяем тип данных
        if not isinstance(entities, list):
            logger.error(f"Ожидался list, получен {type(entities)}: {entities}")
            return None, "Ошибка: Сервер вернул данные в неожиданном формате."

        # Проверяем, что все элементы - строки
        if not all(isinstance(item, str) for item in entities):
            logger.error("Не все элементы списка являются строками")
            return None, "Ошибка: Сервер вернул данные в неожиданном формате."

        # Фильтруем результаты
        filtered = [e for e in entities if query.lower() in e.lower()]
        return filtered if filtered else None, None
    except Exception as e:
        logger.error(f"Ошибка при поиске сущностей: {e}", exc_info=True)
        return None, f"Сетевая ошибка: {str(e)}"


