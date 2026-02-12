from datetime import date
from typing import List, Dict

def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31,
                      29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month-1])
    return date(year, month, day)

def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def schedule_declining(principal: float, r: float, n: int, start_date: date) -> List[Dict]:
    """
    Interés sobre saldo (capital fijo). Ajusta la última cuota para neutralizar residuos por redondeo.
    """
    cap_fixed = round(principal / n, 2)
    saldo = round(principal, 2)
    items: List[Dict] = []

    for i in range(1, n + 1):
        interest = round(saldo * r, 2)
        if i < n:
            capital = cap_fixed
        else:
            capital = round(saldo, 2)
        total = round(capital + interest, 2)
        due = add_months(start_date, i - 1)
        items.append({
            "number": i, "due_date": iso(due),
            "capital": capital, "interest": interest, "total": total
        })
        saldo = max(0.0, round(saldo - capital, 2))

    if saldo != 0:
        last = items[-1]
        adjust = round(saldo, 2)
        last["capital"] = round(last["capital"] + adjust, 2)
        last["total"] = round(last["capital"] + last["interest"], 2)
    return items

def schedule_french(principal: float, r: float, n: int, start_date: date) -> List[Dict]:
    """
    Sistema francés (cuota fija). Ajusta la última cuota para evitar residuos por redondeo.
    """
    if r == 0:
        cuota = round(principal / n, 2)
    else:
        cuota = round(principal * (r / (1 - (1 + r) ** (-n))), 2)

    saldo = round(principal, 2)
    items: List[Dict] = []

    for i in range(1, n + 1):
        interest = round(saldo * r, 2)
        if i < n:
            capital = round(cuota - interest, 2)
            total_i = cuota
        else:
            capital = round(saldo, 2)
            total_i = round(capital + interest, 2)
        due = add_months(start_date, i - 1)
        items.append({
            "number": i, "due_date": iso(due),
            "capital": capital, "interest": interest, "total": total_i
        })
        saldo = max(0.0, round(saldo - capital, 2))

    if saldo != 0:
        last = items[-1]
        adjust = round(saldo, 2)
        last["capital"] = round(last["capital"] + adjust, 2)
        last["total"] = round(last["capital"] + last["interest"], 2)
    return items
