from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = json.loads((HERE / "inputs.json").read_text(encoding="utf-8"))
P = {entry["name"]: entry["value"] for entry in INPUTS["params"]}
CURVES = INPUTS["curves"]
SURCHARGE = INPUTS["consulting_surcharge"]
PRICES = list(range(100, 2001, 25))
CONSULT_PRICES = list(range(int(P["consult_band_low"]), int(P["consult_band_high"]) + 1, 25))


def share(spec: dict[str, float | str], price: int) -> float:
    kind = spec["type"]
    if kind == "linear":
        slope = 0.5 / (float(spec["p_half"]) - float(spec["p_all"]))
        return min(1.0, max(0.0, 1 - (price - float(spec["p_all"])) * slope))
    if kind == "uniform":
        return min(1.0, max(0.0, (float(spec["hi"]) - price) / (float(spec["hi"]) - float(spec["lo"]))))
    z = (math.log(price) - math.log(float(spec["median"]))) / float(spec["sigma"])
    return 0.5 * math.erfc(z / math.sqrt(2))


@dataclass(frozen=True)
class Case:
    curve: str
    free_users: int
    review_min: float
    conv: float
    mode: str
    fix_price: int | None = None
    min_revenue: int | None = None
    floor_objective: int | None = None
    price_direction: str | None = None


@dataclass(frozen=True)
class Tables:
    demand: list[int]
    consult_hundredths: list[int]
    review_seconds: int
    spot_seconds: int
    reviewer_cents_per_second: float
    owner_cents_per_second: float

    @property
    def review_cost(self) -> int:
        return int(round(self.review_seconds * self.reviewer_cents_per_second))

    @property
    def spot_cost(self) -> int:
        return int(round(self.spot_seconds * self.owner_cents_per_second))

    @property
    def consult_cost(self) -> int:
        return int(round(36 * self.owner_cents_per_second))


def tables(case: Case) -> Tables:
    pool = case.free_users * case.conv / 100.0
    return Tables(
        [int(round(pool * share(CURVES[case.curve], price))) for price in PRICES],
        [int(round(100 * P["consult_h_per_paid"] * share(SURCHARGE, price))) for price in CONSULT_PRICES],
        int(round(case.review_min * 60)),
        int(round(case.review_min * 60 * P["owner_spotcheck_pct"] / 100)),
        P["reviewer_rate"] / 36.0,
        P["owner_value"] / 36.0,
    )


def objective_terms(case: Case, table: Tables) -> list[tuple[int, str]]:
    revenue = [(100, "rev"), (1, "crev")]
    if case.mode == "revenue":
        return revenue
    return [*revenue, (-table.review_cost - table.spot_cost, "n"), (-table.consult_cost, "ch")]


def build(case: Case) -> dict[str, object]:
    table = tables(case)
    most = max(table.demand) + 1
    top_hours = max(table.consult_hundredths)
    objective = objective_terms(case, table)
    owner_seconds = int(P["owner_cap_h"] * 3600) - int(P["owner_eng_h"] * 3600)
    reviewer_seconds = int(P["reviewer_cap_h"] * 3600) - int(case.free_users * P["free_support_min"] * 60)

    def integer(name: str, hi: int, description: str) -> dict[str, object]:
        return {"name": name, "type": "int", "domain": {"lo": 0, "hi": hi}, "description": description}

    def structural(identifier: str, kind: str, args: dict[str, object]) -> dict[str, object]:
        return {"id": identifier, "kind": kind, "args": args, "strength": "structural", "category": "definition"}

    constraints: list[dict[str, object]] = [
        structural("price_table", "element", {"index": "pi", "values": PRICES, "target": "price"}),
        structural("demand_table", "element", {"index": "pi", "values": table.demand, "target": "d"}),
        structural("paid_within_demand", "linear", {"terms": [[1, "n"], [-1, "d"]], "op": "<=", "rhs": 0}),
        structural("revenue", "product", {"target": "rev", "factors": ["price", "n"]}),
        structural("consult_price_table", "element", {"index": "ci", "values": CONSULT_PRICES, "target": "cp"}),
        structural(
            "consult_demand_table", "element", {"index": "ci", "values": table.consult_hundredths, "target": "hc"}
        ),
        structural("consult_ceiling", "product", {"target": "ccap", "factors": ["n", "hc"]}),
        structural("consult_within_ceiling", "linear", {"terms": [[1, "ch"], [-1, "ccap"]], "op": "<=", "rhs": 0}),
        structural("consult_revenue", "product", {"target": "crev", "factors": ["cp", "ch"]}),
        {
            "id": "owner_hours",
            "kind": "linear",
            "args": {"terms": [[table.spot_seconds, "n"], [36, "ch"]], "op": "<=", "rhs": "param:owner_seconds"},
            "strength": "hard",
            "category": "assumption",
            "negotiable": False,
            "label": "The owner's spot checks and consulting fit in the owner's hours",
        },
        {
            "id": "reviewer_hours",
            "kind": "linear",
            "args": {"terms": [[table.review_seconds, "n"]], "op": "<=", "rhs": "param:reviewer_seconds"},
            "strength": "hard",
            "category": "assumption",
            "negotiable": False,
            "label": "Reviews and free-account support fit in the reviewers' hours",
        },
    ]
    if case.fix_price is not None:
        constraints.append(
            {
                "id": "fixed_price",
                "kind": "fix",
                "args": {"var": "price", "value": case.fix_price},
                "strength": "hard",
                "category": "desire",
                "label": f"The price is {case.fix_price}",
            }
        )
    if case.min_revenue is not None:
        constraints.append(
            {
                "id": "revenue_target",
                "kind": "linear",
                "args": {"terms": [[100, "rev"], [1, "crev"]], "op": ">=", "rhs": case.min_revenue * 100},
                "strength": "hard",
                "category": "goal",
                "label": f"Monthly revenue reaches {case.min_revenue}",
            }
        )
    if case.floor_objective is not None:
        constraints.append(
            structural(
                "objective_floor",
                "linear",
                {"terms": [[coef, name] for coef, name in objective], "op": ">=", "rhs": case.floor_objective},
            )
        )
    stated: dict[str, object] | None = {
        "sense": "max",
        "terms": [{"coef": coef, "var": name} for coef, name in objective],
    }
    if case.price_direction is not None:
        stated = {"sense": case.price_direction, "terms": [{"coef": 1, "var": "price"}]}
    elif case.min_revenue is not None:
        stated = None
    unsourced = "not sourced"
    return {
        "schema": "constraint-model.v1",
        "name": f"pricing-{case.curve}-{case.free_users}-{case.review_min}-{case.conv}-{case.mode}",
        "description": "Price of a reviewed tier and of a consulting surcharge, under an assumed demand curve.",
        "variables": [
            integer("pi", len(PRICES) - 1, "Which price in the price table"),
            integer("price", max(PRICES), "Monthly price of the reviewed tier"),
            integer("d", most, "Accounts willing to pay that price"),
            integer("n", most, "Paid customers"),
            integer("rev", most * max(PRICES), "Subscription revenue per month"),
            integer("ci", len(CONSULT_PRICES) - 1, "Which price in the consulting price table"),
            integer("cp", max(CONSULT_PRICES), "Consulting price per hour"),
            integer("hc", top_hours, "Consulting hours wanted per paid customer, in hundredths"),
            integer("ccap", most * top_hours, "Ceiling on consulting hours, in hundredths"),
            integer("ch", most * top_hours, "Consulting hours sold, in hundredths"),
            integer("crev", most * top_hours * max(CONSULT_PRICES), "Consulting revenue per month, in cents"),
        ],
        "params": [
            {
                "name": "owner_seconds",
                "value": owner_seconds,
                "unit": "seconds per month",
                "description": "Owner hours left after fixed work",
            },
            {
                "name": "reviewer_seconds",
                "value": reviewer_seconds,
                "unit": "seconds per month",
                "description": "Reviewer hours left after free-account support",
            },
        ],
        "constraints": constraints,
        "evidence": [
            {
                "target": {"param": "owner_seconds"},
                "source": unsourced,
                "confidence": "assumption",
                "quote": "owner_cap_h minus owner_eng_h",
            },
            {
                "target": {"param": "reviewer_seconds"},
                "source": unsourced,
                "confidence": "assumption",
                "quote": "reviewer_cap_h minus free-account support",
            },
            {
                "target": {"constraint": "demand_table"},
                "source": unsourced,
                "confidence": "assumption",
                "quote": f"willingness-to-pay curve {case.curve}; its shape is an assumption",
            },
        ],
        "objective": stated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="build_model.py")
    parser.add_argument("--curve", choices=sorted(CURVES), default="lognorm_250")
    parser.add_argument("--free-users", type=int, default=1000)
    parser.add_argument("--review-min", type=float, default=22.5)
    parser.add_argument("--conv", type=float, default=4.0)
    parser.add_argument("--mode", choices=("revenue", "profit"), default="profit")
    chosen = parser.parse_args()
    case = Case(chosen.curve, chosen.free_users, chosen.review_min, chosen.conv, chosen.mode)
    sys.stdout.write(json.dumps({"model": build(case)}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
