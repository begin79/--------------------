import html
from typing import List, Dict, Optional, Tuple
import hashlib
import datetime

def escape_html(text: str) -> str:
    return html.escape(str(text))

def hash_schedule(pages: List[str]) -> str:
    content = "|".join(pages)
    return hashlib.md5(content.encode("utf-8")).hexdigest()

def get_next_weekday(date: datetime.date) -> datetime.date:
    """Получить следующий рабочий день (пропуская выходные)"""
    next_day = date + datetime.timedelta(days=1)
    # Если воскресенье (6) или суббота (5), переходим на понедельник
    while next_day.weekday() >= 5:  # 5 = суббота, 6 = воскресенье
        next_day += datetime.timedelta(days=1)
    return next_day

def compare_schedules(old_schedule: Optional[Dict], new_schedule: Optional[Dict]) -> List[Dict]:
    """
    Сравнивает старое и новое расписание и возвращает список изменений.

    Args:
        old_schedule: Структурированное расписание (из get_schedule_structured) или None
        new_schedule: Структурированное расписание (из get_schedule_structured) или None

    Returns:
        Список словарей с изменениями, каждый содержит:
        - type: "added", "removed", "modified", "time_changed", "auditorium_changed", "subject_changed"
        - time: время пары
        - old_pair: старая пара (для modified)
        - new_pair: новая пара (для modified/added)
    """
    changes = []

    if not old_schedule and not new_schedule:
        return changes

    if not old_schedule:
        # Все пары новые
        if new_schedule and new_schedule.get("pairs"):
            for pair in new_schedule["pairs"]:
                changes.append({
                    "type": "added",
                    "time": pair.get("time", "-"),
                    "new_pair": pair
                })
        return changes

    if not new_schedule:
        # Все пары удалены
        if old_schedule and old_schedule.get("pairs"):
            for pair in old_schedule["pairs"]:
                changes.append({
                    "type": "removed",
                    "time": pair.get("time", "-"),
                    "old_pair": pair
                })
        return changes

    old_pairs = {pair.get("time", ""): pair for pair in old_schedule.get("pairs", [])}
    new_pairs = {pair.get("time", ""): pair for pair in new_schedule.get("pairs", [])}

    all_times = set(old_pairs.keys()) | set(new_pairs.keys())

    for time in sorted(all_times):
        old_pair = old_pairs.get(time)
        new_pair = new_pairs.get(time)

        if not old_pair:
            # Новая пара добавлена
            changes.append({
                "type": "added",
                "time": time,
                "new_pair": new_pair
            })
        elif not new_pair:
            # Пара удалена
            changes.append({
                "type": "removed",
                "time": time,
                "old_pair": old_pair
            })
        else:
            # Пара существует в обоих - проверяем изменения
            modified_fields = []

            if old_pair.get("subject", "").strip() != new_pair.get("subject", "").strip():
                modified_fields.append("subject")
            if old_pair.get("auditorium", "").strip() != new_pair.get("auditorium", "").strip():
                modified_fields.append("auditorium")
            if old_pair.get("teacher", "").strip() != new_pair.get("teacher", "").strip():
                modified_fields.append("teacher")
            if set(old_pair.get("groups", [])) != set(new_pair.get("groups", [])):
                modified_fields.append("groups")

            if modified_fields:
                change_type = "modified"
                if len(modified_fields) == 1:
                    if "auditorium" in modified_fields:
                        change_type = "auditorium_changed"
                    elif "subject" in modified_fields:
                        change_type = "subject_changed"
                    elif "time" in modified_fields:
                        change_type = "time_changed"

                changes.append({
                    "type": change_type,
                    "time": time,
                    "old_pair": old_pair,
                    "new_pair": new_pair,
                    "modified_fields": modified_fields
                })

    return changes

def format_schedule_changes(changes: List[Dict], date_str: str, query: str) -> str:
    """
    Форматирует список изменений в красивое сообщение.

    Args:
        changes: Список изменений из compare_schedules
        date_str: Дата в формате YYYY-MM-DD
        query: Название группы/преподавателя

    Returns:
        Отформатированное сообщение с изменениями
    """
    if not changes:
        return ""

    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        date_display = date_obj.strftime("%d.%m.%Y")
    except:
        date_display = date_str

    lines = [f"🔔 <b>Изменения в расписании</b>\n"]
    lines.append(f"📅 <b>{date_display}</b> для {escape_html(query)}\n")

    added = [c for c in changes if c["type"] == "added"]
    removed = [c for c in changes if c["type"] == "removed"]
    modified = [c for c in changes if c["type"] in ["modified", "auditorium_changed", "subject_changed", "time_changed"]]

    if added:
        lines.append(f"\n➕ <b>Добавлено пар:</b> {len(added)}")
        for change in added[:5]:  # Показываем максимум 5
            pair = change["new_pair"]
            time = pair.get("time", "-")
            subject = pair.get("subject", "-")
            auditorium = pair.get("auditorium", "-")
            teacher = pair.get("teacher", "")

            line = f"  • {time} — {escape_html(subject)}"
            if auditorium and auditorium != "-":
                line += f" (каб. {escape_html(auditorium)})"
            if teacher:
                line += f"\n    👤 {escape_html(teacher)}"
            lines.append(line)
        if len(added) > 5:
            lines.append(f"  ... и ещё {len(added) - 5}")

    if removed:
        lines.append(f"\n➖ <b>Удалено пар:</b> {len(removed)}")
        for change in removed[:5]:  # Показываем максимум 5
            pair = change["old_pair"]
            time = pair.get("time", "-")
            subject = pair.get("subject", "-")

            lines.append(f"  • {time} — {escape_html(subject)}")
        if len(removed) > 5:
            lines.append(f"  ... и ещё {len(removed) - 5}")

    if modified:
        lines.append(f"\n✏️ <b>Изменено пар:</b> {len(modified)}")
        for change in modified[:5]:  # Показываем максимум 5
            old_pair = change["old_pair"]
            new_pair = change["new_pair"]
            time = new_pair.get("time", "-")
            modified_fields = change.get("modified_fields", [])

            if "auditorium" in modified_fields:
                old_aud = old_pair.get("auditorium", "-")
                new_aud = new_pair.get("auditorium", "-")
                lines.append(f"  • {time} — кабинет изменён:")
                lines.append(f"    {escape_html(old_aud)} → {escape_html(new_aud)}")

            if "subject" in modified_fields:
                old_subj = old_pair.get("subject", "-")
                new_subj = new_pair.get("subject", "-")
                lines.append(f"  • {time} — предмет изменён:")
                lines.append(f"    {escape_html(old_subj)} → {escape_html(new_subj)}")

            if "teacher" in modified_fields:
                old_teach = old_pair.get("teacher", "-")
                new_teach = new_pair.get("teacher", "-")
                lines.append(f"  • {time} — преподаватель изменён:")
                lines.append(f"    {escape_html(old_teach)} → {escape_html(new_teach)}")

            if "groups" in modified_fields:
                old_groups = ", ".join(old_pair.get("groups", []))
                new_groups = ", ".join(new_pair.get("groups", []))
                lines.append(f"  • {time} — группы изменены:")
                lines.append(f"    {escape_html(old_groups)} → {escape_html(new_groups)}")

            # Если изменено несколько полей одновременно
            if len(modified_fields) > 1:
                lines.append(f"  • {time} — изменено несколько параметров")
                subject = new_pair.get("subject", "-")
                auditorium = new_pair.get("auditorium", "-")
                teacher = new_pair.get("teacher", "")
                line = f"    {escape_html(subject)}"
                if auditorium and auditorium != "-":
                    line += f" (каб. {escape_html(auditorium)})"
                if teacher:
                    line += f" — {escape_html(teacher)}"
                lines.append(line)

        if len(modified) > 5:
            lines.append(f"  ... и ещё {len(modified) - 5}")

    return "\n".join(lines)
