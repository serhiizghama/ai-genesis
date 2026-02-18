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

from backend.agents.entity_api import ALLOWED_ENTITY_ATTRS  # single source of truth

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


# Python builtins available without import — used by unbound-name check
_PYTHON_BUILTINS = {
    "True", "False", "None",
    "int", "float", "str", "bool", "list", "dict", "set", "tuple", "bytes",
    "range", "len", "min", "max", "abs", "round", "sum", "any", "all",
    "zip", "enumerate", "isinstance", "issubclass", "type", "id",
    "sorted", "reversed", "filter", "map", "iter", "next",
    "hasattr", "getattr", "setattr", "delattr", "callable",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "StopIteration", "NotImplementedError",
    "__name__", "__class__", "__doc__",
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

        # Level 4: Module reference check (catches e.g. @dataclasses.dataclass without import)
        ref_error = self._check_undefined_module_refs(tree)
        if ref_error:
            logger.warning("validation_failed_undefined_ref", error=ref_error)
            return ValidationResult(
                is_valid=False,
                error=ref_error,
                code_hash=code_hash,
            )

        # Level 4.5: Unbound variable check in execute()
        unbound_error = self._check_unbound_vars_in_execute(tree)
        if unbound_error:
            logger.warning("validation_failed_unbound_var", error=unbound_error)
            return ValidationResult(
                is_valid=False,
                error=unbound_error,
                code_hash=code_hash,
            )

        # Level 5a: Entity attribute whitelist
        entity_attr_error = self._check_entity_attributes(tree)
        if entity_attr_error:
            logger.warning("validation_failed_entity_attr", error=entity_attr_error)
            return ValidationResult(
                is_valid=False,
                error=entity_attr_error,
                code_hash=code_hash,
            )

        # Level 5b: __init__ signature check (no required args beyond self)
        init_sig_error = self._check_init_signature(tree)
        if init_sig_error:
            logger.warning("validation_failed_init_sig", error=init_sig_error)
            return ValidationResult(
                is_valid=False,
                error=init_sig_error,
                code_hash=code_hash,
            )

        # Level 5c: Await on sync entity methods
        await_error = self._check_await_on_entity_methods(tree)
        if await_error:
            logger.warning("validation_failed_await_entity", error=await_error)
            return ValidationResult(
                is_valid=False,
                error=await_error,
                code_hash=code_hash,
            )

        # Level 5: Trait contract validation
        trait_class_name = self._check_trait_contract(tree)
        if not trait_class_name:
            error = "No valid Trait class found (must inherit from BaseTrait/Trait and have async execute(self, entity) method)"
            logger.warning("validation_failed_contract", error=error)
            return ValidationResult(
                is_valid=False,
                error=error,
                code_hash=code_hash,
            )

        # Level 6: Deduplication check (if Redis available)
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

    def _check_undefined_module_refs(self, tree: ast.AST) -> Optional[str]:
        """Check for module names used via attribute access without being imported.

        Catches patterns like @dataclasses.dataclass when 'import dataclasses'
        is missing.

        Args:
            tree: AST of the source code

        Returns:
            Error message if undefined module reference found, None otherwise
        """
        # Collect all imported top-level names
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split(".")[0]
                    imported_names.add(name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imported_names.add(name)

        # Check for known module names used as attribute prefixes without import
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                ref_name = node.value.id
                if ref_name in ALLOWED_IMPORTS and ref_name not in imported_names:
                    return (
                        f"Used '{ref_name}.{node.attr}' but '{ref_name}' is not imported. "
                        f"Add 'import {ref_name}' at the top."
                    )

        return None

    def _check_unbound_vars_in_execute(self, tree: ast.AST) -> Optional[str]:
        """Detect variables used before guaranteed assignment in execute().

        Catches the common LLM pattern:
            if random.random() < 0.1:
                dx = something      # only assigned here (90% chance it doesn't run)
            entity.x += dx          # UnboundLocalError at runtime

        Strategy:
        - Collect names "definitely assigned" at the top level of execute() body
          (unconditional assignments, for-loop targets, function arguments).
        - Collect all names stored anywhere in the function.
        - potentially_unbound = all_assigned - definitely_assigned
        - Walk top-level statements (skipping if/for/while/try bodies) for Loads
          of potentially_unbound names. A Load here means the variable is used
          outside its conditional block → runtime error.

        Args:
            tree: AST of the source code

        Returns:
            Error message if potentially unbound variable found, None otherwise
        """
        for class_node in ast.walk(tree):
            if not isinstance(class_node, ast.ClassDef):
                continue
            if not any(
                isinstance(b, ast.Name) and b.id in ("BaseTrait", "Trait")
                for b in class_node.bases
            ):
                continue

            for method in class_node.body:
                if not isinstance(method, ast.AsyncFunctionDef) or method.name != "execute":
                    continue

                # Names definitely assigned at the top level of execute()
                definite: set[str] = {arg.arg for arg in method.args.args}
                for stmt in method.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            for n in ast.walk(target):
                                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                                    definite.add(n.id)
                    elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
                        definite.add(stmt.target.id)
                    elif (
                        isinstance(stmt, ast.AnnAssign)
                        and stmt.value is not None
                        and isinstance(stmt.target, ast.Name)
                    ):
                        definite.add(stmt.target.id)
                    elif isinstance(stmt, ast.For):
                        for n in ast.walk(stmt.target):
                            if isinstance(n, ast.Name):
                                definite.add(n.id)

                # All names stored anywhere in the function
                all_assigned: set[str] = set()
                for n in ast.walk(method):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                        all_assigned.add(n.id)

                potentially_unbound = all_assigned - definite

                # Check top-level statements (skip conditional/loop bodies)
                # for Loads of potentially_unbound names
                _CONDITIONAL_STMTS = (
                    ast.If, ast.For, ast.AsyncFor, ast.While,
                    ast.Try, ast.With, ast.AsyncWith,
                )
                if potentially_unbound:
                    for stmt in method.body:
                        if isinstance(stmt, _CONDITIONAL_STMTS):
                            continue
                        for n in ast.walk(stmt):
                            if (
                                isinstance(n, ast.Name)
                                and isinstance(n.ctx, ast.Load)
                                and n.id in potentially_unbound
                            ):
                                return (
                                    f"Potentially unbound variable '{n.id}' in execute(): "
                                    f"assigned only inside a conditional/loop block "
                                    f"but used unconditionally (UnboundLocalError risk)"
                                )

                # Check for names used anywhere in execute() but NEVER defined
                # (not assigned, not an arg, not a builtin, not a module-level name)
                module_names: set[str] = set()
                for top in tree.body:  # type: ignore[attr-defined]
                    if isinstance(top, (ast.Import, ast.ImportFrom)):
                        for alias in top.names:
                            module_names.add(alias.asname or alias.name.split(".")[0])
                    elif isinstance(top, ast.ClassDef):
                        module_names.add(top.name)

                func_args = {arg.arg for arg in method.args.args}
                allowed = all_assigned | func_args | module_names | _PYTHON_BUILTINS

                for n in ast.walk(method):
                    if (
                        isinstance(n, ast.Name)
                        and isinstance(n.ctx, ast.Load)
                        and n.id not in allowed
                    ):
                        return (
                            f"Name '{n.id}' is used in execute() but never defined "
                            f"(NameError at runtime)"
                        )

        return None

    def _check_entity_attributes(self, tree: ast.AST) -> Optional[str]:
        """Check that code only accesses whitelisted attributes on 'entity'.

        Args:
            tree: AST of the source code

        Returns:
            Error message if forbidden entity attribute found, None otherwise
        """
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "entity"
                and node.attr not in ALLOWED_ENTITY_ATTRS
            ):
                return f"Forbidden entity attribute: entity.{node.attr} (allowed: {', '.join(sorted(ALLOWED_ENTITY_ATTRS))})"

        return None

    def _check_init_signature(self, tree: ast.AST) -> Optional[str]:
        """Check that Trait __init__ methods have no required parameters beyond self.

        Traits are instantiated without arguments, so any required parameters
        would cause an error at spawn time.

        Args:
            tree: AST of the source code

        Returns:
            Error message if __init__ has required args, None otherwise
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Only check classes inheriting from BaseTrait or Trait
            inherits_trait = any(
                isinstance(base, ast.Name) and base.id in ("BaseTrait", "Trait")
                for base in node.bases
            )
            if not inherits_trait:
                continue

            for item in node.body:
                if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                    continue

                args = item.args
                # n_required = total_args - 1 (self) - defaults
                n_total = len(args.args)
                n_defaults = len(args.defaults)
                n_required = n_total - 1 - n_defaults

                if n_required > 0:
                    required_names = [
                        a.arg for a in args.args[1 : n_total - n_defaults]
                    ]
                    return (
                        f"Traits instantiated without args, __init__ requires: "
                        f"{required_names}"
                    )

        return None

    def _check_await_on_entity_methods(self, tree: ast.AST) -> Optional[str]:
        """Detect 'await entity.<method>(...)' where entity methods are synchronous.

        All entity methods (move, eat_nearby, attack_nearby, is_alive, etc.) are
        regular sync methods. Awaiting them raises TypeError at runtime.

        Args:
            tree: AST of the source code

        Returns:
            Error message if await on entity method found, None otherwise
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Await):
                continue
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "entity"
            ):
                method = call.func.attr
                return (
                    f"Do not use 'await entity.{method}()' — entity methods are synchronous. "
                    f"Use 'entity.{method}(...)' without await."
                )
        return None

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
