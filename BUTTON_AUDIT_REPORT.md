# Отчет аудита кнопок бота ВГЛТУ

## 🔍 Найденные проблемы

### 1. ❌ CRITICAL: Отсутствие await query.answer() в некоторых обработчиках

**Проблема:** В нескольких обработчиках используется прямой вызов `update.callback_query.answer()` вместо `safe_answer_callback_query()`, что может вызывать ошибки при истечении callback query.

**Места:**
- `app/callbacks.py:242` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:250` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:257` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:265` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:279` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:289` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:312` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:601` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:606` - прямой вызов `update.callback_query.answer()`
- `app/callbacks.py:612` - прямой вызов `update.callback_query.answer()`

**Решение:** Заменить все прямые вызовы на `safe_answer_callback_query()`.

---

### 2. ⚠️ MEDIUM: Возможное превышение длины callback_data

**Проблема:** Некоторые динамически формируемые callback_data могут превысить лимит Telegram (64 байта).

**Рисковые места:**
- `view_changed_schedule_{mode}_{date_str}` - может быть длинным при длинных датах
- `export_week_file_{mode}_{query_hash}` - зависит от длины query_hash
- `user_reply_admin_{admin_id}` - безопасно, так как admin_id - число

**Решение:** Добавить валидацию длины callback_data перед созданием кнопок.

---

### 3. ⚠️ MEDIUM: Отсутствие обработки ошибок "Message is not modified"

**Проблема:** Функция `safe_edit_message_text()` уже обрабатывает эту ошибку, но некоторые места могут использовать прямые вызовы `edit_message_text()`.

**Решение:** Убедиться, что везде используется `safe_edit_message_text()`.

---

### 4. ⚠️ LOW: Логика навигации "Назад" и "В меню"

**Анализ:**
- ✅ `CALLBACK_DATA_BACK_TO_START` - корректно ведет в `/start`
- ✅ `CALLBACK_DATA_BACK_TO_SCHEDULE` - корректно ведет к расписанию
- ⚠️ Нужно проверить, что все кнопки "Назад" имеют путь возврата

---

### 5. ⚠️ LOW: Валидация данных при восстановлении из user_data

**Проблема:** При использовании данных из `user_data` после перезагрузки сервера данные могут отсутствовать.

**Решение:** Добавить проверки наличия данных и fallback логику.

---

## ✅ Рекомендации по исправлению

1. Заменить все прямые вызовы `callback_query.answer()` на `safe_answer_callback_query()`
2. Добавить валидацию длины callback_data
3. Проверить все пути навигации
4. Добавить fallback для отсутствующих данных
5. Улучшить обработку ошибок редактирования сообщений

