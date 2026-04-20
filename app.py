import os
import uuid
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, request, redirect, url_for, flash, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# --- Database ---
# Supports three modes:
#   1. DATABASE_URL env var (full connection string)
#   2. Individual DB_* env vars (assembled into a connection string)
#   3. Fallback to local SQLite for development
if os.environ.get("DATABASE_URL"):
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
elif os.environ.get("DB_HOST"):
    from urllib.parse import quote_plus
    db_user = os.environ.get("DB_USER", "appuser")
    db_pass = quote_plus(os.environ.get("DB_PASSWORD", ""))
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "tododb")
    db_sslmode = os.environ.get("DB_SSLMODE", "require")
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        f"?sslmode={db_sslmode}"
    )
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///local.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# --- Azure Blob Storage ---
AZURE_STORAGE_ACCOUNT = os.environ.get("AZURE_STORAGE_ACCOUNT", "")
AZURE_STORAGE_KEY = os.environ.get("AZURE_STORAGE_KEY", "")
AZURE_STATIC_CONTAINER = os.environ.get("AZURE_STATIC_CONTAINER", "static")
AZURE_UPLOADS_CONTAINER = os.environ.get("AZURE_UPLOADS_CONTAINER", "uploads")
USE_AZURE_STORAGE = bool(AZURE_STORAGE_ACCOUNT)

# --- Managed Identity (bonus) ---
USE_MANAGED_IDENTITY = os.environ.get("USE_MANAGED_IDENTITY", "").lower() == "true"

# Blob clients (initialized lazily)
_blob_service_client = None

def get_blob_service_client():
    """Return a BlobServiceClient, creating it on first call."""
    global _blob_service_client
    if _blob_service_client is None:
        from azure.storage.blob import BlobServiceClient
        account_url = f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net"
        if USE_MANAGED_IDENTITY:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            _blob_service_client = BlobServiceClient(account_url, credential=credential)
        else:
            _blob_service_client = BlobServiceClient(account_url, credential=AZURE_STORAGE_KEY)
    return _blob_service_client


def get_static_url(filename):
    """Return the URL for a static asset – Azure Blob or local."""
    if USE_AZURE_STORAGE:
        return (
            f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net"
            f"/{AZURE_STATIC_CONTAINER}/{filename}"
        )
    return url_for("static", filename=filename)


def generate_upload_url(blob_name):
    """Return a time-limited SAS URL for a private upload blob (valet key)."""
    if not USE_AZURE_STORAGE:
        return url_for("uploaded_file", filename=blob_name)

    if USE_MANAGED_IDENTITY:
        from azure.storage.blob import (
            BlobSasPermissions,
            UserDelegationKey,
            generate_blob_sas,
        )
        from azure.identity import DefaultAzureCredential
        client = get_blob_service_client()
        # Get a user delegation key valid for 1 hour
        delegation_key = client.get_user_delegation_key(
            key_start_time=datetime.now(timezone.utc),
            key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        sas_token = generate_blob_sas(
            account_name=AZURE_STORAGE_ACCOUNT,
            container_name=AZURE_UPLOADS_CONTAINER,
            blob_name=blob_name,
            user_delegation_key=delegation_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    else:
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        sas_token = generate_blob_sas(
            account_name=AZURE_STORAGE_ACCOUNT,
            account_key=AZURE_STORAGE_KEY,
            container_name=AZURE_UPLOADS_CONTAINER,
            blob_name=blob_name,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    return (
        f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net"
        f"/{AZURE_UPLOADS_CONTAINER}/{blob_name}?{sas_token}"
    )


# Make helper available in templates
app.jinja_env.globals["static_url"] = get_static_url

# ---------------------------------------------------------------------------
# Database Models
# ---------------------------------------------------------------------------
db = SQLAlchemy(app)


class Todo(db.Model):
    __tablename__ = "todos"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    attachment_blob = db.Column(db.String(300), nullable=True)
    attachment_name = db.Column(db.String(200), nullable=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "txt", "docx", "zip"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_file_to_storage(file, blob_name):
    """Upload a file to Azure Blob Storage or save locally."""
    if USE_AZURE_STORAGE:
        client = get_blob_service_client()
        blob_client = client.get_blob_client(AZURE_UPLOADS_CONTAINER, blob_name)
        blob_client.upload_blob(file, overwrite=True)
    else:
        file.save(os.path.join("uploads", blob_name))


# ---------------------------------------------------------------------------
# Database initialization with Managed Identity token support
# ---------------------------------------------------------------------------
_db_initialized = False

def init_db():
    """Create tables. When using managed identity for Postgres, inject an
    Entra ID access token into the SQLAlchemy engine."""
    global _db_initialized
    if _db_initialized:
        return
    
    if USE_MANAGED_IDENTITY and "postgresql" in app.config["SQLALCHEMY_DATABASE_URI"]:
        from azure.identity import DefaultAzureCredential
        from sqlalchemy import event

        credential = DefaultAzureCredential()

        @event.listens_for(db.engine, "do_connect")
        def provide_token(dialect, conn_rec, cargs, cparams):
            # Remove password; we'll use the token instead
            cparams.pop("password", None)
            token = credential.get_token(
                "https://ossrdbms-aad.database.windows.net/.default"
            )
            cparams["password"] = token.token

    db.create_all()
    _db_initialized = True


@app.before_request
def ensure_db():
    """Initialize DB tables on first request if not yet done."""
    global _db_initialized
    if not _db_initialized:
        try:
            init_db()
        except Exception as e:
            print(f"[ERROR] Database initialization failed: {e}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    todos = Todo.query.order_by(Todo.created_at.desc()).all()
    return render_template("index.html", todos=todos)


@app.route("/add", methods=["POST"])
def add_todo():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if not title:
        flash("Title is required.", "error")
        return redirect(url_for("index"))

    todo = Todo(title=title, description=description)

    # Handle optional file attachment
    file = request.files.get("attachment")
    if file and file.filename and allowed_file(file.filename):
        original_name = secure_filename(file.filename)
        blob_name = f"{uuid.uuid4().hex}_{original_name}"
        upload_file_to_storage(file, blob_name)
        todo.attachment_blob = blob_name
        todo.attachment_name = original_name

    db.session.add(todo)
    db.session.commit()
    flash("Task added!", "success")
    return redirect(url_for("index"))


@app.route("/toggle/<int:todo_id>")
def toggle_todo(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    todo.completed = not todo.completed
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/delete/<int:todo_id>")
def delete_todo(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    # Delete blob if exists
    if todo.attachment_blob and USE_AZURE_STORAGE:
        try:
            client = get_blob_service_client()
            blob_client = client.get_blob_client(AZURE_UPLOADS_CONTAINER, todo.attachment_blob)
            blob_client.delete_blob()
        except Exception:
            pass
    db.session.delete(todo)
    db.session.commit()
    flash("Task deleted.", "info")
    return redirect(url_for("index"))


@app.route("/attachment/<int:todo_id>")
def view_attachment(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    if not todo.attachment_blob:
        flash("No attachment found.", "error")
        return redirect(url_for("index"))
    url = generate_upload_url(todo.attachment_blob)
    return redirect(url)


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    """Serve locally uploaded files during development."""
    return send_from_directory("uploads", filename)


@app.route("/health")
def health():
    return {"status": "ok"}, 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    with app.app_context():
        try:
            init_db()
        except Exception as e:
            print(f"[WARNING] Could not initialize database: {e}")
    app.run(debug=True, host="0.0.0.0", port=port)