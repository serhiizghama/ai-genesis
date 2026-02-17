"""Tests for evolution and mutation API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from backend.api.app import create_app
from backend.core.engine import CoreEngine
from backend.core.entity_manager import EntityManager
from backend.core.environment import Environment
from backend.core.world_physics import WorldPhysics
from backend.core.dynamic_registry import DynamicRegistry
from backend.config import Settings


@pytest.fixture
def mock_redis():
    """Create a mock Redis connection."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    # Mock scan_iter to return async iterator directly (not as return_value)
    redis.scan_iter = MagicMock(return_value=AsyncIterator([]))
    return redis


class AsyncIterator:
    """Helper class for async iteration in tests."""

    def __init__(self, items):
        self.items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def test_app(mock_redis):
    """Create a test FastAPI application."""
    settings = Settings()

    # Create components
    entity_manager = EntityManager(
        world_width=settings.world_width,
        world_height=settings.world_height,
    )

    environment = Environment(
        world_width=settings.world_width,
        world_height=settings.world_height,
        initial_resources=100,
        resource_energy=50.0,
    )

    physics = WorldPhysics(
        world_width=settings.world_width,
        world_height=settings.world_height,
        friction_coefficient=0.98,
        boundary_mode="bounce",
    )

    registry = DynamicRegistry()

    # Create engine
    engine = CoreEngine(
        entity_manager=entity_manager,
        environment=environment,
        physics=physics,
        registry=registry,
        redis=mock_redis,
        settings=settings,
    )

    # Create app
    app = create_app(engine=engine, redis=mock_redis)
    return app


@pytest.fixture
def client(test_app):
    """Create a test client."""
    return TestClient(test_app)


def test_trigger_evolution_success(client, mock_redis):
    """Test successful manual evolution trigger."""
    with patch("backend.api.routes_evolution.EventBus") as MockEventBus:
        mock_bus = MagicMock()
        mock_bus.publish = AsyncMock()
        MockEventBus.return_value = mock_bus

        response = client.post("/api/evolution/trigger")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert "trigger_id" in data
        assert data["trigger_id"].startswith("manual_")
        assert "Evolution cycle triggered" in data["message"]

        # Verify event was published
        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args[0]
        assert call_args[0] == "ch:evolution:force"


def test_trigger_evolution_no_redis(client):
    """Test evolution trigger fails when Redis unavailable."""
    # Override Redis to None
    client.app.state.app_state.redis = None

    response = client.post("/api/evolution/trigger")

    assert response.status_code == 503
    assert "Redis not available" in response.json()["detail"]


def test_get_mutations_empty_list(client, mock_redis):
    """Test getting mutations when none exist."""
    # Mock scan_iter to return empty list
    mock_redis.scan_iter = MagicMock(return_value=AsyncIterator([]))

    response = client.get("/api/mutations")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 0
    assert data["mutations"] == []


def test_get_mutations_with_data(client, mock_redis):
    """Test getting mutations with existing data."""
    # Mock Redis to return mutation keys
    mock_keys = [b"evo:mutation:test_123", b"evo:mutation:test_456"]
    mock_redis.scan_iter = MagicMock(return_value=AsyncIterator(mock_keys))

    # Mock hgetall to return mutation data
    async def mock_hgetall(key):
        # Decode key if bytes
        key_str = key.decode() if isinstance(key, bytes) else str(key)

        if "test_123" in key_str:
            return {
                b"mutation_id": b"test_123",
                b"trait_name": b"TestTrait1",
                b"version": b"1",
                b"status": b"applied",
                b"timestamp": b"1234567890.0",
                b"code_hash": b"abc123",
            }
        elif "test_456" in key_str:
            return {
                b"mutation_id": b"test_456",
                b"trait_name": b"TestTrait2",
                b"version": b"2",
                b"status": b"failed",
                b"timestamp": b"1234567900.0",
                b"code_hash": b"def456",
            }
        return {}

    mock_redis.hgetall = mock_hgetall

    response = client.get("/api/mutations")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 2
    assert len(data["mutations"]) == 2

    # Check first mutation (sorted by timestamp, newest first)
    mut1 = data["mutations"][0]
    assert mut1["trait_name"] == "TestTrait2"
    assert mut1["status"] == "failed"

    # Check second mutation
    mut2 = data["mutations"][1]
    assert mut2["trait_name"] == "TestTrait1"
    assert mut2["status"] == "applied"


def test_get_mutations_no_redis(client):
    """Test getting mutations fails when Redis unavailable."""
    client.app.state.app_state.redis = None

    response = client.get("/api/mutations")

    assert response.status_code == 503
    assert "Redis not available" in response.json()["detail"]


def test_get_mutation_source_success(client, mock_redis):
    """Test getting mutation source code."""
    mutation_id = "test_123"

    # Mock hgetall to return metadata
    async def mock_hgetall(key):
        if mutation_id in str(key):
            return {
                b"mutation_id": b"test_123",
                b"trait_name": b"TestTrait",
                b"version": b"1",
                b"status": b"applied",
            }
        return {}

    # Mock get to return source code
    async def mock_get(key):
        if "source" in str(key):
            return b"class TestTrait:\n    pass"
        return None

    mock_redis.hgetall = mock_hgetall
    mock_redis.get = mock_get

    response = client.get(f"/api/mutations/{mutation_id}/source")

    assert response.status_code == 200
    data = response.json()

    assert data["mutation_id"] == mutation_id
    assert data["trait_name"] == "TestTrait"
    assert data["status"] == "applied"
    assert "class TestTrait" in data["source_code"]


def test_get_mutation_source_not_found(client, mock_redis):
    """Test getting source for non-existent mutation."""
    mutation_id = "nonexistent"

    # Mock hgetall to return empty dict (not found)
    async def mock_hgetall(key):
        return {}

    mock_redis.hgetall = mock_hgetall

    response = client.get(f"/api/mutations/{mutation_id}/source")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_mutation_source_no_redis(client):
    """Test getting source fails when Redis unavailable."""
    client.app.state.app_state.redis = None

    response = client.get("/api/mutations/test_123/source")

    assert response.status_code == 503
    assert "Redis not available" in response.json()["detail"]


def test_get_mutation_source_with_file_fallback(client, mock_redis, tmp_path):
    """Test getting source code from file when not in Redis."""
    mutation_id = "test_123"

    # Create a temporary source file
    source_file = tmp_path / "test_trait.py"
    source_file.write_text("class TestTrait:\n    pass")

    # Mock hgetall to return metadata with file_path
    async def mock_hgetall(key):
        if mutation_id in str(key):
            return {
                b"mutation_id": b"test_123",
                b"trait_name": b"TestTrait",
                b"status": b"applied",
                b"file_path": str(source_file).encode(),
            }
        return {}

    # Mock get to return None (source not in Redis)
    async def mock_get(key):
        return None

    mock_redis.hgetall = mock_hgetall
    mock_redis.get = mock_get

    response = client.get(f"/api/mutations/{mutation_id}/source")

    assert response.status_code == 200
    data = response.json()

    assert data["mutation_id"] == mutation_id
    assert "class TestTrait" in data["source_code"]


def test_evolution_endpoints_in_openapi(client):
    """Test that evolution endpoints appear in OpenAPI schema."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    openapi = response.json()

    # Check that evolution endpoints are documented
    paths = openapi["paths"]
    assert "/api/evolution/trigger" in paths
    assert "/api/mutations" in paths
    assert "/api/mutations/{mutation_id}/source" in paths

    # Check POST trigger endpoint
    trigger_endpoint = paths["/api/evolution/trigger"]["post"]
    assert "evolution" in trigger_endpoint["tags"]

    # Check GET mutations endpoint
    mutations_endpoint = paths["/api/mutations"]["get"]
    assert "evolution" in mutations_endpoint["tags"]
