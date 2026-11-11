import pytest
from workforce_core.upi_link import build


def test_upi_links():
    link = build("ramesh.k@okhdfcbank", "Ramesh Kumar", "₹1,500", "Rent Nov")
    assert (
        link.url
        == "upi://pay?pa=ramesh.k@okhdfcbank&pn=Ramesh%20Kumar&am=1500.00&cu=INR&tn=Rent%20Nov"
    )
    assert link.amount == "1500.00"
    assert build("9876543210@ybl").url == "upi://pay?pa=9876543210@ybl&cu=INR"
    for bad in ("ramesh", "ramesh@", "@ybl", "a b@ybl"):
        with pytest.raises(ValueError, match="UPI ID"):
            build(bad, amount=10)
    for bad in ("0", "-5", "200000", "ten"):
        with pytest.raises(ValueError):
            build("a@ybl", amount=bad)
