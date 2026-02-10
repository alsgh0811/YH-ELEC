from flask import Flask, render_template, request, redirect, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import csv
from io import TextIOWrapper

app = Flask(__name__)
app.secret_key = "super-secret-key"

# SQLite DB 설정
import os
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(10), default="user")  # admin / user
    is_active = db.Column(db.Boolean, default=False) # 승인 여부

# 자재 테이블 정의
class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    spec = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(100))

    histories = db.relationship(
        'History',
        backref='item'
    )

from datetime import datetime
class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    item_id = db.Column(
        db.Integer,
        db.ForeignKey('item.id', ondelete='SET NULL'),
        nullable=True
    )

    change_type = db.Column(db.String(10))   # IN / OUT
    quantity = db.Column(db.Integer)
    manager = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    with app.app_context():
        db.create_all()

    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(
            username="admin",
            password=generate_password_hash("admin1234"),
            role="admin",
            is_active=True
        )
        db.session.add(admin)
        db.session.commit()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")

        if session.get("role") != "admin":
            return "접근 권한이 없습니다.", 403
    
        return f(*args, **kwargs)
    return decorated_function   
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if not user:
            return render_template("login.html", error="아이디가 없습니다.")

        if not user.is_active:
            return render_template("login.html", error="관리자 승인 대기 중입니다.")

        if not check_password_hash(user.password, password):
            return render_template("login.html", error="비밀번호가 틀렸습니다.")

        # 로그인 성공
        session["user_id"] = user.id
        session["role"] = user.role

        return redirect("/")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        # 중복 아이디 체크
        existing = User.query.filter_by(username=username).first()
        if existing:
            return render_template(
                "register.html",
                error="이미 존재하는 아이디입니다."
            )

        # 승인 대기 상태로 사용자 생성
        user = User(
            username=username,
            password=generate_password_hash(password),
            role="user",
            is_active=False   # ❗ 관리자 승인 전까지 로그인 불가
        )

        db.session.add(user)
        db.session.commit()

        return render_template(
            "register.html",
            success="회원가입 완료! 관리자 승인 대기 중입니다."
        )

    return render_template("register.html")

@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/delete/<int:user_id>")
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    # ⚠️ 관리자 자신 삭제 방지
    if user.role == "admin":
        return "관리자는 삭제할 수 없습니다.", 403

    db.session.delete(user)
    db.session.commit()

    return redirect("/admin/users")

@app.route("/admin/approve/<int:user_id>")
@admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    return redirect("/admin/users")

@app.route("/admin/disable/<int:user_id>")
def disable_user(user_id):
    if session.get("role") != "admin":
        return redirect("/")

    user = User.query.get_or_404(user_id)

    if user.role == "admin":
        return redirect("/admin/users")

    user.is_active = False
    db.session.commit()
    return redirect("/admin/users")

@app.route("/upload_csv", methods=["GET", "POST"])
def upload_csv():
    if request.method == "POST":
        file = request.files["file"]

        if not file:
            return redirect("/upload_csv")

        stream = TextIOWrapper(file.stream, encoding="utf-8-sig")
        reader = csv.DictReader(stream)

        for row in reader:
            print(row)

            name = row.get("name", "").strip()
            spec = row.get("spec", "").strip()
            location = row.get("location", "").strip()

            qty_str = row.get("quantity", "").strip()

            # 필수값 체크
            if not name or not spec:
                continue

            # 수량 안전 처리
            if qty_str == "":
               quantity = 0
            else:
                try:
                   quantity = int(qty_str)
                except ValueError:
                   continue

            # 중복 자재 방지
            existing = Item.query.filter_by(name=name, spec=spec).first()
            if existing:
                continue
 
            item = Item(
            name=name,
            spec=spec,
            quantity=quantity,
            location=location  # 📍 위치 저장
            )
            db.session.add(item)
            db.session.commit()

            # 초기 이력 기록
            if quantity > 0:
               history = History(
                   item_id=item.id,
                   change_type="IN",
                   quantity=quantity,
                   manager="CSV등록"
               )
               db.session.add(history)
               db.session.commit()


        return redirect("/")

    return render_template("upload_csv.html")


@app.route("/")
@login_required
def index():
    error = request.args.get("error")
    name = request.args.get("name")
    spec = request.args.get("spec")

    query = Item.query

    if name:
        query = query.filter(Item.name.contains(name))

    if spec:
        query = query.filter(Item.spec.contains(spec))

    items = query.all()

    return render_template(
        "index.html",
        items=items,
        error=error
    )



@app.route("/add_item", methods=["GET", "POST"])
def add_item():
    if request.method == "POST":
        name = request.form["name"]
        spec = request.form["spec"]
        quantity = int(request.form["quantity"])
        location = request.form["location"]

        # ✅ 중복 체크
        existing = Item.query.filter_by(name=name, spec=spec).first()
        if existing:
            return redirect("/add_item")

        # ✅ 자재 등록
        item = Item(
            name=name,
            spec=spec,
            quantity=quantity,
            location=location
        )
        db.session.add(item)
        db.session.commit()

        # ✅ 초기 수량 이력 기록 (POST 안에서만!)
        if quantity > 0:
            history = History(
                item_id=item.id,
                change_type="IN",
                quantity=quantity,
                manager="초기등록"
            )
            db.session.add(history)
            db.session.commit()

        return redirect("/")

    # ✅ GET 요청은 여기서 끝
    return render_template("add_item.html")


@app.route("/delete_item/<int:item_id>")
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)

    if item.quantity != 0:
        return redirect("/")

    # 1️⃣ 삭제 이력 먼저 기록
    history = History(
        item_id=None,
        change_type="DELETE",
        quantity=0,
        manager="시스템"
    )
    db.session.add(history)

    # 2️⃣ 자재 삭제
    db.session.delete(item)

    # 3️⃣ 한 번에 커밋
    db.session.commit()

    return redirect("/")


@app.route("/edit_item/<int:item_id>", methods=["GET", "POST"])
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)

    if request.method == "POST":
        item.name = request.form["name"]
        item.spec = request.form["spec"]

        db.session.commit()
        return redirect("/")

    return render_template("edit_item.html", item=item)

@app.route("/update/<int:item_id>", methods=["POST"])
def update_item(item_id):
    item = Item.query.get_or_404(item_id)

    change_type = request.form["type"]
    quantity = int(request.form["quantity"])
    manager = request.form["manager"]

    if change_type == "OUT" and item.quantity < quantity:
        return redirect("/?error=not_enough")

    if change_type == "IN":
        item.quantity += quantity
    else:
        item.quantity -= quantity

    history = History(
        item_id=item.id,
        change_type=change_type,
        quantity=quantity,
        manager=manager
    )

    db.session.add(history)
    db.session.commit()

    return redirect("/")

from datetime import timedelta

@app.route("/history")
def history():
    histories = (
        db.session.query(History, Item)
        .outerjoin(Item, History.item_id == Item.id)
        .order_by(History.created_at.desc())
        .all()
    )

    # 한국시간으로 변환해서 새 리스트 생성
    kst_histories = []
    for history, item in histories:
        history.created_at_kst = history.created_at + timedelta(hours=9)
        kst_histories.append((history, item))

    return render_template("history.html", histories=kst_histories)

@app.route("/in/<int:item_id>")
def stock_in(item_id):
    item = Item.query.get(item_id)
    item.quantity += 1
    db.session.commit()
    return redirect("/")

@app.route("/out/<int:item_id>")
def stock_out(item_id):
    item = Item.query.get(item_id)
    if item.quantity > 0:
        item.quantity -= 1
        db.session.commit()
    return redirect("/")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()   # ✅ 1️⃣ 테이블 먼저 생성

        # ✅ 2️⃣ 그 다음 관리자 계정 생성
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(
                username="admin",
                password=generate_password_hash("admin1234"),
                role="admin",
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()

        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(
                username="admin",
                password=generate_password_hash("admin1234"),
                role="admin",
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()

    app.run(debug=True)


