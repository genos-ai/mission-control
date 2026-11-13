"""`mc mission create` budget flags, `mc mission budget` and `mc mission set-budget` (88.4.1)."""

from typing import Any

from click.testing import CliRunner

from modules.clients.cli.mc_groups.mission import mission
from tests.unit.clients.cli.test_mc_schedule import MISSION_ID, FakeApi, patch_api

USER_ID = "11111111-1111-1111-1111-111111111111"
BUDGET = {
    "per_run_usd": 5.0,
    "per_month_usd": 50.0,
    "lifetime_usd": None,
    "month_spent_usd": 12.5,
    "lifetime_spent_usd": 40.0,
    "active_run_spent_usd": 0.0,
    "breach": "budget_monthly_cap",
}


class BudgetApi(FakeApi):
    """FakeApi with PUT, answering with ``reply``."""

    async def put(self, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append(("PUT", path, {"body": body}))
        return self.reply


def _invoke(api: FakeApi, args: list[str]):
    with patch_api("modules.clients.cli.mc_groups.mission", api):
        return CliRunner().invoke(mission, args)


def test_create_sends_budget_flags():
    api = BudgetApi(routes={"/auth/me": {"id": USER_ID}}, reply={"id": MISSION_ID, "name": "b"})

    result = _invoke(
        api,
        [
            "create",
            "--name",
            "b",
            "--description",
            "Budget flags",
            "--gate-mode",
            "manual",
            "--budget-per-run",
            "2.5",
            "--budget-per-month",
            "25",
            "--budget-lifetime",
            "250",
        ],
    )

    assert result.exit_code == 0, result.output
    path, kwargs = api.last("POST")
    assert path == "/missions"
    body = kwargs["body"]
    assert (
        body["budget_per_run_usd"],
        body["budget_per_month_usd"],
        body["budget_lifetime_usd"],
    ) == (2.5, 25.0, 250.0)


def test_create_omits_unset_budget_flags():
    api = BudgetApi(routes={"/auth/me": {"id": USER_ID}}, reply={"id": MISSION_ID, "name": "b"})

    result = _invoke(
        api, ["create", "--name", "b", "--description", "Defaults", "--gate-mode", "manual"]
    )

    assert result.exit_code == 0, result.output
    body = api.last("POST")[1]["body"]
    assert not {"budget_per_run_usd", "budget_per_month_usd", "budget_lifetime_usd"} & set(body)


def test_set_budget_puts_caps():
    api = BudgetApi(reply=BUDGET)

    result = _invoke(api, ["set-budget", "--per-run", "5", "--per-month", "50", "--no-lifetime"])

    assert result.exit_code == 0, result.output
    path, kwargs = api.last("PUT")
    assert path == f"/missions/{MISSION_ID}/budget"
    assert kwargs["body"] == {"per_run_usd": 5.0, "per_month_usd": 50.0, "lifetime_usd": None}
    assert "budget_monthly_cap" in result.output


def test_set_budget_requires_one_lifetime_choice():
    api = BudgetApi(reply=BUDGET)

    result = _invoke(api, ["set-budget", "--per-run", "5", "--per-month", "50"])

    assert result.exit_code != 0
    assert not [call for call in api.calls if call[0] == "PUT"]


def test_budget_shows_caps_and_spend():
    api = BudgetApi(routes={f"/missions/{MISSION_ID}/budget": BUDGET})

    result = _invoke(api, ["budget"])

    assert result.exit_code == 0, result.output
    assert "$12.50" in result.output
    assert "no limit" in result.output
