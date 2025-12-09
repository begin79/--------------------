# Решение проблемы аутентификации Amvera

## Проблема
```
fatal: Authentication failed for 'https://git.msk0.amvera.ru/andro8461/vgltu-version-2/'
```

## Решения (попробуйте по порядку)

### ✅ Решение 1: Использовать токен доступа (самое надежное)

1. **Создайте токен доступа в Amvera:**
   - Войдите в панель Amvera
   - Перейдите в: **Настройки аккаунта** → **Токены доступа** (или **Access Tokens**)
   - Создайте новый токен с правами на запись в репозиторий
   - Скопируйте токен (он показывается только один раз!)

2. **Используйте токен вместо пароля:**
   ```bash
   git push amvera master
   ```
   - **Username**: `andro8461` (ваш логин)
   - **Password**: вставьте **токен доступа** (не обычный пароль!)

### ✅ Решение 2: Включить username в URL

```bash
# Обновите remote URL с username
git remote set-url amvera https://andro8461@git.msk0.amvera.ru/andro8461/vgltu-version-2

# Проверьте, что URL обновлен
git remote -v

# Теперь попробуйте push (потребуется только пароль/токен)
git push amvera master
```

### ✅ Решение 3: Использовать SSH (если у вас настроены SSH ключи)

1. **Проверьте, есть ли SSH ключ:**
   ```bash
   ls ~/.ssh/id_rsa.pub
   ```

2. **Если ключа нет, создайте его:**
   ```bash
   ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
   ```

3. **Добавьте публичный ключ в Amvera:**
   - Скопируйте содержимое `~/.ssh/id_rsa.pub`
   - В панели Amvera: **Настройки** → **SSH ключи** → **Добавить ключ**

4. **Измените remote на SSH:**
   ```bash
   git remote set-url amvera git@git.msk0.amvera.ru:andro8461/vgltu-version-2.git

   # Проверьте подключение
   ssh -T git@git.msk0.amvera.ru

   # Push через SSH
   git push amvera master
   ```

### ✅ Решение 4: Использовать Git Credential Manager (Windows)

```bash
# Включить менеджер учетных данных
git config --global credential.helper manager-core

# Попробуйте push снова
git push amvera master
# Введите логин и пароль/токен в появившемся окне
```

### ✅ Решение 5: Сохранить учетные данные в Git config (не рекомендуется для безопасности)

```bash
# Временно сохранить учетные данные
git config --global credential.helper store

# Попробуйте push
git push amvera master
# Введите логин и токен один раз, они сохранятся
```

## Проверка текущей конфигурации

```bash
# Проверить текущий remote URL
git remote get-url amvera

# Проверить все remotes
git remote -v

# Проверить настройки credential helper
git config --global credential.helper
```

## Рекомендация

**Используйте Решение 1 (токен доступа)** - это самый безопасный и надежный способ.

После настройки токена, все последующие push будут работать автоматически (если используете credential helper).

## Если ничего не помогло

1. Проверьте, что у вас есть права на запись в репозиторий
2. Убедитесь, что репозиторий существует и доступен
3. Попробуйте создать новый токен доступа
4. Обратитесь в поддержку Amvera

