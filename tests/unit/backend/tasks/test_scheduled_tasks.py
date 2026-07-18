"""
Unit tests for scheduled background tasks.

Tests task logic in isolation without requiring Redis.
Task functions are imported directly from the scheduled module,
bypassing the broker registration which requires Redis.
"""

import pytest

from modules.backend.tasks.scheduled import (
    daily_cleanup,
    hourly_health_check,
    metrics_aggregation,
    weekly_report_generation,
)


class TestDailyCleanup:
    """Tests for daily_cleanup task."""

    @pytest.mark.asyncio
    async def test_daily_cleanup_returns_completion_status(self):
        """Task returns completion status with metadata."""
        result = await daily_cleanup(older_than_days=30)

        assert result["status"] == "completed"
        assert result["older_than_days"] == 30
        assert "tables_cleaned" in result
        assert "completed_at" in result

    @pytest.mark.asyncio
    async def test_daily_cleanup_default_retention(self):
        """Default retention is 30 days."""
        result = await daily_cleanup()

        assert result["older_than_days"] == 30

    @pytest.mark.asyncio
    async def test_daily_cleanup_custom_retention(self):
        """Custom retention period is respected."""
        result = await daily_cleanup(older_than_days=7)

        assert result["older_than_days"] == 7


class TestHourlyHealthCheck:
    """Tests for hourly_health_check task."""

    @pytest.mark.asyncio
    async def test_hourly_health_check_returns_status(self):
        """Task returns health check status."""
        result = await hourly_health_check()

        assert result["status"] in ("healthy", "degraded")
        assert "checks" in result
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_hourly_health_check_includes_services(self):
        """Health check includes expected services."""
        result = await hourly_health_check()

        checks = result["checks"]
        assert "database" in checks
        assert "redis" in checks


class TestWeeklyReportGeneration:
    """Tests for weekly_report_generation task."""

    @pytest.mark.asyncio
    async def test_weekly_report_returns_status(self):
        """Task returns report generation status."""
        result = await weekly_report_generation()

        assert result["status"] == "completed"
        assert "reports_generated" in result
        assert "generated_at" in result

    @pytest.mark.asyncio
    async def test_weekly_report_includes_reports_list(self):
        """Result includes reports_generated list."""
        result = await weekly_report_generation()

        assert "reports_generated" in result
        assert isinstance(result["reports_generated"], list)


class TestMetricsAggregation:
    """Tests for metrics_aggregation task."""

    @pytest.mark.asyncio
    async def test_metrics_aggregation_returns_status(self):
        """Task returns aggregation status."""
        result = await metrics_aggregation(interval_minutes=15)

        assert result["status"] == "completed"
        assert result["interval_minutes"] == 15
        assert "metrics_aggregated" in result
        assert "aggregated_at" in result

    @pytest.mark.asyncio
    async def test_metrics_aggregation_default_interval(self):
        """Default interval is 15 minutes."""
        result = await metrics_aggregation()

        assert result["interval_minutes"] == 15

    @pytest.mark.asyncio
    async def test_metrics_aggregation_custom_interval(self):
        """Custom interval is respected."""
        result = await metrics_aggregation(interval_minutes=5)

        assert result["interval_minutes"] == 5

    # TestScheduledTasksConfiguration removed — SCHEDULED_TASKS dict was deleted
    # when TaskIQ was replaced by Temporal Schedules (Plan 56 Phase C).
    # Schedule configuration is now in main.py lifespan (Temporal Schedules).
