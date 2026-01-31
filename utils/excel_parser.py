def parse_excel(file_path: str) -> List[Dict]:
    wb = load_workbook(file_path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        data = dict(zip(headers, row))
        rows.append(data)

    tasks = []

    # Поддержка шаблона выгрузки (админский формат)
    if "full_name" in headers and "task_description" in headers and "end_date" in headers:
        for r in rows:
            task = {
                "practice_name": r.get("practice_name"),
                "start_date": parse_date(r.get("start_date")),
                "end_date": parse_date(r.get("end_date")),
                "full_name": r.get("full_name"),
                "tg_username": r.get("tg_username"),
                "phone": r.get("phone"),
                "description": r.get("task_description"),
            }
            tasks.append(task)
    elif "practice_name" in headers and "full_name" in headers and "end_date" in headers:
        # Формат 1: Полный (для учебных планов)
        for r in rows:
            task = {
                "practice_name": r.get("practice_name"),
                "start_date": parse_date(r.get("start_date")),
                "end_date": parse_date(r.get("end_date")),
                "full_name": r.get("full_name"),
                "tg_username": r.get("tg_username"),
                "phone": r.get("phone"),
                "description": r.get("task_description") or r.get("practice_name") or "",
            }
            tasks.append(task)
    elif "full_name" in headers and "task_description" in headers and "end_date" in headers:
        # Формат 2: Краткий (для быстрых задач)
        for r in rows:
            task = {
                "practice_name": r.get("task_description"),
                "start_date": None,
                "end_date": parse_date(r.get("end_date")),
                "full_name": r.get("full_name"),
                "tg_username": None,
                "phone": None,
                "description": r.get("task_description"),
            }
            tasks.append(task)
    else:
        raise ValueError("Неизвестный формат Excel")

    return tasks