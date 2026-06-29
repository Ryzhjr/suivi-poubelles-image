from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4
import io
import base64

from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from PIL import Image, ImageFilter, ImageStat
from PIL.ExifTags import TAGS, GPSTAGS
from werkzeug.utils import secure_filename
import matplotlib
matplotlib.use('Agg')  # Backend sans GUI pour serveur
import matplotlib.pyplot as plt
import numpy as np


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
        if "dark_ratio" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN dark_ratio REAL")
        if "bright_ratio" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN bright_ratio REAL")
        conn.commit()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def relative_path(path):
    return path.resolve().relative_to(BASE_DIR).as_posix()


def extract_gps_from_exif(img):
    """Extract GPS coordinates from image EXIF data."""
    try:
        exif = img._getexif()
        if not exif:
            return None, None

        gps_info = {}
        for tag_id, value in exif.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "GPSInfo":
                for gps_tag_id, gps_value in value.items():
                    gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                    gps_info[gps_tag] = gps_value
                break

        if not gps_info:
            return None, None

        def convert_to_degrees(value):
            d, m, s = value
            return float(d) + float(m) / 60 + float(s) / 3600

        lat = None
        lng = None

        if "GPSLatitude" in gps_info and "GPSLatitudeRef" in gps_info:
            lat = convert_to_degrees(gps_info["GPSLatitude"])
            if gps_info["GPSLatitudeRef"] == "S":
                lat = -lat

        if "GPSLongitude" in gps_info and "GPSLongitudeRef" in gps_info:
            lng = convert_to_degrees(gps_info["GPSLongitude"])
            if gps_info["GPSLongitudeRef"] == "W":
                lng = -lng

        return lat, lng
    except Exception:
        return None, None


def extract_features(path):
    file_size = path.stat().st_size
    with Image.open(path) as img:
        # Extract GPS from EXIF before converting to RGB
        exif_lat, exif_lng = extract_gps_from_exif(img)

        img = img.convert("RGB")
        width, height = img.size
        stat = ImageStat.Stat(img)
        avg_red, avg_green, avg_blue = stat.mean

        # Histogrammes RVB (distribution des couleurs)
        histogram_rgb = img.histogram()
        # histogram_rgb contient 768 valeurs : 256 pour R, 256 pour G, 256 pour B
        # On stocke la somme des bins pour chaque canal comme signature simplifiée
        hist_red_sum = sum(histogram_rgb[0:256])
        hist_green_sum = sum(histogram_rgb[256:512])
        hist_blue_sum = sum(histogram_rgb[512:768])

        grayscale = img.convert("L")
        gray_stat = ImageStat.Stat(grayscale)
        brightness = gray_stat.mean[0]
        contrast = gray_stat.stddev[0]

        # Histogramme de luminance (niveaux de gris)
        histogram_luminance = grayscale.histogram()
        # 256 valeurs pour les niveaux de gris (0 = noir, 255 = blanc)
        # On calcule des métriques utiles : pics dans les zones sombres/claires
        dark_pixels = sum(histogram_luminance[0:85])    # Pixels sombres (0-84)
        mid_pixels = sum(histogram_luminance[85:170])   # Pixels moyens (85-169)
        bright_pixels = sum(histogram_luminance[170:256])  # Pixels clairs (170-255)
        total_pixels = width * height

        dark_ratio = (dark_pixels / total_pixels * 100) if total_pixels > 0 else 0
        bright_ratio = (bright_pixels / total_pixels * 100) if total_pixels > 0 else 0

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
        "dark_ratio": round(dark_ratio, 2),
        "bright_ratio": round(bright_ratio, 2),
        "exif_latitude": exif_lat,
        "exif_longitude": exif_lng,
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

    # Use EXIF GPS if no coordinates provided
    if latitude is None and features.get("exif_latitude") is not None:
        latitude = features["exif_latitude"]
    if longitude is None and features.get("exif_longitude") is not None:
        longitude = features["exif_longitude"]

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO images (
                filename, original_filename, filepath, source, upload_date,
                location_address, latitude, longitude, location_accuracy,
                manual_label, automatic_label, file_size, width, height,
                avg_red, avg_green, avg_blue, brightness, contrast, edge_score,
                dark_ratio, bright_ratio
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                features["dark_ratio"],
                features["bright_ratio"],
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


# ===== GÉNÉRATION DE GRAPHIQUES MATPLOTLIB (Backend Python) =====

def generate_file_size_distribution_graph():
    """Génère un graphique matplotlib de la distribution des tailles de fichiers."""
    with get_db() as conn:
        file_sizes = conn.execute("SELECT file_size FROM images").fetchall()

    if not file_sizes:
        return None

    # Convertir en Mo
    sizes_mb = [row["file_size"] / (1024 * 1024) for row in file_sizes]

    # Créer le graphique
    plt.figure(figsize=(10, 6))
    plt.hist(sizes_mb, bins=20, color='#3BA58E', edgecolor='black', alpha=0.7)
    plt.xlabel('Taille du fichier (Mo)', fontsize=12)
    plt.ylabel('Nombre d\'images', fontsize=12)
    plt.title('Distribution des tailles de fichiers', fontsize=14, fontweight='bold')
    plt.grid(axis='y', alpha=0.3)

    # Sauvegarder en base64 pour inclusion dans HTML
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()

    return image_base64


def generate_label_distribution_bar():
    """Génère un graphique en barres de la répartition des annotations."""
    with get_db() as conn:
        labels_dist = conn.execute("""
            SELECT
                COALESCE(manual_label, 'non_annotee') as label,
                COUNT(*) as count
            FROM images
            GROUP BY label
        """).fetchall()

    if not labels_dist:
        return None

    labels = [row["label"] for row in labels_dist]
    counts = [row["count"] for row in labels_dist]

    colors = {'clean': '#68B66D', 'dirty': '#D97A3A', 'non_annotee': '#7D7D75'}
    bar_colors = [colors.get(label, '#7D7D75') for label in labels]

    plt.figure(figsize=(8, 6))
    plt.bar(labels, counts, color=bar_colors, edgecolor='black', alpha=0.8)
    plt.xlabel('Annotation', fontsize=12)
    plt.ylabel('Nombre d\'images', fontsize=12)
    plt.title('Répartition des annotations manuelles', fontsize=14, fontweight='bold')
    plt.grid(axis='y', alpha=0.3)

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()

    return image_base64


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

    with get_db() as conn:
        # Évolution temporelle (30 derniers jours)
        timeline = conn.execute("""
            SELECT DATE(upload_date) as date, COUNT(*) as count
            FROM images
            GROUP BY DATE(upload_date)
            ORDER BY date DESC
            LIMIT 30
        """).fetchall()

        # Inverser pour avoir l'ordre chronologique
        timeline_dates = [row["date"] for row in reversed(timeline)]
        timeline_counts = [row["count"] for row in reversed(timeline)]

        # Répartition par label
        labels_dist = conn.execute("""
            SELECT
                COALESCE(manual_label, 'non_annotee') as label,
                COUNT(*) as count
            FROM images
            GROUP BY label
        """).fetchall()

        label_data = {"clean": 0, "dirty": 0, "non_annotee": 0}
        for row in labels_dist:
            label_data[row["label"]] = row["count"]

        # Top 10 villes
        cities = conn.execute("""
            SELECT
                COALESCE(location_address, 'Non localisé') as city,
                COUNT(*) as count
            FROM images
            GROUP BY city
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()

        cities_names = [row["city"] for row in cities]
        cities_counts = [row["count"] for row in cities]

        # Distribution luminosité (100 dernières images)
        brightness_dist = conn.execute("""
            SELECT brightness
            FROM images
            WHERE brightness IS NOT NULL
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

        brightness_values = [row["brightness"] for row in brightness_dist]

        # Sources
        sources = conn.execute("""
            SELECT source, COUNT(*) as count
            FROM images
            GROUP BY source
        """).fetchall()

        sources_names = [row["source"] for row in sources]
        sources_counts = [row["count"] for row in sources]

        # Statistiques générales supplémentaires
        geo_stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) as geolocated
            FROM images
        """).fetchone()

        # Taux de géolocalisation
        geo_percentage = round((geo_stats["geolocated"] / geo_stats["total"] * 100) if geo_stats["total"] > 0 else 0, 1)

        # Taux d'annotation manuelle
        annotation_stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN manual_label IS NOT NULL THEN 1 ELSE 0 END) as annotated
            FROM images
        """).fetchone()

        annotation_percentage = round((annotation_stats["annotated"] / annotation_stats["total"] * 100) if annotation_stats["total"] > 0 else 0, 1)

        # Précision de l'annotation automatique (concordance avec manuel)
        accuracy_stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN manual_label = automatic_label THEN 1 ELSE 0 END) as correct
            FROM images
            WHERE manual_label IS NOT NULL
        """).fetchone()

        accuracy_percentage = round((accuracy_stats["correct"] / accuracy_stats["total"] * 100) if accuracy_stats["total"] > 0 else 0, 1)

        # Signalements cette semaine
        week_stats = conn.execute("""
            SELECT COUNT(*) as count
            FROM images
            WHERE upload_date >= datetime('now', '-7 days')
        """).fetchone()

        # Signalements aujourd'hui
        today_stats = conn.execute("""
            SELECT COUNT(*) as count
            FROM images
            WHERE DATE(upload_date) = DATE('now')
        """).fetchone()

        # === MÉTRIQUES DE CLASSIFICATION ===
        # Calcul de Accuracy, Precision, Recall pour chaque classe

        # Pour la classe "clean"
        clean_metrics = conn.execute("""
            SELECT
                -- True Positives : auto=clean ET manual=clean
                SUM(CASE WHEN automatic_label = 'clean' AND manual_label = 'clean' THEN 1 ELSE 0 END) as tp,
                -- False Positives : auto=clean mais manual!=clean
                SUM(CASE WHEN automatic_label = 'clean' AND manual_label != 'clean' THEN 1 ELSE 0 END) as fp,
                -- False Negatives : auto!=clean mais manual=clean
                SUM(CASE WHEN automatic_label != 'clean' AND manual_label = 'clean' THEN 1 ELSE 0 END) as fn,
                -- True Negatives : auto!=clean ET manual!=clean
                SUM(CASE WHEN automatic_label != 'clean' AND manual_label != 'clean' THEN 1 ELSE 0 END) as tn
            FROM images
            WHERE manual_label IS NOT NULL
        """).fetchone()

        # Pour la classe "dirty"
        dirty_metrics = conn.execute("""
            SELECT
                SUM(CASE WHEN automatic_label = 'dirty' AND manual_label = 'dirty' THEN 1 ELSE 0 END) as tp,
                SUM(CASE WHEN automatic_label = 'dirty' AND manual_label != 'dirty' THEN 1 ELSE 0 END) as fp,
                SUM(CASE WHEN automatic_label != 'dirty' AND manual_label = 'dirty' THEN 1 ELSE 0 END) as fn,
                SUM(CASE WHEN automatic_label != 'dirty' AND manual_label != 'dirty' THEN 1 ELSE 0 END) as tn
            FROM images
            WHERE manual_label IS NOT NULL
        """).fetchone()

        # Calcul des métriques
        def calculate_metrics(tp, fp, fn, tn):
            precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0
            recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0
            f1_score = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
            return {
                "precision": round(precision * 100, 1),
                "recall": round(recall * 100, 1),
                "f1_score": round(f1_score * 100, 1)
            }

        metrics_clean = calculate_metrics(
            clean_metrics["tp"] or 0,
            clean_metrics["fp"] or 0,
            clean_metrics["fn"] or 0,
            clean_metrics["tn"] or 0
        )

        metrics_dirty = calculate_metrics(
            dirty_metrics["tp"] or 0,
            dirty_metrics["fp"] or 0,
            dirty_metrics["fn"] or 0,
            dirty_metrics["tn"] or 0
        )

        # Accuracy globale (déjà calculée mais reformulée)
        global_accuracy = accuracy_percentage

    # Préparer les données de tailles de fichiers pour Chart.js
    with get_db() as conn:
        file_sizes_raw = conn.execute("SELECT file_size FROM images").fetchall()

    # Convertir en Mo et créer des bins
    sizes_mb = [row["file_size"] / (1024 * 1024) for row in file_sizes_raw]

    # Créer des bins (0-0.5, 0.5-1, 1-1.5, etc.)
    if sizes_mb:
        hist, bin_edges = np.histogram(sizes_mb, bins=15)
        bin_labels = [f"{bin_edges[i]:.1f}-{bin_edges[i+1]:.1f}" for i in range(len(bin_edges)-1)]
        file_sizes_data = {
            "bins": bin_labels,
            "counts": hist.tolist()
        }
    else:
        file_sizes_data = {"bins": [], "counts": []}

    return render_template("dashboard.html",
        stats=stats,
        timeline_data={"dates": timeline_dates, "counts": timeline_counts},
        label_data=label_data,
        cities_data={"cities": cities_names, "counts": cities_counts},
        brightness_data=brightness_values,
        file_sizes_data=file_sizes_data,
        geo_percentage=geo_percentage,
        annotation_percentage=annotation_percentage,
        accuracy_percentage=accuracy_percentage,
        week_count=week_stats["count"],
        today_count=today_stats["count"],
        metrics_clean=metrics_clean,
        metrics_dirty=metrics_dirty,
        global_accuracy=global_accuracy
    )


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


@app.route("/images/<int:image_id>/location", methods=["POST"])
def update_location(image_id):
    latitude = parse_optional_float(request.form.get("latitude"))
    longitude = parse_optional_float(request.form.get("longitude"))
    location_address = request.form.get("location_address", "").strip() or None

    with get_db() as conn:
        conn.execute(
            "UPDATE images SET latitude = ?, longitude = ?, location_address = ? WHERE id = ?",
            (latitude, longitude, location_address, image_id),
        )
        conn.commit()
    flash("Localisation mise a jour.", "success")
    return redirect(url_for("image_detail", image_id=image_id))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/media/<path:filepath>")
def media(filepath):
    return send_from_directory(BASE_DIR, filepath)


@app.route("/map")
def map_view():
    return render_template("map.html")


@app.route("/api/markers")
def api_markers():
    label = request.args.get("label", "all")
    period = request.args.get("period", "all")

    query = "SELECT id, latitude, longitude, manual_label, automatic_label, location_address, upload_date, filepath FROM images WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    params = []

    if label == "clean":
        query += " AND manual_label = ?"
        params.append("clean")
    elif label == "dirty":
        query += " AND manual_label = ?"
        params.append("dirty")
    elif label == "non_annotee":
        query += " AND manual_label IS NULL"

    if period == "24h":
        cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        query += " AND upload_date >= ?"
        params.append(cutoff)
    elif period == "week":
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        query += " AND upload_date >= ?"
        params.append(cutoff)
    elif period == "month":
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        query += " AND upload_date >= ?"
        params.append(cutoff)

    query += " ORDER BY upload_date DESC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    markers = []
    lats = []
    lngs = []

    for row in rows:
        lats.append(row["latitude"])
        lngs.append(row["longitude"])
        markers.append({
            "id": row["id"],
            "lat": row["latitude"],
            "lng": row["longitude"],
            "label": row["manual_label"] or "non_annotee",
            "auto_label": row["automatic_label"],
            "address": row["location_address"],
            "date": row["upload_date"][:10] if row["upload_date"] else None,
            "thumbnail": "/" + row["filepath"],
        })

    bounds = None
    if lats and lngs:
        bounds = {
            "north": max(lats),
            "south": min(lats),
            "east": max(lngs),
            "west": min(lngs),
        }

    return jsonify({"markers": markers, "count": len(markers), "bounds": bounds})


@app.route("/api/heatmap")
def api_heatmap():
    period = request.args.get("period", "all")

    query = """
        SELECT latitude, longitude FROM images
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        AND (manual_label = 'dirty' OR (manual_label IS NULL AND automatic_label = 'dirty'))
    """
    params = []

    if period == "24h":
        cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        query += " AND upload_date >= ?"
        params.append(cutoff)
    elif period == "week":
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        query += " AND upload_date >= ?"
        params.append(cutoff)
    elif period == "month":
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        query += " AND upload_date >= ?"
        params.append(cutoff)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    points = [[row["latitude"], row["longitude"], 1.0] for row in rows]

    return jsonify({"points": points, "count": len(points)})


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
