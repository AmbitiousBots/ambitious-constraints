from __future__ import annotations

import math
import sys
import unittest
from collections.abc import Mapping

import build_model
from build_model import PRICES, Case, P, build, tables

from ambitious_constraints.domain.analysis import Run, solution
from ambitious_constraints.domain.check import check
from ambitious_constraints.domain.model import compile_model
from tests.support import fixture, run

EXPECTED = fixture("pricing-expected.json")


def solved(case: Case, engine: Run) -> Mapping[str, object]:
    result = solution(build(case), {"name": "pricing", "digest": "0" * 64}, None, engine)
    assert result["checked"] == {"violations": []}, result["checked"]
    return result


def integers(result: Mapping[str, object]) -> dict[str, int]:
    values = result["values"]
    assert isinstance(values, dict)
    return {name: int(value) for name, value in values.items()}


def summary(case: Case, values: Mapping[str, int]) -> dict[str, float]:
    table = tables(case)
    paid, hours = values["n"], values["ch"] / 100
    revenue = values["rev"] + values["crev"] / 100
    reviewer_hours = (table.review_seconds * paid) / 3600 + case.free_users * P["free_support_min"] / 60
    owner_hours = table.spot_seconds * paid / 3600 + hours
    cash = revenue - reviewer_hours * P["reviewer_rate"]
    return {
        "revenue": round(revenue),
        "cash_profit": round(cash),
        "profit": round(cash - owner_hours * P["owner_value"]),
        "reach_target": int(revenue >= P["revenue_target"]),
    }


def recorded_values(case: Case, row: Mapping[str, object]) -> dict[str, int]:
    table = tables(case)
    price, paid, consult_price = int(str(row["price"])), int(str(row["paid"])), int(str(row["consult_price"]))
    hours = round(float(str(row["consult_h"])) * 100)
    index, consult_index = PRICES.index(price), build_model.CONSULT_PRICES.index(consult_price)
    wanted = table.consult_hundredths[consult_index]
    return {
        "pi": index,
        "price": price,
        "d": table.demand[index],
        "n": paid,
        "rev": price * paid,
        "ci": consult_index,
        "cp": consult_price,
        "hc": wanted,
        "ccap": paid * wanted,
        "ch": hours,
        "crev": consult_price * hours,
    }


class PricingRegression(unittest.TestCase):
    engine: Run

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = run()

    def test_every_recorded_row_is_reproduced(self) -> None:
        rows = EXPECTED["rows"]
        assert isinstance(rows, list)
        self.assertEqual(len(rows), 288)
        same_price = 0
        same_plan = 0
        for row in rows:
            case = Case(row["curve"], row["free_users"], row["review_min"], row["conv"], row["mode"])
            with self.subTest(case=case):
                best = solved(case, self.engine)
                self.assertEqual(best["status"], "optimal")
                values = integers(best)
                objective = best["objective"]
                assert isinstance(objective, int)
                model = compile_model(build(case))[0]
                recorded = check(model, recorded_values(case, row))
                self.assertEqual(recorded.violations, ())
                self.assertEqual(recorded.objective, objective)
                low = high = values["price"]
                if objective > 0:
                    floor = int(math.ceil(0.95 * objective))
                    low = integers(
                        solved(Case(*_base(case), floor_objective=floor, price_direction="min"), self.engine)
                    )["price"]
                    high = integers(
                        solved(Case(*_base(case), floor_objective=floor, price_direction="max"), self.engine)
                    )["price"]
                self.assertEqual((low, high), (row["flat_lo"], row["flat_hi"]))
                self.assertTrue(low <= values["price"] <= high)
                again = solved(Case(*_base(case), fix_price=row["price"]), self.engine)
                self.assertEqual(again["objective"], objective)
                same_price += values["price"] == row["price"]
                if (values["price"], values["n"], values["cp"], values["ch"]) == (
                    row["price"],
                    row["paid"],
                    row["consult_price"],
                    round(row["consult_h"] * 100),
                ):
                    same_plan += 1
                    self.assertEqual(
                        summary(case, values),
                        {key: row[key] for key in ("revenue", "cash_profit", "profit", "reach_target")},
                    )
        sys.stderr.write(f"pricing regression: 288 rows, same price in {same_price}, same full plan in {same_plan}\n")

    def test_fixed_price_points_are_reproduced(self) -> None:
        points = EXPECTED["points"]
        assert isinstance(points, dict)
        compared = 0
        for key, series in points.items():
            curve, _, free_users = key.partition("|")
            support = int(free_users) * P["free_support_min"] / 60 * P["reviewer_rate"]
            for price, _paid, value in series:
                case = Case(curve, int(free_users), P["review_min_base"], P["conv_base"], "profit", fix_price=price)
                objective = solved(case, self.engine)["objective"]
                assert isinstance(objective, int)
                self.assertAlmostEqual(objective / 100 - support, value, places=6, msg=f"{key} at {price}")
                compared += 1
        self.assertEqual(compared, 616)

    def test_free_accounts_needed_for_the_target_are_reproduced(self) -> None:
        needed = EXPECTED["free_users_needed_for_target"]
        assert isinstance(needed, dict)
        target = int(P["revenue_target"])
        for curve, by_review in needed.items():
            for review_min, expected in by_review.items():
                with self.subTest(curve=curve, review_min=review_min):

                    def reachable(free_users: int, curve: str = curve, review_min: str = review_min) -> bool:
                        case = Case(curve, free_users, float(review_min), P["conv_base"], "revenue", min_revenue=target)
                        return solved(case, self.engine)["status"] in ("optimal", "feasible")

                    low, high = 50, 10000
                    found = None
                    if reachable(high):
                        while high - low > 25:
                            middle = (low + high) // 2
                            if reachable(middle):
                                high = middle
                            else:
                                low = middle
                        found = high
                    self.assertEqual(found, expected)


def _base(case: Case) -> tuple[str, int, float, float, str]:
    return case.curve, case.free_users, case.review_min, case.conv, case.mode


if __name__ == "__main__":
    unittest.main()
