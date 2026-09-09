from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_file, jsonify
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import hashlib
import json
import os
import uuid
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secure-digital-evidence-secret-key"

# -----------------------------
# FOLDERS
# -----------------------------

UPLOAD_FOLDER = "uploads"
KEY_FILE = "encryption.key"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# -----------------------------
# ENCRYPTION KEY
# -----------------------------

if not os.path.exists(KEY_FILE):
    key = Fernet.generate_key()

    with open(KEY_FILE, "wb") as f:
        f.write(key)
else:
    with open(KEY_FILE, "rb") as f:
        key = f.read()

cipher = Fernet(key)

# -----------------------------
# AGENCY ACCOUNTS
# -----------------------------

AGENCIES = {
    "Agency A": generate_password_hash("agencyA123"),
    "Agency B": generate_password_hash("agencyB123"),
    "Agency C": generate_password_hash("agencyC123")
}

# -----------------------------
# ALLOWED FILE TYPES
# -----------------------------

ALLOWED_EXTENSIONS = {
    "pdf",
    "txt",
    "jpg",
    "jpeg",
    "png",
    "docx"
}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


# -----------------------------
# BLOCKCHAIN
# -----------------------------

blockchain = []

genesis_block = {
    "index": 0,
    "timestamp": datetime.now().isoformat(),
    "evidence_id": "GENESIS",
    "filename": "GENESIS BLOCK",
    "sender": "SYSTEM",
    "receiver": "SYSTEM",
    "evidence_hash": "GENESIS",
    "previous_hash": "0"
}

genesis_block["hash"] = hashlib.sha256(
    json.dumps(genesis_block, sort_keys=True).encode()
).hexdigest()

blockchain.append(genesis_block)


def calculate_block_hash(block):
    block_copy = block.copy()

    block_copy.pop("hash", None)

    return hashlib.sha256(
        json.dumps(block_copy, sort_keys=True).encode()
    ).hexdigest()


def verify_blockchain():

    for i in range(1, len(blockchain)):

        current = blockchain[i]
        previous = blockchain[i - 1]

        if current["previous_hash"] != previous["hash"]:
            return False

        if current["hash"] != calculate_block_hash(current):
            return False

    return True


# -----------------------------
# CHAIN OF CUSTODY
# -----------------------------

custody_log = []


def add_custody_event(
    event,
    agency,
    evidence_id=None,
    sender=None,
    receiver=None
):

    custody_log.append({
        "timestamp": datetime.now().isoformat(),
        "event": event,
        "agency": agency,
        "evidence_id": evidence_id,
        "sender": sender,
        "receiver": receiver
    })


# -----------------------------
# LOGIN REQUIRED
# -----------------------------

def login_required():

    if "agency" not in session:
        return False

    return True


# -----------------------------
# HOME / LOGIN
# -----------------------------

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        agency = request.form.get("agency")
        password = request.form.get("password")

        if agency not in AGENCIES:

            flash("Invalid agency")
            return redirect(url_for("login"))

        if check_password_hash(AGENCIES[agency], password):

            session["agency"] = agency

            add_custody_event(
                "LOGIN",
                agency
            )

            return redirect(url_for("dashboard"))

        flash("Incorrect password")

    return render_template(
        "index.html",
        logged_in=False
    )


# -----------------------------
# LOGOUT
# -----------------------------

@app.route("/logout")
def logout():

    agency = session.get("agency")

    if agency:
        add_custody_event(
            "LOGOUT",
            agency
        )

    session.clear()

    return redirect(url_for("login"))


# -----------------------------
# DASHBOARD
# -----------------------------

@app.route("/dashboard")
def dashboard():

    if not login_required():
        return redirect(url_for("login"))

    current_agency = session["agency"]

    # IMPORTANT:
    # Only sender OR receiver can see evidence
    visible_blocks = []

    for block in blockchain:

        if block["evidence_id"] == "GENESIS":
            continue

        if (
            block["sender"] == current_agency
            or
            block["receiver"] == current_agency
        ):
            visible_blocks.append(block)

    # Current agency custody events only
    visible_logs = []

    for log in custody_log:

        if (
            log.get("agency") == current_agency
            or
            log.get("sender") == current_agency
            or
            log.get("receiver") == current_agency
        ):
            visible_logs.append(log)

    return render_template(
        "index.html",
        logged_in=True,
        agency=current_agency,
        blockchain=visible_blocks,
        custody_log=visible_logs,
        security_status=verify_blockchain()
    )


# -----------------------------
# UPLOAD / SEND EVIDENCE
# -----------------------------

@app.route("/upload", methods=["POST"])
def upload():

    if not login_required():
        return redirect(url_for("login"))

    sender = session["agency"]

    receiver = request.form.get("receiver")

    file = request.files.get("evidence")

    # -------------------------
    # VALIDATION
    # -------------------------

    if not file:

        flash("Please select a file")
        return redirect(url_for("dashboard"))

    if file.filename == "":

        flash("Please select a file")
        return redirect(url_for("dashboard"))

    if receiver not in AGENCIES:

        flash("Invalid receiver")
        return redirect(url_for("dashboard"))

    if receiver == sender:

        flash("You cannot send evidence to the same agency")
        return redirect(url_for("dashboard"))

    if not allowed_file(file.filename):

        flash("File type not allowed")
        return redirect(url_for("dashboard"))

    # -------------------------
    # EVIDENCE ID
    # -------------------------

    evidence_id = "EVD-" + str(uuid.uuid4())[:8]

    original_filename = secure_filename(file.filename)

    # -------------------------
    # READ FILE
    # -------------------------

    file_data = file.read()

    if not file_data:

        flash("Empty file is not allowed")
        return redirect(url_for("dashboard"))

    # -------------------------
    # SHA-256 HASH
    # -------------------------

    evidence_hash = hashlib.sha256(file_data).hexdigest()

    # -------------------------
    # ENCRYPT FILE
    # -------------------------

    encrypted_data = cipher.encrypt(file_data)

    encrypted_filename = evidence_id + "_" + original_filename + ".enc"

    encrypted_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        encrypted_filename
    )

    with open(encrypted_path, "wb") as f:
        f.write(encrypted_data)

    # -------------------------
    # BLOCKCHAIN BLOCK
    # -------------------------

    previous_hash = blockchain[-1]["hash"]

    block = {
        "index": len(blockchain),
        "timestamp": datetime.now().isoformat(),
        "evidence_id": evidence_id,
        "filename": original_filename,
        "sender": sender,
        "receiver": receiver,
        "evidence_hash": evidence_hash,
        "previous_hash": previous_hash
    }

    block["hash"] = calculate_block_hash(block)

    blockchain.append(block)

    # -------------------------
    # CHAIN OF CUSTODY
    # -------------------------

    add_custody_event(
        "EVIDENCE UPLOADED & SENT",
        sender,
        evidence_id,
        sender,
        receiver
    )

    flash(
        f"Evidence securely sent to {receiver}. "
        f"Evidence ID: {evidence_id}"
    )

    return redirect(url_for("dashboard"))


# -----------------------------
# VERIFY EVIDENCE
# -----------------------------

@app.route("/verify/<evidence_id>")
def verify_evidence(evidence_id):

    if not login_required():
        return redirect(url_for("login"))

    current_agency = session["agency"]

    block = None

    # -------------------------
    # FIND BLOCK
    # -------------------------

    for item in blockchain:

        if item["evidence_id"] == evidence_id:

            block = item
            break

    if not block:

        flash("Evidence not found")
        return redirect(url_for("dashboard"))

    # -------------------------
    # ACCESS CONTROL
    # -------------------------

    if (
        current_agency != block["sender"]
        and
        current_agency != block["receiver"]
    ):

        add_custody_event(
            "UNAUTHORIZED VERIFY ATTEMPT",
            current_agency,
            evidence_id,
            block["sender"],
            block["receiver"]
        )

        flash(
            "ACCESS DENIED: You are not authorized to view this evidence."
        )

        return redirect(url_for("dashboard"))

    # -------------------------
    # FILE PATH
    # -------------------------

    encrypted_filename = (
        evidence_id
        + "_"
        + secure_filename(block["filename"])
        + ".enc"
    )

    encrypted_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        encrypted_filename
    )

    if not os.path.exists(encrypted_path):

        flash("Encrypted evidence file not found")
        return redirect(url_for("dashboard"))

    # -------------------------
    # DECRYPT
    # -------------------------

    try:

        with open(encrypted_path, "rb") as f:
            encrypted_data = f.read()

        decrypted_data = cipher.decrypt(encrypted_data)

    except Exception:

        flash("Evidence decryption failed")
        return redirect(url_for("dashboard"))

    # -------------------------
    # RECALCULATE HASH
    # -------------------------

    current_hash = hashlib.sha256(
        decrypted_data
    ).hexdigest()

    # -------------------------
    # COMPARE HASH
    # -------------------------

    if current_hash == block["evidence_hash"]:

        result = "AUTHENTIC - NO TAMPERING DETECTED"

        add_custody_event(
            "EVIDENCE VERIFIED - AUTHENTIC",
            current_agency,
            evidence_id,
            block["sender"],
            block["receiver"]
        )

        flash(
            f"{result} for {evidence_id}"
        )

    else:

        result = "WARNING - EVIDENCE TAMPERED"

        add_custody_event(
            "TAMPER DETECTED",
            current_agency,
            evidence_id,
            block["sender"],
            block["receiver"]
        )

        flash(
            f"{result}: Hash does not match!"
        )

    return redirect(url_for("dashboard"))


# -----------------------------
# DOWNLOAD EVIDENCE
# -----------------------------

@app.route("/download/<evidence_id>")
def download_evidence(evidence_id):

    if not login_required():
        return redirect(url_for("login"))

    current_agency = session["agency"]

    block = None

    for item in blockchain:

        if item["evidence_id"] == evidence_id:

            block = item
            break

    if not block:

        flash("Evidence not found")
        return redirect(url_for("dashboard"))

    # -------------------------
    # ACCESS CONTROL
    # -------------------------

    if (
        current_agency != block["sender"]
        and
        current_agency != block["receiver"]
    ):

        add_custody_event(
            "UNAUTHORIZED DOWNLOAD ATTEMPT",
            current_agency,
            evidence_id,
            block["sender"],
            block["receiver"]
        )

        flash(
            "ACCESS DENIED: You cannot access this evidence."
        )

        return redirect(url_for("dashboard"))

    # -------------------------
    # FILE
    # -------------------------

    encrypted_filename = (
        evidence_id
        + "_"
        + secure_filename(block["filename"])
        + ".enc"
    )

    encrypted_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        encrypted_filename
    )

    if not os.path.exists(encrypted_path):

        flash("Evidence file not found")
        return redirect(url_for("dashboard"))

    # -------------------------
    # DECRYPT
    # -------------------------

    try:

        with open(encrypted_path, "rb") as f:
            encrypted_data = f.read()

        decrypted_data = cipher.decrypt(encrypted_data)

    except Exception:

        flash("Unable to decrypt evidence")
        return redirect(url_for("dashboard"))

    # -------------------------
    # CREATE TEMP FILE
    # -------------------------

    temp_filename = (
        evidence_id
        + "_"
        + secure_filename(block["filename"])
    )

    temp_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        temp_filename
    )

    with open(temp_path, "wb") as f:
        f.write(decrypted_data)

    # -------------------------
    # CUSTODY LOG
    # -------------------------

    add_custody_event(
        "EVIDENCE ACCESSED / DOWNLOADED",
        current_agency,
        evidence_id,
        block["sender"],
        block["receiver"]
    )

    return send_file(
        temp_path,
        as_attachment=True,
        download_name=block["filename"]
    )


# -----------------------------
# BLOCKCHAIN API
# -----------------------------

@app.route("/blockchain")
def get_blockchain():

    if not login_required():
        return jsonify({
            "error": "Login required"
        }), 401

    current_agency = session["agency"]

    visible_blocks = []

    for block in blockchain:

        if block["evidence_id"] == "GENESIS":

            continue

        if (
            block["sender"] == current_agency
            or
            block["receiver"] == current_agency
        ):

            visible_blocks.append(block)

    return jsonify({
        "agency": current_agency,
        "blockchain": visible_blocks,
        "valid": verify_blockchain()
    })


# -----------------------------
# SECURITY STATUS
# -----------------------------

@app.route("/security-status")
def security_status():

    if not login_required():
        return jsonify({
            "error": "Login required"
        }), 401

    current_agency = session["agency"]

    visible_evidence = []

    for block in blockchain:

        if block["evidence_id"] == "GENESIS":
            continue

        if (
            block["sender"] == current_agency
            or
            block["receiver"] == current_agency
        ):

            visible_evidence.append(block)

    return jsonify({
        "agency": current_agency,
        "blockchain_valid": verify_blockchain(),
        "accessible_evidence": len(visible_evidence),
        "security": "ACTIVE"
    })


# -----------------------------
# RUN SERVER
# -----------------------------

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )