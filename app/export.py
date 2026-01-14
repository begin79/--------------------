"""
Модуль для экспорта расписания в различных форматах
"""
import datetime
import logging
from typing import Dict, List, Optional
from io import BytesIO

from .schedule import get_schedule_structured
from .constants import API_TYPE_TEACHER

logger = logging.getLogger(__name__)

# Пути к ресурсам (используем из config для единообразия)
from .config import FONTS_DIR, ASSETS_DIR
# Поддерживаем разные форматы логотипа
LOGO_PATH = None
for logo_name in ["лого.jpg", "лого.png", "logo.jpg", "logo.png"]:
    logo_path = ASSETS_DIR / logo_name
    if logo_path.exists():
        LOGO_PATH = logo_path
        break
FONTS_PATH = FONTS_DIR
DEFAULT_FONT_PATH = FONTS_PATH / "DejaVuSans.ttf"
DEFAULT_FONT_BOLD_PATH = FONTS_PATH / "DejaVuSans-Bold.ttf"

async def get_week_schedule_structured(entity_name: str, entity_type: str, start_date: Optional[datetime.date] = None, week_offset: int = 0) -> Dict[str, List[Dict]]:
    """
    Получить структурированное расписание на неделю (пн-сб, без воскресенья)
    Возвращает только дни, в которых есть пары.

    Args:
        entity_name: Имя группы или преподавателя
        entity_type: API_TYPE_GROUP или API_TYPE_TEACHER
        start_date: Начальная дата (по умолчанию сегодня)
        week_offset: Смещение недели (0 = текущая неделя, 1 = следующая неделя)

    Returns:
        Dict[date_str, List[pair_dict]] где pair_dict содержит:
        - time: время (например "08:30-10:00")
        - subject: предмет
        - groups: список групп
        - auditorium: аудитория
        - teacher: преподаватель (если есть)
    """
    if start_date is None:
        start_date = datetime.date.today()

    # Логика определения недели:
    # - Если сегодня понедельник-суббота: берем текущую неделю
    # - Если сегодня воскресенье: берем следующую неделю (текущая уже прошла)
    days_since_monday = start_date.weekday()
    if days_since_monday == 6:  # Воскресенье
        # Берем следующую неделю
        monday = start_date + datetime.timedelta(days=1)
    else:
        # Берем понедельник текущей недели
        monday = start_date - datetime.timedelta(days=days_since_monday)

    # Применяем смещение недели
    if week_offset > 0:
        monday = monday + datetime.timedelta(days=7 * week_offset)

    week_schedule = {}

    # Только рабочие дни: понедельник - суббота (0-5)
    for day_offset in range(6):
        current_date = monday + datetime.timedelta(days=day_offset)
        date_str = current_date.strftime("%Y-%m-%d")

        structured, err = await get_schedule_structured(date_str, entity_name, entity_type)

        # Если есть ошибка (не None, None), пропускаем этот день
        if err:
            logger.warning(f"Ошибка получения расписания для {date_str}: {err}")
            continue

        # Если structured is None, значит для этого дня нет расписания (нет пар)
        if not structured:
            logger.debug(f"Для {date_str} нет расписания (get_schedule_structured вернул None)")
            continue

        pairs = structured.get("pairs", [])
        logger.debug(f"Для {date_str} получено {len(pairs)} пар из get_schedule_structured")

        # УПРОЩЕННАЯ ЛОГИКА: берем все пары, которые вернул get_schedule_structured
        # Фильтрация уже сделана в get_schedule_structured, здесь просто используем результат
        actual_date_key = structured.get("date_iso") if structured else None
        actual_date_key = actual_date_key or date_str

        # Добавляем день, если есть пары
        if pairs:
            if actual_date_key in week_schedule and week_schedule[actual_date_key] != pairs:
                logger.warning(
                    f"⚠️ Переопределяем расписание для {actual_date_key}: ранее было {len(week_schedule[actual_date_key])} пар, "
                    f"теперь {len(pairs)}."
                )
            week_schedule[actual_date_key] = pairs
            logger.debug(f"✅ Для {actual_date_key} добавлено {len(pairs)} пар в week_schedule")

    logger.debug(f"📊 Итого в week_schedule: {len(week_schedule)} дней с парами")
    if week_schedule:
        for date_str, pairs in week_schedule.items():
            logger.debug(f"  - {date_str}: {len(pairs)} пар")

    return week_schedule

async def get_day_schedule_structured(entity_name: str, entity_type: str, date: datetime.date) -> Optional[Dict]:
    """Получить структурированное расписание на один день"""
    date_str = date.strftime("%Y-%m-%d")
    structured, err = await get_schedule_structured(date_str, entity_name, entity_type)
    if err or not structured:
        return None
    return structured

def format_week_schedule_text(week_schedule: Dict[str, List[Dict]], entity_name: str, entity_type: str) -> str:
    """Форматирует расписание на неделю в текстовую таблицу"""
    from .utils import escape_html, get_pair_type_emoji
    weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]

    entity_label = "преподавателя" if entity_type == API_TYPE_TEACHER else "группы"
    lines = [f"📅 <b>Расписание на неделю для {entity_label}: {escape_html(entity_name)}</b>\n"]
    lines.append("=" * 60)

    # Пропускаем воскресенье - только рабочие дни (пн-сб)
    for date_str in sorted(week_schedule.keys()):
        pairs = week_schedule[date_str]
        if not pairs:  # Пропускаем дни без пар
            continue

        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        # Проверяем, что это не воскресенье (6)
        if date_obj.weekday() >= 6:
            continue

        weekday_name = weekdays[date_obj.weekday()]
        date_formatted = date_obj.strftime("%d.%m.%Y")

        lines.append(f"\n<b>{weekday_name}, {date_formatted}</b>")
        lines.append("-" * 40)

        for pair in pairs:
            time = pair.get("time", "-")
            subject = escape_html(pair.get("subject", "-"))
            groups = ", ".join(pair.get("groups", []))
            auditorium = escape_html(pair.get("auditorium", "-"))
            teacher = escape_html(pair.get("teacher", ""))
            subject_emoji = get_pair_type_emoji(subject)

            lines.append(f"\n⏰ <b>{time}</b>")
            lines.append(f"{subject_emoji} {subject}")
            if groups:
                lines.append(f"👥 Группы: {groups}")
            if auditorium and auditorium != "-":
                lines.append(f"📍 Аудитория: {auditorium}")
            if teacher:
                lines.append(f"👤 Преподаватель: {teacher}")
            lines.append("")

    return "\n".join(lines)

async def generate_schedule_image(week_schedule: Dict[str, List[Dict]], entity_name: str, entity_type: str, font_size: int = 22) -> Optional[BytesIO]:
    """
    Генерирует изображение с расписанием на неделю в виде двух колонок:
    Левая колонка: Понедельник, Вторник, Среда (вертикально)
    Правая колонка: Четверг, Пятница, Суббота (вертикально)
    Текст не сокращается, используется только перенос строк.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("PIL/Pillow не установлен, генерация изображений недоступна")
        return None

    try:
        # --- Улучшенная функция для переноса текста ---
        def wrap_text(text, font, max_width):
            """Переносит текст по словам, не сокращая его. Если слово слишком длинное, переносит по символам."""
            if not text or not text.strip():
                line_height = font.getbbox('A')[3] + 6 if text else 0
                return [""] if text else [], line_height

            def get_text_width(txt):
                """Получить ширину текста в пикселях"""
                if not txt:
                    return 0
                try:
                    bbox = font.getbbox(txt)
                    return bbox[2] - bbox[0]
                except Exception:
                    return len(txt) * 10  # Fallback

            lines = []
            words = text.split(' ')

            # Убираем пустые слова
            words = [w for w in words if w]

            if not words:
                return [text], font.getbbox('A')[3] + 6

            current_line = words[0]

            for word in words[1:]:
                # Пробуем добавить слово к текущей строке
                test_line = current_line + ' ' + word if current_line else word
                test_width = get_text_width(test_line)

                if test_width <= max_width:
                    # Помещается
                    current_line = test_line
                else:
                    # Не помещается - сохраняем текущую строку
                    if current_line:
                        # Проверяем длину текущей строки
                        if get_text_width(current_line) > max_width:
                            # Текущая строка слишком длинная, разбиваем по символам
                            chars = list(current_line)
                            temp_line = ""
                            for char in chars:
                                test_char = (temp_line + char) if temp_line else char
                                if get_text_width(test_char) <= max_width:
                                    temp_line = test_char
                                else:
                                    if temp_line:
                                        lines.append(temp_line)
                                    temp_line = char
                            current_line = temp_line if temp_line else ""
                        else:
                            lines.append(current_line)
                            current_line = ""

                    # Обрабатываем новое слово
                    word_width = get_text_width(word)
                    if word_width > max_width:
                        # Слово слишком длинное, разбиваем по символам
                        chars = list(word)
                        temp_word = ""
                        for char in chars:
                            test_char = (temp_word + char) if temp_word else char
                            if get_text_width(test_char) <= max_width:
                                temp_word = test_char
                            else:
                                if temp_word:
                                    if current_line:
                                        lines.append(current_line)
                                    current_line = temp_word
                                    temp_word = char
                                else:
                                    if current_line:
                                        lines.append(current_line)
                                    current_line = char
                                    temp_word = ""
                        if temp_word:
                            if current_line:
                                lines.append(current_line)
                            current_line = temp_word
                    else:
                        # Слово нормальной длины
                        current_line = word

            # Добавляем последнюю строку
            if current_line:
                if get_text_width(current_line) > max_width:
                    # Разбиваем по символам
                    chars = list(current_line)
                    temp_line = ""
                    for char in chars:
                        test_char = (temp_line + char) if temp_line else char
                        if get_text_width(test_char) <= max_width:
                            temp_line = test_char
                        else:
                            if temp_line:
                                lines.append(temp_line)
                            temp_line = char
                    if temp_line:
                        lines.append(temp_line)
                else:
                    lines.append(current_line)

            # Высота строки с интервалом
            try:
                line_height = font.getbbox('A')[3] + 6
            except Exception:
                line_height = 20
            total_height = len(lines) * line_height if lines else line_height
            return lines, total_height

        # --- Дизайн, Шрифты и Макет ---
        BG_COLOR, CARD_COLOR, TEXT_COLOR = '#F5F5F5', '#FFFFFF', '#000000'
        DAY_HEADER_BG, DAY_HEADER_TEXT = '#e8f5e9', '#006400'

        # Новый макет: 2 колонки вместо 3x2
        NUM_COLUMNS = 2

        try:
            # Увеличиваем размеры шрифтов для лучшей читаемости
            title_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), 48)
            name_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), 40)
            day_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), 42)
            content_font = ImageFont.truetype(str(DEFAULT_FONT_PATH), 36)
            time_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), 34)
            info_font = ImageFont.truetype(str(DEFAULT_FONT_PATH), 32)  # Для групп, аудитории, преподавателя
        except Exception:
            logger.warning("Не удалось загрузить кастомные шрифты.")
            title_font = ImageFont.load_default()
            name_font = ImageFont.load_default()
            day_font = ImageFont.load_default()
            content_font = ImageFont.load_default()
            time_font = ImageFont.load_default()
            info_font = ImageFont.load_default()

        # Параметры макета: две колонки с достаточной шириной
        # Увеличиваем ширину для лучшей читаемости с увеличенными шрифтами
        width = 2800  # Оптимальная ширина для увеличенных шрифтов
        padding = 60
        column_spacing = 50  # Расстояние между колонками
        card_padding = 50
        day_spacing = 40  # Расстояние между днями в колонке
        pair_spacing = 30  # Отступ между парами

        # Ширина одной колонки (карточки дня)
        card_width = (width - 2 * padding - column_spacing) // NUM_COLUMNS
        text_width = card_width - 2 * card_padding  # Ширина для текста внутри карточки

        # --- Предварительный расчет высоты для каждого дня ---
        weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
        day_contents = {}
        valid_days = []

        # Заголовок дня (фиксированная высота) - увеличиваем для увеличенных шрифтов
        day_header_height = 90
        day_header_gap = 25  # Отступ под плашкой дня (учитываем в расчёте высоты)

        # Сначала определяем, какие дни недели имеют пары
        # ВАЖНО: Вычисляем понедельник на основе дат из week_schedule, а не текущей даты
        # Это гарантирует правильное сопоставление пар с днями недели
        if week_schedule:
            # Берем первую дату из расписания и вычисляем понедельник недели для нее
            first_date_str = sorted(week_schedule.keys())[0]
            first_date = datetime.datetime.strptime(first_date_str, "%Y-%m-%d").date()
            days_since_monday = first_date.weekday()
            monday = first_date - datetime.timedelta(days=days_since_monday)
        else:
            # Если расписания нет, используем текущую неделю (fallback)
            today = datetime.date.today()
            days_since_monday = today.weekday()
            if days_since_monday == 6:  # Воскресенье
                monday = today + datetime.timedelta(days=1)
            else:
                monday = today - datetime.timedelta(days=days_since_monday)

        for day_index, weekday_name in enumerate(weekdays):
            # Вычисляем дату для этого дня недели
            current_date = monday + datetime.timedelta(days=day_index)
            date_str = current_date.strftime("%Y-%m-%d")

            # Проверяем, есть ли пары для этого дня
            pairs = week_schedule.get(date_str, [])
            if not pairs:
                # Сохраняем пустое значение, чтобы колонка пропустила этот день
                day_contents[weekday_name] = {'height': 0, 'data': None, 'date_str': None}
                continue

            valid_days.append(weekday_name)
            pairs_data = []

            # Логика нумерации пар (как в текстовом расписании)
            pair_counter = 0
            last_counted_time = ""

            # Обрабатываем ВСЕ пары без ограничений
            for i, pair in enumerate(week_schedule[date_str]):
                lines_info = []

                # Определяем номер пары на основе времени
                time = pair.get('time', '-')
                if time != last_counted_time:
                    pair_counter += 1
                    last_counted_time = time

                # Получаем номер пары (используем обычные цифры вместо эмодзи для изображения)
                pair_number = pair_counter

                # 1. Время и номер пары (номер выделен жирным)
                # Рисуем номер и время отдельно для лучшего контроля
                time_text = f"{pair_number}. {time}"
                time_lines, h = wrap_text(time_text, time_font, text_width)
                lines_info.append({'lines': time_lines, 'height': h, 'font': time_font, 'pair_number': pair_number, 'time': time})

                # 2. Предмет (полный текст, без сокращений, без эмодзи)
                subject_text = pair.get('subject', '-')
                # Не сокращаем предмет, только переносим по словам
                subj_text = f"Предмет: {subject_text}"
                subj_lines, h = wrap_text(subj_text, content_font, text_width)
                lines_info.append({'lines': subj_lines, 'height': h, 'font': content_font})

                # 3. Группы (полный текст, без сокращений, без эмодзи)
                groups = pair.get('groups', [])
                if groups:
                    if isinstance(groups, list):
                        groups_text = ", ".join(groups)
                    else:
                        groups_text = str(groups)
                    groups_full_text = f"Группы: {groups_text}"
                    groups_lines, h = wrap_text(groups_full_text, info_font, text_width)
                    lines_info.append({'lines': groups_lines, 'height': h, 'font': info_font})

                # 4. Аудитория (полный текст, без эмодзи)
                auditorium = pair.get('auditorium', '-')
                if auditorium and auditorium != '-':
                    auditorium_text = f"Аудитория: {auditorium}"
                    auditorium_lines, h = wrap_text(auditorium_text, info_font, text_width)
                    lines_info.append({'lines': auditorium_lines, 'height': h, 'font': info_font})

                # 5. Преподаватель (полный текст, без эмодзи)
                teacher = pair.get('teacher', '')
                if teacher:
                    teacher_text = f"Преподаватель: {teacher}"
                    teacher_lines, h = wrap_text(teacher_text, info_font, text_width)
                    lines_info.append({'lines': teacher_lines, 'height': h, 'font': info_font})

                # Сохраняем данные пары (без добавления отступа здесь, отступ добавим при расчете общей высоты)
                pairs_data.append({'lines_info': lines_info})

            # Общая высота дня = заголовок + все пары + отступы
            if pairs_data:
                # Высота всех пар (включая отступы между парами)
                pairs_total_height = sum(
                    sum(info['height'] for info in pair_data['lines_info'])
                    for pair_data in pairs_data
                )
                # Добавляем отступы между парами (на одну меньше, чем пар)
                pairs_spacing_height = pair_spacing * (len(pairs_data) - 1) if len(pairs_data) > 1 else 0
                # ВАЖНО: учитываем дополнительный зазор под заголовком дня (day_header_gap),
                # который используется при отрисовке, чтобы текст не прилипал к плашке.
                total_day_height = (
                    day_header_height
                    + day_header_gap
                    + card_padding
                    + pairs_total_height
                    + pairs_spacing_height
                    + card_padding
                )
            else:
                # Если пар нет, минимальная высота (только заголовок)
                total_day_height = day_header_height + day_header_gap + 2 * card_padding

            day_contents[weekday_name] = {
                'height': total_day_height,
                'data': {'pairs_data': pairs_data, 'date_str': date_str} if pairs_data else None,
                'date_str': date_str
            }

        # Проверяем, есть ли вообще дни с парами
        if not valid_days:
            logger.warning("Нет дней с парами для экспорта")
            return None

        # Рассчитываем высоту для каждой колонки (только дни с парами)
        left_column_days = ["Понедельник", "Вторник", "Среда"]
        right_column_days = ["Четверг", "Пятница", "Суббота"]

        # Фильтруем только дни, у которых есть данные (пары)
        left_column_heights = [day_contents[d]['height'] for d in left_column_days if day_contents[d].get('data') and day_contents[d].get('height', 0) > 0]
        right_column_heights = [day_contents[d]['height'] for d in right_column_days if day_contents[d].get('data') and day_contents[d].get('height', 0) > 0]

        # Высота колонки = сумма высот всех дней в колонке + отступы между днями
        left_column_height = sum(left_column_heights) + (len(left_column_heights) - 1) * day_spacing if left_column_heights else 0
        right_column_height = sum(right_column_heights) + (len(right_column_heights) - 1) * day_spacing if right_column_heights else 0

        # Высота контента = максимальная высота из двух колонок
        content_height = max(left_column_height, right_column_height)

        # Если нет контента, возвращаем None
        if content_height == 0:
            logger.warning("Высота контента равна 0, нет данных для отображения")
            return None

        # Высота заголовка (динамическая, на основе реальных размеров)
        # Рассчитываем реальную высоту заголовка
        header_height_calc = padding
        logo_size = 0
        if LOGO_PATH and LOGO_PATH.exists():
            logo_size = 100  # Размер логотипа справа сверху
            # Логотип справа, заголовок слева - берем максимальную высоту
            header_height_calc = max(logo_size + padding, header_height_calc)
        # Заголовок "Расписание для группы"
        entity_label_text = "преподавателя" if entity_type == API_TYPE_TEACHER else "группы"
        title_text_calc = f"Расписание для {entity_label_text}"
        title_bbox_calc = title_font.getbbox(title_text_calc)
        # Если есть логотип, заголовок и название группы размещаются слева, логотип справа
        if logo_size > 0:
            # Высота = максимум из (логотип + отступ) и (заголовок + название + отступы)
            text_height = title_bbox_calc[3] + 10
            name_bbox_calc = name_font.getbbox(entity_name)
            text_height += name_bbox_calc[3] + 15
            header_height_calc = max(logo_size + padding, text_height + padding) + padding
        else:
            header_height_calc += title_bbox_calc[3] + 10
            name_bbox_calc = name_font.getbbox(entity_name)
            header_height_calc += name_bbox_calc[3] + 15
            header_height_calc += padding  # Нижний отступ заголовка

        # Общая высота изображения
        height = header_height_calc + content_height + padding

        # --- Отрисовка ---
        img = Image.new('RGB', (width, height), color=BG_COLOR)
        draw = ImageDraw.Draw(img)

        # 1. Глобальный заголовок с логотипом справа сверху
        y_header = padding
        logo_img = None
        if LOGO_PATH and LOGO_PATH.exists():
            # Логотип справа сверху (более профессиональный вид)
            logo_img = Image.open(LOGO_PATH).resize((100, 100), Image.Resampling.LANCZOS)
            # Конвертируем в RGBA для поддержки прозрачности
            if logo_img.mode != 'RGBA':
                logo_img = logo_img.convert('RGBA')
            # Убираем белый фон (делаем прозрачным)
            data = logo_img.getdata()
            new_data = []
            for item in data:
                # Если пиксель белый или почти белый, делаем его прозрачным
                if item[0] > 240 and item[1] > 240 and item[2] > 240:
                    new_data.append((item[0], item[1], item[2], 0))
                else:
                    new_data.append(item)
            logo_img.putdata(new_data)
            logo_x = width - logo_img.width - padding
            logo_y = padding
            img.paste(logo_img, (logo_x, logo_y), logo_img)

        # Заголовок и название группы слева
        entity_label = "преподавателя" if entity_type == API_TYPE_TEACHER else "группы"
        title_text = f"Расписание для {entity_label}"
        title_bbox = title_font.getbbox(title_text)
        draw.text((padding, y_header), title_text, fill=TEXT_COLOR, font=title_font)
        y_header += title_bbox[3] + 10

        name_bbox = name_font.getbbox(entity_name)
        draw.text((padding, y_header), entity_name, fill=TEXT_COLOR, font=name_font)
        y_header += name_bbox[3] + 15
        
        # Если есть логотип, заголовок должен быть на той же высоте или ниже логотипа
        if logo_img:
            header_bottom = y_header
            logo_bottom = padding + logo_img.height
            y_header = max(header_bottom, logo_bottom) + padding

        # 2. Отрисовка двух колонок
        # base_y должен совпадать с расчетом header_height_calc (y_header после отрисовки заголовка)
        base_y = y_header + padding

        # Левая колонка (Понедельник, Вторник, Среда)
        left_column_x = padding
        current_y_left = base_y

        # Правая колонка (Четверг, Пятница, Суббота)
        right_column_x = padding + card_width + column_spacing
        current_y_right = base_y

        def draw_day_card(column_x, start_y, weekday_name, day_content):
            """Отрисовывает карточку одного дня"""
            if not day_content or not day_content.get('data'):
                return 0

            date_str = day_content['date_str']
            if not date_str:
                return 0

            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            day_header_text = f"{weekday_name}, {date_obj.strftime('%d.%m.%Y')}"

            # Высота карточки = высота дня
            card_height = day_content['height']
            card_y = start_y

            # Рисуем белую карточку
            draw.rectangle([column_x, card_y, column_x + card_width, card_y + card_height], fill=CARD_COLOR, outline='#E0E0E0', width=2)

            # Заголовок дня
            y_in_card = card_y + card_padding
            header_rect_y = y_in_card
            draw.rectangle([column_x + card_padding, header_rect_y, column_x + card_width - card_padding, header_rect_y + day_header_height], fill=DAY_HEADER_BG)
            day_header_bbox = day_font.getbbox(day_header_text)
            draw.text(
                (column_x + (card_width - day_header_bbox[2]) / 2, header_rect_y + (day_header_height - day_header_bbox[3]) / 2),
                day_header_text, fill=DAY_HEADER_TEXT, font=day_font
            )
            # Учитываем зазор под заголовком дня
            y_in_card += day_header_height + day_header_gap

            # Рисуем все пары
            pairs_list = day_content['data']['pairs_data']
            for pair_idx, pair_data in enumerate(pairs_list):
                is_first_line = True
                for lines_info in pair_data['lines_info']:
                    font_to_use = lines_info.get('font', content_font)
                    line_height = font_to_use.getbbox('A')[3] + 6

                    # Если это первая строка (номер пары и время), выделяем номер
                    if is_first_line and 'pair_number' in lines_info:
                        pair_number = lines_info['pair_number']
                        time = lines_info.get('time', '')
                        # Рисуем номер пары жирным и большего размера
                        try:
                            pair_number_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), 32)
                        except Exception:
                            pair_number_font = time_font

                        # Рисуем номер пары
                        number_text = f"{pair_number}."
                        number_bbox = pair_number_font.getbbox(number_text)
                        number_width = number_bbox[2] - number_bbox[0]
                        # Номер пары выделен жирным и немного больше
                        draw.text((column_x + card_padding, y_in_card), number_text, fill='#006400', font=pair_number_font)

                        # Рисуем время после номера
                        time_x = column_x + card_padding + number_width + 8
                        time_text = time
                        draw.text((time_x, y_in_card), time_text, fill=TEXT_COLOR, font=time_font)
                        y_in_card += line_height
                        is_first_line = False
                    else:
                        for line in lines_info['lines']:
                            # Проверяем, не выходит ли текст за границы карточки
                            if y_in_card + line_height > card_y + card_height - card_padding:
                                # Если выходит, прекращаем отрисовку (это не должно происходить, т.к. высота рассчитана)
                                logger.warning(f"Текст выходит за границы карточки для дня {weekday_name}")
                                break

                            # Рисуем строку текста (уже перенесенную через wrap_text, без сокращений)
                            draw.text((column_x + card_padding, y_in_card), line, fill=TEXT_COLOR, font=font_to_use)
                            y_in_card += line_height
                        is_first_line = False

                # Отступ между парами (но не после последней пары)
                if pair_idx < len(pairs_list) - 1:
                    y_in_card += pair_spacing

            return card_height

        # Отрисовываем дни в левой колонке
        for weekday_name in left_column_days:
            day_content = day_contents.get(weekday_name)
            if day_content and day_content.get('data'):
                day_height = draw_day_card(left_column_x, current_y_left, weekday_name, day_content)
                current_y_left += day_height + day_spacing

        # Отрисовываем дни в правой колонке
        for weekday_name in right_column_days:
            day_content = day_contents.get(weekday_name)
            if day_content and day_content.get('data'):
                day_height = draw_day_card(right_column_x, current_y_right, weekday_name, day_content)
                current_y_right += day_height + day_spacing

        # Сохранение
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes

    except Exception as e:
        logger.error(f"Ошибка при генерации изображения: {e}", exc_info=True)
        return None

async def generate_day_schedule_image(day_schedule: Dict, entity_name: str, entity_type: str, font_size: int = 22) -> Optional[BytesIO]:
    """
    Генерирует изображение с расписанием на один день в новом эстетичном стиле.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("PIL/Pillow не установлен, генерация изображений недоступна")
        return None

    try:
        pairs = day_schedule.get("pairs", [])
        if not pairs:
            return None

        # --- Новый дизайн: Цвета и Шрифты ---
        BG_COLOR = '#F5F5F5'
        CARD_COLOR = '#FFFFFF'
        TEXT_COLOR = '#000000'
        DAY_HEADER_BG = '#e8f5e9'
        DAY_HEADER_TEXT = '#006400'

        title_font_size = 32
        name_font_size = 24
        day_font_size = font_size + 2
        content_font_size = font_size

        try:
            title_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), title_font_size)
            name_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), name_font_size)
            day_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), day_font_size)
            content_font = ImageFont.truetype(str(DEFAULT_FONT_PATH), content_font_size)
        except Exception:
            logger.warning("Не удалось загрузить кастомные шрифты, используются стандартные.")
            title_font = ImageFont.load_default()
            name_font = ImageFont.load_default()
            day_font = ImageFont.load_default()
            content_font = ImageFont.load_default()

        # --- Параметры изображения и макета ---
        width = 1200
        padding = 50
        card_padding = 30
        line_height = 35
        pair_spacing = 20

        # --- Динамический подсчет высоты ---
        y = padding
        logo_img = None
        if LOGO_PATH and LOGO_PATH.exists():
            logo_img = Image.open(LOGO_PATH).resize((100, 100), Image.Resampling.LANCZOS)
            # Конвертируем в RGBA для поддержки прозрачности
            if logo_img.mode != 'RGBA':
                logo_img = logo_img.convert('RGBA')
            # Убираем белый фон (делаем прозрачным)
            data = logo_img.getdata()
            new_data = []
            for item in data:
                # Если пиксель белый или почти белый, делаем его прозрачным
                if item[0] > 240 and item[1] > 240 and item[2] > 240:
                    new_data.append((item[0], item[1], item[2], 0))
                else:
                    new_data.append(item)
            logo_img.putdata(new_data)
            # Логотип справа, заголовок слева - берем максимальную высоту
            y = max(logo_img.height + padding, y)
        y += 50 + 40 + 30 # Заголовки
        y += card_padding + 50 + 15 # Отступ, заголовок дня, отступ
        for pair in pairs:
            y += line_height * 2
            if pair.get("groups"):
                y += line_height
            if pair.get("auditorium") and pair.get("auditorium") != "-":
                y += line_height
            if pair.get("teacher"):
                y += line_height
            y += pair_spacing
        height = y + padding

        # --- Отрисовка ---
        img = Image.new('RGB', (width, height), color=BG_COLOR)
        draw = ImageDraw.Draw(img)

        # 1. Заголовок с логотипом справа сверху
        y = padding
        if logo_img:
            # Логотип справа сверху
            logo_x = width - logo_img.width - padding
            logo_y = padding
            img.paste(logo_img, (logo_x, logo_y), logo_img if logo_img.mode == 'RGBA' else None)

        # Заголовок и название слева
        entity_label = "преподавателя" if entity_type == API_TYPE_TEACHER else "группы"
        title_text = f"Расписание для {entity_label}"
        draw.text((padding, y), title_text, fill=TEXT_COLOR, font=title_font)
        title_bbox = title_font.getbbox(title_text)
        y += title_bbox[3] + 10

        draw.text((padding, y), entity_name, fill=TEXT_COLOR, font=name_font)
        name_bbox = name_font.getbbox(entity_name)
        y += name_bbox[3] + 10
        
        # Если есть логотип, заголовок должен быть на той же высоте или ниже логотипа
        if logo_img:
            header_bottom = y
            logo_bottom = padding + logo_img.height
            y = max(header_bottom, logo_bottom) + 30
        else:
            y += 30

        # 2. Белая карточка
        card_x, card_y = padding, y
        card_width = width - 2 * padding
        card_height = height - y - padding
        draw.rectangle([card_x, card_y, card_x + card_width, card_y + card_height], fill=CARD_COLOR)

        # 3. Расписание внутри карточки
        y = card_y + card_padding
        date_str = day_schedule.get("date", "")
        weekday = day_schedule.get("weekday", "")
        day_header_text = f"{weekday}, {date_str}"
        day_header_bbox = day_font.getbbox(day_header_text)

        draw.rectangle([card_x + card_padding, y, card_x + card_width - card_padding, y + 50], fill=DAY_HEADER_BG)
        draw.text((card_x + (card_width - day_header_bbox[2]) / 2, y + (50 - day_header_bbox[3]) / 2),
                  day_header_text, fill=DAY_HEADER_TEXT, font=day_font)
        y += 50 + 15

        # Пары с правильной нумерацией (как в текстовом расписании)
        pair_counter = 0
        last_counted_time = ""

        for i, pair in enumerate(pairs):
            # Определяем номер пары на основе времени
            time = pair.get('time', '-')
            if time != last_counted_time:
                pair_counter += 1
                last_counted_time = time

            # Номер пары выделен жирным и зеленым цветом
            try:
                pair_number_font = ImageFont.truetype(str(DEFAULT_FONT_BOLD_PATH), 28)
            except Exception:
                pair_number_font = content_font

            # Рисуем номер пары и время
            number_text = f"{pair_counter}."
            number_bbox = pair_number_font.getbbox(number_text)
            number_width = number_bbox[2] - number_bbox[0]
            draw.text((card_x + card_padding + 15, y), number_text, fill='#006400', font=pair_number_font)
            draw.text((card_x + card_padding + 15 + number_width + 8, y), time, fill=TEXT_COLOR, font=content_font)
            y += line_height

            pair_text_lines = []
            # Предмет без эмодзи
            pair_text_lines.append(f"Предмет: {pair.get('subject', '-')}")
            groups = ", ".join(pair.get("groups", []))
            if groups:
                pair_text_lines.append(f"Группы: {groups}")
            auditorium = pair.get("auditorium", "-")
            if auditorium and auditorium != '-':
                pair_text_lines.append(f"Аудитория: {auditorium}")
            teacher = pair.get("teacher", "")
            if teacher:
                pair_text_lines.append(f"Преподаватель: {teacher}")

            for line in pair_text_lines:
                draw.text((card_x + card_padding + 15, y), line, fill=TEXT_COLOR, font=content_font)
                y += line_height
            y += pair_spacing

        # Сохранение
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes

    except Exception as e:
        logger.error(f"Ошибка при генерации изображения дня: {e}", exc_info=True)
        return None

async def generate_week_schedule_file(week_schedule: Dict[str, List[Dict]], entity_name: str, entity_type: str) -> Optional[BytesIO]:
    """
    Генерирует PDF файл с расписанием на неделю.
    Улучшения: ФИО преподавателя, серый фон страницы и центрированные заголовки дней.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Spacer, KeepTogether, Image, Flowable, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.units import mm
    except ImportError:
        logger.error("reportlab не установлен. Установите: pip install reportlab")
        return None

    try:
        # --- Вспомогательный класс для отрисовки плашек с закругленными углами ---
        class _RoundedHeader(Flowable):
            def __init__(self, text, style, background_color, corner_radius=3*mm, padding=10):
                super().__init__()
                self.text = text
                self.style = style
                self.background_color = background_color
                self.corner_radius = corner_radius
                self.padding = padding
                self.p = Paragraph(self.text, self.style)

            def wrap(self, availWidth, availHeight):
                self.width = availWidth
                p_width, p_height = self.p.wrapOn(self.canv, self.width - 2 * self.padding, availHeight)
                self.height = p_height + 2 * self.padding
                return self.width, self.height

            def draw(self):
                self.canv.saveState()
                self.canv.setFillColor(self.background_color)
                self.canv.roundRect(0, 0, self.width, self.height, self.corner_radius, stroke=0, fill=1)
                self.p.drawOn(self.canv, self.padding, self.padding)
                self.canv.restoreState()

        file_bytes = BytesIO()
        doc = SimpleDocTemplate(
            file_bytes,
            pagesize=A4,
            rightMargin=20*mm,
            leftMargin=20*mm,
            topMargin=15*mm,
            bottomMargin=20*mm
        )

        # --- Регистрация шрифтов ---
        FONT_NAME = 'Helvetica'
        FONT_NAME_BOLD = 'Helvetica-Bold'
        if DEFAULT_FONT_PATH.exists():
            pdfmetrics.registerFont(TTFont('DejaVuSans', str(DEFAULT_FONT_PATH)))
            FONT_NAME = 'DejaVuSans'
        if DEFAULT_FONT_BOLD_PATH.exists():
            pdfmetrics.registerFont(TTFont('DejaVuSansBold', str(DEFAULT_FONT_BOLD_PATH)))
            FONT_NAME_BOLD = 'DejaVuSansBold'
        if FONT_NAME_BOLD == 'Helvetica-Bold' and FONT_NAME != 'Helvetica':
            FONT_NAME_BOLD = FONT_NAME

        styles = getSampleStyleSheet()
        story = []
        from .utils import escape_html

        # --- HEADER (с логотипом справа сверху) ---
        entity_label = "преподавателя" if entity_type == API_TYPE_TEACHER else "группы"
        
        if LOGO_PATH and LOGO_PATH.exists():
            # Создаем таблицу для размещения логотипа справа и заголовка слева
            from reportlab.platypus import Table, TableStyle
            
            # Логотип справа
            logo = Image(str(LOGO_PATH), width=30*mm, height=30*mm)
            
            # Таблица: слева текст, справа логотип
            header_data = [
                [
                    Paragraph(f"<b>Расписание для {entity_label}</b><br/>{escape_html(entity_name)}", 
                             ParagraphStyle('Header', fontName=FONT_NAME_BOLD, fontSize=20, 
                                          textColor=colors.black, leading=24)),
                    logo
                ]
            ]
            header_table = Table(header_data, colWidths=[None, 35*mm])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(header_table)
            story.append(Spacer(1, 10*mm))
        else:
            # Если нет логотипа, используем старый вариант по центру
            title_style = ParagraphStyle(
                'MainTitle',
                fontName=FONT_NAME_BOLD,
                fontSize=28,
                textColor=colors.black,
                alignment=TA_CENTER,
                spaceAfter=2*mm,
                leading=34
            )
            story.append(Paragraph(f"Расписание для {entity_label}", title_style))

            # Подзаголовок с ФИО
            name_style = ParagraphStyle(
                'NameTitle',
                parent=title_style,
                fontName=FONT_NAME_BOLD,
                fontSize=20,
                spaceAfter=15*mm
            )
            story.append(Paragraph(escape_html(entity_name), name_style))

        # --- СТИЛИ ДЛЯ РАСПИСАНИЯ ---
        # ИЗМЕНЕНИЕ: alignment теперь TA_CENTER
        day_heading_text_style = ParagraphStyle(
            'DayHeadingText',
            fontName=FONT_NAME_BOLD,
            fontSize=13,
            textColor=colors.HexColor('#006400'),
            alignment=TA_CENTER # <--- ВЫРАВНИВАНИЕ ПО ЦЕНТРУ
        )
        pair_style = ParagraphStyle(
            'PairDetails',
            parent=styles['Normal'],
            fontName=FONT_NAME,
            fontSize=11,
            leading=15,
            textColor=colors.black,
            spaceAfter=10,
            spaceBefore=5,
            leftIndent=5
        )

        # --- СОДЕРЖИМОЕ РАСПИСАНИЯ ---
        weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
        for date_str in sorted(week_schedule.keys()):
            pairs = week_schedule[date_str]
            if not pairs: continue

            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            if date_obj.weekday() >= 6: continue

            day_content = []
            weekday_name = weekdays[date_obj.weekday()]
            date_formatted = date_obj.strftime("%d.%m.%Y")
            day_header_text = f"{weekday_name}, {date_formatted}"

            day_content.append(_RoundedHeader(
                text=day_header_text,
                style=day_heading_text_style,
                background_color=colors.HexColor('#e8f5e9')
            ))
            day_content.append(Spacer(1, 4 * mm))

            # Правильная нумерация пар (как в текстовом расписании)
            pair_counter = 0
            last_counted_time = ""

            for i, pair in enumerate(pairs):
                # Определяем номер пары на основе времени
                time = pair.get('time', '-')
                if time != last_counted_time:
                    pair_counter += 1
                    last_counted_time = time

                # Номер пары выделен жирным
                pair_text = f"<b>{pair_counter}.</b> {escape_html(str(time))}<br/>"
                pair_text += f"{escape_html(str(pair.get('subject', '-')))}<br/>"
                groups = ", ".join(pair.get("groups", []))
                if groups:
                    pair_text += f"Группы: {escape_html(groups)}<br/>"
                auditorium = pair.get("auditorium", "-")
                if auditorium and auditorium != "-":
                    pair_text += f"Аудитория: {escape_html(auditorium)}<br/>"
                teacher = pair.get("teacher", "")
                if teacher:
                    pair_text += f"Преподаватель: {escape_html(teacher)}<br/>"
                day_content.append(Paragraph(pair_text, pair_style))

            story.append(KeepTogether(day_content))
            story.append(Spacer(1, 8*mm))

        # --- Функция для отрисовки фона ---
        # ИЗМЕНЕНИЕ: Добавлена отрисовка фона
        def draw_background(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(colors.HexColor('#F5F5F5')) # Очень светлый серый
            canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], stroke=0, fill=1)
            canvas.restoreState()

        # Сборка документа с применением фона
        doc.build(story, onFirstPage=draw_background, onLaterPages=draw_background)
        file_bytes.seek(0)
        return file_bytes
    except Exception as e:
        logger.error(f"Ошибка при генерации PDF файла: {e}", exc_info=True)
        return None