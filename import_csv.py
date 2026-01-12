import csv
from app import db, Item, app

with app.app_context():
    with open("items.csv", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        print("CSV 컬럼:", reader.fieldnames)  # 🔍 확인용

        for row in reader:
            print(row)  # 🔍 한 줄 출력
            item = Item(
    name=row["name"],
    spec=row["spec"],
    quantity=int(row["quantity"]) if row["quantity"].strip() != "" else 0
)
            db.session.add(item)

        db.session.commit()

print("엑셀 데이터 DB 저장 완료")
