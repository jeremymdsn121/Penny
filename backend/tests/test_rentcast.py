"""Tests for the pure parsing helpers in app.services.rentcast."""

from app.services import rentcast as rc


def test_compose_address():
    assert (
        rc.compose_address({"address": "1 A St", "city": "Austin", "state": "TX", "zip": "78701"})
        == "1 A St, Austin, TX 78701"
    )
    assert rc.compose_address({"address": "1 A St", "state": "TX"}) == "1 A St, TX"
    assert rc.compose_address({}) == ""


def test_num_only_accepts_numbers():
    assert rc._num(5) == 5
    assert rc._num(1.5) == 1.5
    assert rc._num("5") is None
    assert rc._num(None) is None


def test_parse_comparable_maps_fields():
    comp = rc._parse_comparable(
        {
            "formattedAddress": "1 A St",
            "price": 500000,
            "bedrooms": 3,
            "bathrooms": 2,
            "squareFootage": 1800,
            "yearBuilt": 1999,
            "propertyType": "Single Family",
            "distance": 0.5,
            "correlation": 0.9,
        }
    )
    assert comp["address"] == "1 A St"
    assert comp["price"] == 500000
    assert comp["square_footage"] == 1800
    assert comp["year_built"] == 1999
    # non-numeric / missing values normalize to None
    assert rc._parse_comparable({"price": "n/a"})["price"] is None


def test_year_series_sorted_newest_first():
    raw = {
        "2022": {"year": 2022, "value": 100},
        "2024": {"year": 2024, "value": 120},
        "2023": {"year": 2023, "value": 110},
        "bad": "not a dict",  # skipped
    }
    series = rc._year_series(raw, "value")
    assert [r["year"] for r in series] == [2024, 2023, 2022]
    assert series[0]["value"] == 120
    assert rc._year_series(None, "value") == []
