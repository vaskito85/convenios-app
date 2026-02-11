from datetime import date

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

def schedule_declining(principal: float, r: float, n: int, start_date: date):
    cap_fixed = round(principal / n, 2)
    saldo = principal
    items = []
    for i in range(1, n+1):
        interest = round(saldo * r, 2)
        total = round(cap_fixed + interest, 2)
        due = add_months(start_date, i-1)
        items.append({
            "number": i, "due_date": iso(due),
            "capital": cap_fixed, "interest": interest, "total": total
        })
        saldo = max(0.0, round(saldo - cap_fixed, 2))
    return items

def schedule_french(principal: float, r: float, n: int, start_date: date):
    if r == 0:
        cuota = round(principal / n, 2)
    else:
        cuota = round(principal * (r / (1 - (1 + r) ** (-n))), 2)
    saldo = principal
    items = []
    for i in range(1, n+1):
        interest = round(saldo * r, 2)
        capital = round(cuota - interest, 2)
        if i == n:
            capital = round(saldo, 2)
            cuota_i = round(capital + interest, 2)
        else:
            cuota_i = cuota
        due = add_months(start_date, i-1)
        items.append({
            "number": i, "due_date": iso(due),
            "capital": capital, "interest": interest, "total": cuota_i
        })
        saldo = max(0.0, round(saldo - capital, 2))
    return items