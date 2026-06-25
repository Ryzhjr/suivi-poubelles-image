from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from PIL import Image, ImageFilter, ImageStat
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Data"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "database.db"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}

app = Flask(__name__)
app.config["SECRET_KEY"] = "solution-factory-dev"
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    UPLOAD_DIR.mkdir(exist_ok=True)
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'upload',
                upload_date TEXT NOT NULL,
                location_address TEXT,
                latitude REAL,
                longitude REAL,
                location_accuracy REAL,
                manual_label TEXT,
                automatic_label TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                avg_red REAL NOT NULL,
                avg_green REAL NOT NULL,
                avg_blue REAL NOT NULL,
                brightness REAL NOT NULL,
                contrast REAL NOT NULL,
                edge_score REAL NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(images)").fetchall()
        }
        if "location_address" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN location_address TEXT")
        if "latitude" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN latitude REAL")
        if "longitude" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN longitude REAL")
        if "location_accuracy" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN location_accuracy REAL")
        conn.commit()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def relative_path(path):
    return path.resolve().relative_to(BASE_DIR).as_posix()


def extract_features(path):
    file_size = path.stat().st_size
    with Image.open(path) as img:
        img = img.convert("RGB")
        width, height = img.size
        stat = ImageStat.Stat(img)
        avg_red, avg_green, avg_blue = stat.mean

        grayscale = img.convert("L")
        gray_stat = ImageStat.Stat(grayscale)
        brightness = gray_stat.mean[0]
        contrast = gray_stat.stddev[0]

        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        edge_score = ImageStat.Stat(edges).mean[0]

    return {
        "file_size": file_size,
        "width": width,
        "height": height,
        "avg_red": round(avg_red, 2),
        "avg_green": round(avg_green, 2),
        "avg_blue": round(avg_blue, 2),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "edge_score": round(edge_score, 2),
    }


def classify_by_rules(features):
    brightness = features["brightness"]
    contrast = features["contrast"]
    edge_score = features["edge_score"]

    dirty_score = 0
    if brightness < 105:
        dirty_score += 1
    if contrast > 55:
        dirty_score += 1
    if edge_score > 18:
        dirty_score += 1
    if features["file_size"] > 750_000:
        dirty_score += 1

    if dirty_score >= 3:
        return "dirty"
    if dirty_score <= 1 and brightness >= 95:
        return "clean"
    return "unknown"


init_db()


def parse_optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def save_image_record(
    path,
    original_filename,
    manual_label=None,
    location_address=None,
    latitude=None,
    longitude=None,
    location_accuracy=None,
    source="upload",
):
    features = extract_features(path)
    automatic_label = classify_by_rules(features)
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO images (
                filename, original_filename, filepath, source, upload_date,
                location_address, latitude, longitude, location_accuracy,
                manual_label, automatic_label, file_size, width, height,
                avg_red, avg_green, avg_blue, brightness, contrast, edge_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                path.name,
                original_filename,
                relative_path(path),
                source,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                location_address,
                latitude,
                longitude,
                location_accuracy,
                manual_label,
                automatic_label,
                features["file_size"],
                features["width"],
                features["height"],
                features["avg_red"],
                features["avg_green"],
                features["avg_blue"],
                features["brightness"],
                features["contrast"],
                features["edge_score"],
            ),
        )
        conn.commit()
        return cursor.lastrowid


def image_exists_by_source(source, original_filename):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM images WHERE source = ? AND original_filename = ?",
            (source, original_filename),
        ).fetchone()
    return row is not None


def get_image(image_id):
    with get_db() as conn:
        return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


def get_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM images").fetchone()["count"]
        manual_rows = conn.execute(
            "SELECT COALESCE(manual_label, 'non_annotee') AS label, COUNT(*) AS count FROM images GROUP BY label"
        ).fetchall()
        auto_rows = conn.execute(
            "SELECT automatic_label AS label, COUNT(*) AS count FROM images GROUP BY automatic_label"
        ).fetchall()
        recent = conn.execute(
            "SELECT * FROM images ORDER BY id DESC LIMIT 6"
        ).fetchall()

    manual = {row["label"]: row["count"] for row in manual_rows}
    automatic = {row["label"]: row["count"] for row in auto_rows}
    return {
        "total": total,
        "manual": manual,
        "automatic": automatic,
        "recent": recent,
    }


@app.context_processor
def inject_helpers():
    return {"format_size": format_size}


def format_size(size):
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} Mo"
    return f"{size / 1024:.1f} Ko"


@app.route("/")
def dashboard():
    stats = get_stats()
    return render_template("dashboard.html", stats=stats)


@app.route("/api/stats")
def api_stats():
    stats = get_stats()
    return jsonify(
        {
            "total": stats["total"],
            "manual": stats["manual"],
            "automatic": stats["automatic"],
        }
    )


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("image")
        if not file or file.filename == "":
            flash("Selectionne une image avant d'envoyer.", "error")
            return redirect(url_for("upload"))
        if not allowed_file(file.filename):
            flash("Format non accepte. Utilise JPG, JPEG ou PNG.", "error")
            return redirect(url_for("upload"))

        manual_label = request.form.get("manual_label") or None
        if manual_label not in {None, "clean", "dirty"}:
            flash("Annotation invalide.", "error")
            return redirect(url_for("upload"))

        location_address = request.form.get("location_address", "").strip() or None
        latitude = parse_optional_float(request.form.get("latitude"))
        longitude = parse_optional_float(request.form.get("longitude"))
        location_accuracy = parse_optional_float(request.form.get("location_accuracy"))

        original_filename = secure_filename(file.filename)
        suffix = Path(original_filename).suffix.lower()
        filename = f"{uuid4().hex}{suffix}"
        destination = UPLOAD_DIR / filename
        file.save(destination)
        image_id = save_image_record(
            destination,
            original_filename,
            manual_label=manual_label,
            location_address=location_address,
            latitude=latitude,
            longitude=longitude,
            location_accuracy=location_accuracy,
        )
        flash("Image ajoutee et analysee.", "success")
        return redirect(url_for("image_detail", image_id=image_id))

    return render_template("upload.html")


@app.route("/images")
def images():
    label = request.args.get("label")
    params = []
    query = "SELECT * FROM images"
    if label:
        if label == "non_annotee":
            query += " WHERE manual_label IS NULL"
        else:
            query += " WHERE manual_label = ?"
            params.append(label)
    query += " ORDER BY id DESC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return render_template("images.html", images=rows, selected_label=label)


@app.route("/images/<int:image_id>")
def image_detail(image_id):
    image = get_image(image_id)
    if image is None:
        flash("Image introuvable.", "error")
        return redirect(url_for("images"))
    return render_template("image_detail.html", image=image)


@app.route("/images/<int:image_id>/annotate", methods=["POST"])
def annotate(image_id):
    label = request.form.get("manual_label")
    if label not in {"clean", "dirty", "unknown"}:
        flash("Annotation invalide.", "error")
        return redirect(url_for("image_detail", image_id=image_id))

    with get_db() as conn:
        conn.execute(
            "UPDATE images SET manual_label = ? WHERE id = ?",
            (None if label == "unknown" else label, image_id),
        )
        conn.commit()
    flash("Annotation enregistree.", "success")
    return redirect(url_for("image_detail", image_id=image_id))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/media/<path:filepath>")
def media(filepath):
    return send_from_directory(BASE_DIR, filepath)


@app.route("/import-dataset", methods=["POST"])
def import_dataset():
    imported = 0
    skipped = 0
    errors = 0
    targets = [
        (DATA_DIR / "train" / "with_label" / "clean", "clean", "dataset_clean"),
        (DATA_DIR / "train" / "with_label" / "dirty", "dirty", "dataset_dirty"),
        (DATA_DIR / "train" / "no_label", None, "dataset_no_label"),
        (DATA_DIR / "test", None, "dataset_test"),
    ]

    dataset_upload_dir = UPLOAD_DIR / "dataset"
    dataset_upload_dir.mkdir(parents=True, exist_ok=True)

    for folder, manual_label, source in targets:
        if not folder.exists():
            continue
        for item in folder.iterdir():
            if not item.is_file() or not allowed_file(item.name):
                continue
            if image_exists_by_source(source, item.name):
                skipped += 1
                continue
            try:
                safe_name = secure_filename(item.name) or f"{uuid4().hex}{item.suffix.lower()}"
                destination = dataset_upload_dir / f"{source}_{uuid4().hex}_{safe_name}"
                shutil.copy2(item, destination)
                save_image_record(destination, item.name, manual_label=manual_label, source=source)
                imported += 1
            except Exception:
                errors += 1

    flash(f"Import termine : {imported} ajoutees, {skipped} deja presentes, {errors} erreurs.", "success")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5001, debug=True)
