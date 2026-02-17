"""Code validation system for LLM-generated Trait mutations.

This module provides security-hardened validation to prevent malicious or
broken code from being executed in the simulation.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from typing import Optional

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()

# Whitelist of allowed imports for mutations
ALLOWED_IMPORTS = {
    "__future__",  # Required for annotations
    "math",
    "random",
    "dataclasses",
    "typing",
    "enum",
    "collections",
    "functools",
    "itertools",
}

# Banned function calls that could be used for malicious purposes
BANNED_CALLS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "breakpoint",
    "globals",
    "locals",
    "vars",
    "dir",
    "help",
    "input",
    "print",  # Prevent spam, use logger instead
}

# Banned attribute accesses (dunders that could expose internals)
BANNED_ATTRS = {
    "__subclasses__",
    "__bases__",
    "__globals__",
    "__code__",
    "__builtins__",
    "__dict__",
    "__class__",
    "__mro__",
}


@dataclass
class ValidationResult:
    """Result of code validation.

    Attributes:
        is_valid: Whether the code passed all validation checks
        error: Error message if validation failed, None otherwise
        trait_class_name: Name of the Trait class found in code, None if invalid
        code_hash: SHA-256 hash of the source code
    """

    is_valid: bool
    error: Optional[str] = None
    trait_class_name: Optional[str] = None
    code_hash: Optional[str] = None


class CodeValidator:
    """Validates LLM-generated Trait code for security and correctness.

    This validator performs multi-level checks:
    1. Syntax validation (AST parsing)
    2. Import whitelist enforcement
    3. Banned call and attribute detection
    4. Trait contract verification (async execute method)
    5. SHA-256 deduplication via Redis

    The validator is designed to be paranoid and reject anything suspicious.
    """

    def __init__(self, redis: Optional[Redis] = None) -> None:
        """Initialize the code validator.

        Args:
            redis: Optional Redis connection for deduplication checks.
                   If None, deduplication is skipped.
        """
        self._redis = redis

    async def validate(self, source_code: str) -> ValidationResult:
        """Validate source code through all security levels.

        Args:
            source_code: Python source code to validate

        Returns:
            ValidationResult with validation status and details

        Note:
            This method is async to support Redis deduplication checks.
            For synchronous use without Redis, use validate_syntax_only().
        """
        # Calculate hash first (needed for all results)
        code_hash = self._calculate_hash(source_code)

        # Level 1: Syntax validation
        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            logger.warning("validation_failed_syntax", error=str(exc))
            return ValidationResult(
                is_valid=False,
                error=f"Syntax error: {exc}",
                code_hash=code_hash,
            )

        # Level 2: Import whitelist
        import_error = self._check_imports(tree)
        if import_error:
            logger.warning("validation_failed_imports", error=import_error)
            return ValidationResult(
                is_valid=False,
                error=import_error,
                code_hash=code_hash,
            )

        # Level 3: Banned calls and attributes
        banned_error = self._check_banned_operations(tree)
        if banned_error:
            logger.warning("validation_failed_banned", error=banned_error)
            return ValidationResult(
                is_valid=False,
                error=banned_error,
                code_hash=code_hash,
            )

        # Level 4: Trait contract validation
        trait_class_name = self._check_trait_contract(tree)
        if not trait_class_name:
            error = "No valid Trait class found (must inherit from BaseTrait/Trait and have async execute(self, entity) method)"
            logger.warning("validation_failed_contract", error=error)
            return ValidationResult(
                is_valid=False,
                error=error,
                code_hash=code_hash,
            )

        # Level 5: Deduplication check (if Redis available)
        if self._redis:
            is_duplicate = await self._check_duplicate(code_hash)
            if is_duplicate:
                error = f"Duplicate code (hash: {code_hash[:16]}...)"
                logger.warning("validation_failed_duplicate", code_hash=code_hash)
                return ValidationResult(
                    is_valid=False,
                    error=error,
                    code_hash=code_hash,
                )

        # All checks passed!
        logger.info(
            "validation_success",
            trait_class_name=trait_class_name,
            code_hash=code_hash[:16],
        )
        return ValidationResult(
            is_valid=True,
            trait_class_name=trait_class_name,
            code_hash=code_hash,
        )

    def _calculate_hash(self, source_code: str) -> str:
        """Calculate SHA-256 hash of source code.

        Args:
            source_code: Source code to hash

        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    def _check_imports(self, tree: ast.AST) -> Optional[str]:
        """Check that all imports are in the whitelist.

        Args:
            tree: AST of the source code

        Returns:
            Error message if invalid import found, None otherwise
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]  # Get top-level module
                    if module not in ALLOWED_IMPORTS:
                        return f"Forbidden import: {alias.name} (only {', '.join(sorted(ALLOWED_IMPORTS))} allowed)"

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split(".")[0]
                    if module not in ALLOWED_IMPORTS:
                        return f"Forbidden import: from {node.module} (only {', '.join(sorted(ALLOWED_IMPORTS))} allowed)"

        return None

    def _check_banned_operations(self, tree: ast.AST) -> Optional[str]:
        """Check for banned function calls and attribute accesses.

        Args:
            tree: AST of the source code

        Returns:
            Error message if banned operation found, None otherwise
        """
        for node in ast.walk(tree):
            # Check for banned function calls
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node.func)
                if func_name in BANNED_CALLS:
                    return f"Forbidden function call: {func_name}()"

            # Check for banned attribute accesses
            elif isinstance(node, ast.Attribute):
                if node.attr in BANNED_ATTRS:
                    return f"Forbidden attribute access: .{node.attr}"

            # Check for banned names (like __builtins__)
            elif isinstance(node, ast.Name):
                if node.id in BANNED_ATTRS:
                    return f"Forbidden name: {node.id}"

        return None

    def _get_call_name(self, node: ast.expr) -> str:
        """Extract function name from a Call node.

        Args:
            node: AST node representing a function call

        Returns:
            Function name as string, or empty string if complex
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        else:
            return ""

    def _check_trait_contract(self, tree: ast.AST) -> Optional[str]:
        """Verify that code contains a valid Trait class.

        A valid Trait must:
        - Be a class definition
        - Inherit from 'BaseTrait' or 'Trait'
        - Have an async method named 'execute'
        - execute method must take 'self' and 'entity' parameters

        Args:
            tree: AST of the source code

        Returns:
            Name of the Trait class if valid, None otherwise
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Check if class inherits from BaseTrait or Trait
            inherits_trait = False
            for base in node.bases:
                if isinstance(base, ast.Name):
                    if base.id in ("BaseTrait", "Trait"):
                        inherits_trait = True
                        break

            if not inherits_trait:
                continue

            # Found a class inheriting from Trait, now check for execute method
            for item in node.body:
                if not isinstance(item, ast.AsyncFunctionDef):
                    continue

                if item.name != "execute":
                    continue

                # Check that execute has at least 2 parameters (self, entity)
                if len(item.args.args) < 2:
                    continue

                # Valid Trait class found!
                return node.name

        return None

    async def _check_duplicate(self, code_hash: str) -> bool:
        """Check if code hash already exists in Redis.

        Args:
            code_hash: SHA-256 hash of the code

        Returns:
            True if hash exists (duplicate), False otherwise
        """
        if not self._redis:
            return False

        try:
            exists = await self._redis.sismember("evo:mutation:hashes", code_hash)  # type: ignore[misc]
            return bool(exists)
        except Exception as exc:
            logger.error("redis_dedup_check_failed", error=str(exc))
            # On error, allow the code through (fail open for availability)
            return False

    async def mark_as_used(self, code_hash: str) -> None:
        """Add code hash to Redis to prevent future duplicates.

        Args:
            code_hash: SHA-256 hash of the code to mark as used

        Note:
            This should be called after successful mutation loading.
        """
        if not self._redis:
            return

        try:
            await self._redis.sadd("evo:mutation:hashes", code_hash)  # type: ignore[misc]
            logger.debug("mutation_hash_stored", code_hash=code_hash[:16])
        except Exception as exc:
            logger.error("redis_hash_store_failed", error=str(exc))
