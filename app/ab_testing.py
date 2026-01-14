"""
Базовая система A/B тестирования для бота
"""
import logging
import hashlib
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ABTestVariant:
    """Вариант A/B теста"""
    name: str
    weight: float  # Вес варианта (0.0 - 1.0)
    config: Dict[str, Any]  # Конфигурация варианта


class ABTesting:
    """Система A/B тестирования"""
    
    def __init__(self):
        self.tests: Dict[str, Dict[str, ABTestVariant]] = {}
        self.user_assignments: Dict[int, Dict[str, str]] = {}  # user_id: {test_name: variant_name}
    
    def register_test(self, test_name: str, variants: Dict[str, ABTestVariant]):
        """
        Зарегистрировать A/B тест
        
        Args:
            test_name: Название теста
            variants: Словарь вариантов {variant_name: ABTestVariant}
        """
        # Проверяем, что сумма весов равна 1.0
        total_weight = sum(v.weight for v in variants.values())
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"Сумма весов для теста '{test_name}' не равна 1.0 ({total_weight}), нормализуем")
            # Нормализуем веса
            for variant in variants.values():
                variant.weight /= total_weight
        
        self.tests[test_name] = variants
        logger.info(f"Зарегистрирован A/B тест '{test_name}' с {len(variants)} вариантами")
    
    def get_variant(self, user_id: int, test_name: str) -> Optional[str]:
        """
        Получить вариант теста для пользователя
        
        Args:
            user_id: ID пользователя
            test_name: Название теста
            
        Returns:
            Название варианта или None если тест не найден
        """
        if test_name not in self.tests:
            logger.warning(f"Тест '{test_name}' не найден")
            return None
        
        # Если пользователь уже имеет назначенный вариант, возвращаем его
        if user_id in self.user_assignments and test_name in self.user_assignments[user_id]:
            return self.user_assignments[user_id][test_name]
        
        # Назначаем вариант на основе детерминированного хеша
        variant_name = self._assign_variant(user_id, test_name)
        
        # Сохраняем назначение
        if user_id not in self.user_assignments:
            self.user_assignments[user_id] = {}
        self.user_assignments[user_id][test_name] = variant_name
        
        logger.debug(f"Пользователь {user_id} назначен на вариант '{variant_name}' теста '{test_name}'")
        return variant_name
    
    def _assign_variant(self, user_id: int, test_name: str) -> str:
        """
        Назначить вариант теста пользователю на основе детерминированного хеша
        
        Args:
            user_id: ID пользователя
            test_name: Название теста
            
        Returns:
            Название варианта
        """
        # Создаем детерминированный хеш из user_id и test_name
        hash_input = f"{user_id}_{test_name}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        
        # Нормализуем до 0-1
        normalized = (hash_value % 10000) / 10000.0
        
        # Назначаем вариант на основе весов
        variants = self.tests[test_name]
        cumulative = 0.0
        for variant_name, variant in variants.items():
            cumulative += variant.weight
            if normalized <= cumulative:
                return variant_name
        
        # Fallback на первый вариант
        return list(variants.keys())[0]
    
    def get_variant_config(self, user_id: int, test_name: str) -> Optional[Dict[str, Any]]:
        """
        Получить конфигурацию варианта для пользователя
        
        Args:
            user_id: ID пользователя
            test_name: Название теста
            
        Returns:
            Конфигурация варианта или None
        """
        variant_name = self.get_variant(user_id, test_name)
        if not variant_name or test_name not in self.tests:
            return None
        
        variant = self.tests[test_name].get(variant_name)
        return variant.config if variant else None
    
    def get_test_stats(self, test_name: str) -> Dict[str, int]:
        """
        Получить статистику распределения вариантов теста
        
        Args:
            test_name: Название теста
            
        Returns:
            Словарь {variant_name: count}
        """
        if test_name not in self.tests:
            return {}
        
        stats = {variant_name: 0 for variant_name in self.tests[test_name].keys()}
        
        for user_id, assignments in self.user_assignments.items():
            variant = assignments.get(test_name)
            if variant and variant in stats:
                stats[variant] += 1
        
        return stats


# Глобальный экземпляр
ab_testing = ABTesting()

# Пример регистрации тестов (можно вызывать при инициализации)
def init_default_tests():
    """Инициализировать тесты по умолчанию"""
    # Пример: тест на форматирование расписания
    ab_testing.register_test("schedule_format", {
        "control": ABTestVariant(
            name="control",
            weight=0.5,
            config={"use_emojis": True, "compact_mode": False}
        ),
        "compact": ABTestVariant(
            name="compact",
            weight=0.5,
            config={"use_emojis": True, "compact_mode": True}
        )
    })
    
    logger.info("Инициализированы тесты по умолчанию")

