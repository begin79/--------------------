# Решение проблемы таймаута PyPI на Amvera

## Проблема
```
WARNING: Retrying (Retry(total=9, connect=None, read=None, redirect=None, status=None))
after connection broken by 'ReadTimeoutError("HTTPSConnectionPool(host='pypi-lightmirrors.lightmirrors',
port=443): Read timed out. (read timeout=45.0)")'
```

## Что это значит?

Это **предупреждение**, а не ошибка. Pip пытается установить пакет `python-telegram-bot[job-queue]`, но соединение с PyPI прерывается по таймауту. Pip автоматически повторяет попытку до 9 раз.

## Решения

### Вариант 1: Подождать (рекомендуется)

Обычно pip успешно устанавливает пакет после нескольких повторных попыток. Просто подождите завершения сборки.

### Вариант 2: Увеличить таймаут в amvera.yaml

Если проблема повторяется, можно увеличить таймаут для pip:

```yaml
build:
  install:
    - pip install --timeout=300 -r requirements.txt
```

### Вариант 3: Использовать другой индекс PyPI

Если проблема с зеркалом `pypi-lightmirrors.lightmirrors`, можно использовать официальный PyPI:

```yaml
build:
  install:
    - pip install --index-url https://pypi.org/simple/ -r requirements.txt
```

### Вариант 4: Установить пакеты по отдельности

Можно разбить установку на несколько шагов:

```yaml
build:
  install:
    - pip install python-telegram-bot>=20.0
    - pip install python-telegram-bot[job-queue]>=20.0
    - pip install -r requirements.txt
```

## Проверка

После завершения сборки проверьте логи:
- Если видите `Successfully installed python-telegram-bot-...` - всё в порядке!
- Если видите ошибки установки - попробуйте варианты выше

## Текущий статус

Если сборка еще идет, просто подождите. Pip обычно справляется с таймаутами самостоятельно.

Если сборка завершилась с ошибкой, попробуйте перезапустить сборку - иногда это помогает при временных проблемах с сетью.

