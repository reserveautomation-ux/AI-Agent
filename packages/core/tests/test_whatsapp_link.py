import pytest
from workforce_core.whatsapp_link import build, default_country_for, normalise_number


def test_numbers():
    assert normalise_number("98765 43210") == "919876543210"
    assert normalise_number("+91 98765-43210") == "919876543210"
    assert normalise_number("09876543210") == "919876543210"
    assert normalise_number("0044 7700 900123") == "447700900123"
    assert normalise_number("+1 (415) 555-0100") == "14155550100"
    assert normalise_number("") == ""
    with pytest.raises(ValueError):
        normalise_number("12345")


def test_links():
    link = build("98765 43210", "Running 10 min late 🙏 & sorry")
    assert (
        link.url
        == "https://wa.me/919876543210?text=Running%2010%20min%20late%20%F0%9F%99%8F%20%26%20sorry"
    )
    assert link.to == "+919876543210"
    # No number: WhatsApp opens with the text and lets you pick the contact.
    assert build("", "Hi").url == "https://wa.me/?text=Hi"
    with pytest.raises(ValueError):
        build("9876543210", "  ")
    assert default_country_for("Europe/London") == "44" and default_country_for(None) == "91"
