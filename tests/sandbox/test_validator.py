"""Adversarial tests for CodeValidator — security hardening."""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

from backend.sandbox.validator import CodeValidator, ValidationResult


# Valid Trait code for positive testing
VALID_TRAIT = """
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING


class HeatShield(BaseTrait):
    async def execute(self, entity) -> None:
        # Reduce energy consumption in hot areas
        if entity.x > 1000:
            entity.energy += 0.5
"""

# Minimal valid trait
MINIMAL_TRAIT = """
class SimpleTrait(Trait):
    async def execute(self, entity):
        entity.energy += 1
"""


class TestSyntaxValidation:
    """Test Level 1: Syntax validation."""

    @pytest.mark.asyncio
    async def test_valid_syntax(self) -> None:
        """Test that valid Python syntax passes."""
        validator = CodeValidator()
        result = await validator.validate(VALID_TRAIT)
        assert result.is_valid
        assert result.trait_class_name == "HeatShield"

    @pytest.mark.asyncio
    async def test_syntax_error_missing_colon(self) -> None:
        """Test that syntax errors are caught."""
        code = """
class Broken(Trait)
    async def execute(self, entity):
        pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "Syntax error" in result.error

    @pytest.mark.asyncio
    async def test_syntax_error_incomplete_code(self) -> None:
        """Test incomplete code is rejected."""
        code = "def foo("
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "Syntax error" in result.error


class TestImportWhitelist:
    """Test Level 2: Import whitelist enforcement."""

    @pytest.mark.asyncio
    async def test_allowed_imports(self) -> None:
        """Test that whitelisted imports are allowed."""
        code = """
import math
import random
from dataclasses import dataclass
from typing import Optional
from enum import Enum
from collections import defaultdict
from functools import lru_cache
from itertools import cycle

class GoodTrait(Trait):
    async def execute(self, entity):
        x = math.sqrt(16)
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert result.is_valid

    @pytest.mark.asyncio
    async def test_forbidden_import_os(self) -> None:
        """Test that os module is blocked."""
        code = """
import os

class EvilTrait(Trait):
    async def execute(self, entity):
        os.system("rm -rf /")
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "Forbidden import" in result.error
        assert "os" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_import_sys(self) -> None:
        """Test that sys module is blocked."""
        code = """
import sys

class EvilTrait(Trait):
    async def execute(self, entity):
        sys.exit(1)
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "sys" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_import_subprocess(self) -> None:
        """Test that subprocess module is blocked."""
        code = """
from subprocess import Popen

class EvilTrait(Trait):
    async def execute(self, entity):
        Popen(["rm", "-rf", "/"])
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "subprocess" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_import_socket(self) -> None:
        """Test that socket module is blocked."""
        code = """
import socket

class EvilTrait(Trait):
    async def execute(self, entity):
        socket.socket()
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "socket" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_import_requests(self) -> None:
        """Test that requests module is blocked."""
        code = """
import requests

class EvilTrait(Trait):
    async def execute(self, entity):
        requests.get("http://evil.com")
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "requests" in result.error


class TestBannedOperations:
    """Test Level 3: Banned calls and attribute access."""

    @pytest.mark.asyncio
    async def test_eval_blocked(self) -> None:
        """Test that eval() is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        eval("__import__('os').system('ls')")
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "eval" in result.error

    @pytest.mark.asyncio
    async def test_exec_blocked(self) -> None:
        """Test that exec() is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        exec("import os; os.system('ls')")
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "exec" in result.error

    @pytest.mark.asyncio
    async def test_open_blocked(self) -> None:
        """Test that open() is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        with open('/etc/passwd') as f:
            data = f.read()
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "open" in result.error

    @pytest.mark.asyncio
    async def test_import_dunder_blocked(self) -> None:
        """Test that __import__ is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        os = __import__('os')
        os.system('ls')
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "__import__" in result.error

    @pytest.mark.asyncio
    async def test_subclasses_blocked(self) -> None:
        """Test that __subclasses__ is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        for cls in object.__subclasses__():
            pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "__subclasses__" in result.error

    @pytest.mark.asyncio
    async def test_globals_blocked(self) -> None:
        """Test that __globals__ is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        g = self.execute.__globals__
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "__globals__" in result.error

    @pytest.mark.asyncio
    async def test_builtins_blocked(self) -> None:
        """Test that __builtins__ is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        b = __builtins__
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "__builtins__" in result.error

    @pytest.mark.asyncio
    async def test_compile_blocked(self) -> None:
        """Test that compile() is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        code_obj = compile("print('evil')", "<string>", "exec")
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "compile" in result.error

    @pytest.mark.asyncio
    async def test_globals_function_blocked(self) -> None:
        """Test that globals() is blocked."""
        code = """
class EvilTrait(Trait):
    async def execute(self, entity):
        g = globals()
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "globals" in result.error


class TestTraitContract:
    """Test Level 4: Trait contract validation."""

    @pytest.mark.asyncio
    async def test_valid_trait_basetrait(self) -> None:
        """Test valid Trait inheriting from BaseTrait."""
        code = """
class MyTrait(BaseTrait):
    async def execute(self, entity):
        entity.energy += 1
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert result.is_valid
        assert result.trait_class_name == "MyTrait"

    @pytest.mark.asyncio
    async def test_valid_trait_trait(self) -> None:
        """Test valid Trait inheriting from Trait."""
        validator = CodeValidator()
        result = await validator.validate(MINIMAL_TRAIT)
        assert result.is_valid
        assert result.trait_class_name == "SimpleTrait"

    @pytest.mark.asyncio
    async def test_missing_inheritance(self) -> None:
        """Test that class without Trait inheritance is rejected."""
        code = """
class NotATrait:
    async def execute(self, entity):
        pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "No valid Trait class found" in result.error

    @pytest.mark.asyncio
    async def test_missing_execute_method(self) -> None:
        """Test that Trait without execute method is rejected."""
        code = """
class IncompleteTrait(Trait):
    async def update(self, entity):
        pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "No valid Trait class found" in result.error

    @pytest.mark.asyncio
    async def test_synchronous_execute(self) -> None:
        """Test that synchronous execute method is rejected."""
        code = """
class SyncTrait(Trait):
    def execute(self, entity):
        pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "No valid Trait class found" in result.error

    @pytest.mark.asyncio
    async def test_execute_wrong_params(self) -> None:
        """Test that execute with wrong params is rejected."""
        code = """
class WrongParamsTrait(Trait):
    async def execute(self):
        pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid

    @pytest.mark.asyncio
    async def test_multiple_traits_first_valid(self) -> None:
        """Test that first valid Trait is detected."""
        code = """
class HelperClass:
    pass

class ValidTrait(BaseTrait):
    async def execute(self, entity):
        pass

class AnotherClass:
    pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert result.is_valid
        assert result.trait_class_name == "ValidTrait"


class TestDeduplication:
    """Test Level 5: SHA-256 deduplication."""

    @pytest_asyncio.fixture
    async def mock_redis(self) -> AsyncMock:
        """Create mock Redis client."""
        redis = AsyncMock()
        redis.sismember = AsyncMock(return_value=False)
        redis.sadd = AsyncMock()
        return redis

    @pytest.mark.asyncio
    async def test_hash_calculated(self, mock_redis: AsyncMock) -> None:
        """Test that code hash is calculated."""
        validator = CodeValidator(redis=mock_redis)
        result = await validator.validate(MINIMAL_TRAIT)
        assert result.code_hash is not None
        assert len(result.code_hash) == 64  # SHA-256 hex = 64 chars

    @pytest.mark.asyncio
    async def test_duplicate_rejected(self, mock_redis: AsyncMock) -> None:
        """Test that duplicate code is rejected."""
        # Configure mock to return True (hash exists)
        mock_redis.sismember = AsyncMock(return_value=True)

        validator = CodeValidator(redis=mock_redis)
        result = await validator.validate(MINIMAL_TRAIT)

        assert not result.is_valid
        assert "Duplicate" in result.error
        assert result.code_hash is not None

    @pytest.mark.asyncio
    async def test_mark_as_used(self, mock_redis: AsyncMock) -> None:
        """Test that hash can be marked as used."""
        validator = CodeValidator(redis=mock_redis)

        # First validate
        result = await validator.validate(MINIMAL_TRAIT)
        assert result.is_valid

        # Mark as used
        await validator.mark_as_used(result.code_hash)

        # Verify Redis sadd was called
        mock_redis.sadd.assert_called_once_with(
            "evo:mutation:hashes",
            result.code_hash,
        )

    @pytest.mark.asyncio
    async def test_dedup_without_redis(self) -> None:
        """Test that validation works without Redis."""
        validator = CodeValidator(redis=None)
        result = await validator.validate(MINIMAL_TRAIT)
        assert result.is_valid
        assert result.code_hash is not None

    @pytest.mark.asyncio
    async def test_same_code_same_hash(self) -> None:
        """Test that identical code produces identical hash."""
        validator = CodeValidator()
        result1 = await validator.validate(MINIMAL_TRAIT)
        result2 = await validator.validate(MINIMAL_TRAIT)
        assert result1.code_hash == result2.code_hash

    @pytest.mark.asyncio
    async def test_different_code_different_hash(self) -> None:
        """Test that different code produces different hash."""
        code1 = MINIMAL_TRAIT
        code2 = """
class DifferentTrait(Trait):
    async def execute(self, entity):
        entity.energy += 2
"""
        validator = CodeValidator()
        result1 = await validator.validate(code1)
        result2 = await validator.validate(code2)
        assert result1.code_hash != result2.code_hash


class TestAdversarialCombinations:
    """Test combinations of adversarial techniques."""

    @pytest.mark.asyncio
    async def test_obfuscated_import(self) -> None:
        """Test obfuscated malicious import."""
        code = """
import sys as system_module

class SneakyTrait(Trait):
    async def execute(self, entity):
        system_module.exit(1)
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "sys" in result.error

    @pytest.mark.asyncio
    async def test_attribute_chain_attack(self) -> None:
        """Test attribute chain to access internals."""
        code = """
class ChainAttack(Trait):
    async def execute(self, entity):
        cls = entity.__class__
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        assert not result.is_valid
        assert "__class__" in result.error

    @pytest.mark.asyncio
    async def test_infinite_loop_allowed(self) -> None:
        """Test that infinite loop passes validation.

        Note: Infinite loops are caught at runtime by timeout, not validation.
        """
        code = """
class InfiniteLoop(Trait):
    async def execute(self, entity):
        while True:
            entity.x += 1
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        # Infinite loops are allowed - will be killed by timeout at runtime
        assert result.is_valid

    @pytest.mark.asyncio
    async def test_module_level_code_allowed(self) -> None:
        """Test that module-level executable code is allowed by validator.

        Note: Module-level code restrictions are enforced by a separate
        AST validator (not yet implemented).
        """
        code = """
print("This runs at import time!")  # Will be caught by import validator later

class NormalTrait(Trait):
    async def execute(self, entity):
        pass
"""
        validator = CodeValidator()
        result = await validator.validate(code)
        # Module-level print() will be caught by banned calls check
        assert not result.is_valid
        assert "print" in result.error
