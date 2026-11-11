"""UPI payment links: your UPI app (GPay, PhonePe, Paytm, BHIM...) opens with the payee and
amount filled in, and you approve with your UPI PIN. We never touch the money or the PIN.

Uses the standard UPI deep link (upi://pay, NPCI's linking spec); the same text works as a
UPI QR code for scanning from a computer screen.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import quote

VPA = re.compile(r"^[A-Za-z0-9.\-_]{2,256}@[A-Za-z][A-Za-z0-9.\-]{1,64}$")
MAX_AMOUNT = Decimal("100000")  # typical per-transaction UPI limit (₹1 lakh)


@dataclass(frozen=True)
class UpiLink:
    url: str
    vpa: str
    name: str
    amount: str  # "500.00", or "" to let the payer type it
    note: str


def build(vpa: str, name: str = "", amount: str | float | None = None, note: str = "") -> UpiLink:
    vpa = (vpa or "").strip()
    if not VPA.match(vpa):
        raise ValueError("that isn't a UPI ID (like name@okhdfcbank); ask for their UPI ID")
    amt = ""
    if amount not in (None, ""):
        try:
            value = Decimal(str(amount).replace(",", "").replace("₹", "").strip())
        except InvalidOperation as exc:
            raise ValueError("the amount should be a number of rupees") from exc
        if value <= 0 or value > MAX_AMOUNT:
            raise ValueError("the amount must be between ₹1 and ₹1,00,000")
        amt = str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    name = " ".join((name or "").split())[:50]
    note = " ".join((note or "").split())[:50]
    params = [f"pa={quote(vpa, safe='@.-_')}"]
    if name:
        params.append(f"pn={quote(name)}")
    if amt:
        params.append(f"am={amt}")
    params.append("cu=INR")
    if note:
        params.append(f"tn={quote(note)}")
    return UpiLink(url="upi://pay?" + "&".join(params), vpa=vpa, name=name, amount=amt, note=note)
