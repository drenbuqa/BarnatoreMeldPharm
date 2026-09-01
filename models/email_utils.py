import logging
import os
import smtplib
import threading
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from smtplib import SMTPAuthenticationError

from bson import ObjectId

from .db import mongo


def _format_currency(value):
    try:
        return f"€{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return "€0.00"


def _get_order(order_or_id):
    if isinstance(order_or_id, dict):
        return order_or_id
    if not order_or_id:
        return None
    try:
        return mongo.db.orders.find_one({"_id": ObjectId(str(order_or_id))})
    except Exception:
        return None


def _get_smtp_config():
    sender_email = (
        os.getenv("PHARMACY_FROM_EMAIL") or os.getenv("SMTP_FROM_EMAIL")
        or os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("SMTP_USER")
        or os.getenv("MAIL_USERNAME")
    )
    host_default, port_default = _infer_smtp_defaults(sender_email)
    return {
        "sender_email": sender_email,
        "smtp_host": os.getenv("SMTP_HOST") or os.getenv("MAIL_SERVER") or host_default,
        "smtp_port": int(os.getenv("SMTP_PORT") or os.getenv("MAIL_PORT") or port_default),
        "smtp_user": os.getenv("SMTP_USER") or os.getenv("MAIL_USERNAME") or sender_email,
        "smtp_password": os.getenv("SMTP_PASSWORD") or os.getenv("MAIL_PASSWORD"),
        "sender_name": os.getenv("PHARMACY_NAME", "Barnatore Meld Pharm"),
        "reply_to": os.getenv("PHARMACY_REPLY_TO") or sender_email,
        "use_tls": (os.getenv("SMTP_USE_TLS") or os.getenv("MAIL_USE_TLS") or "true").lower() != "false",
    }


PHARMACY_PHONE = "+383 45 590 455"
PHARMACY_EMAIL_CONTACT = "meldpharm@hotmail.com"
PHARMACY_ADDRESS = "72 Eqrem Çabej, Prishtinë 10000"
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://barnatoremeldpharm.com")
# Always use the deployed domain for email images — localhost URLs break in email clients
_EMAIL_BASE = os.getenv("SITE_BASE_URL", "https://barnatoremeldpharm.com").rstrip("/")
LOGO_URL = f"{_EMAIL_BASE}/static/favicon.png"


def _order_timeline_html(active_step):
    """
    active_step: 0=placed, 1=Konfirmuar, 2=Në Dërgesë, 3=Dorëzuar
    Uses a two-row table: top row = circles + connectors, bottom row = labels.
    """
    steps = [("✓", "Porosi vendosur"), ("📦", "Konfirmuar"), ("🚚", "Në Dërgesë"), ("✓", "Dorëzuar")]
    n = len(steps)
    circle_row = ""
    label_row = ""
    for i, (icon, label) in enumerate(steps):
        is_done = i <= active_step
        circle_bg = "#4F5D4E" if is_done else "#e5e7eb"
        circle_color = "#fff" if is_done else "#94a3b8"
        label_color = "#4F5D4E" if is_done else "#94a3b8"
        label_weight = "700" if i == active_step else ("600" if is_done else "400")
        circle_row += f'<td style="text-align:center;vertical-align:middle;width:40px;padding:0;"><div style="width:36px;height:36px;border-radius:50%;background:{circle_bg};color:{circle_color};font-size:14px;line-height:36px;text-align:center;margin:0 auto;">{icon}</div></td>'
        label_row += f'<td style="text-align:center;vertical-align:top;width:40px;padding:6px 2px 0;"><div style="font-size:10px;color:{label_color};font-weight:{label_weight};line-height:1.3;">{label}</div></td>'
        if i < n - 1:
            conn_color = "#4F5D4E" if i < active_step else "#e5e7eb"
            circle_row += f'<td style="vertical-align:middle;padding:0;"><div style="height:2px;background:{conn_color};width:100%;"></div></td>'
            label_row += '<td></td>'
    return f"""
<table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:20px 0 4px;border-collapse:collapse;">
  <tr>{circle_row}</tr>
  <tr>{label_row}</tr>
</table>"""


def _abs_img_url(url):
    """Make a relative image URL absolute for use in emails. Always use the live domain."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return _EMAIL_BASE.rstrip("/") + "/" + url.lstrip("/")


def _order_items_html(items):
    """Render order items as a table with product images."""
    rows = ""
    for item in items:
        img_url = _abs_img_url(item.get("image_url") or "")
        img_cell = (
            f'<img src="{img_url}" width="52" height="52" style="width:52px;height:52px;object-fit:cover;border-radius:8px;border:1px solid #e5e7eb;display:block;" alt="">'
            if img_url else
            '<div style="width:52px;height:52px;background:#f1f5f9;border-radius:8px;"></div>'
        )
        variant = item.get("variant") or ""
        variant_line = f'<div style="font-size:11px;color:#94a3b8;margin-top:2px;">{variant}</div>' if variant else ""
        qty = int(item.get("quantity") or 1)
        total = _format_currency(item.get("item_total"))
        rows += f"""
<tr>
  <td style="padding:10px 0;border-bottom:1px solid #f1f5f9;vertical-align:middle;width:60px;">{img_cell}</td>
  <td style="padding:10px 12px;border-bottom:1px solid #f1f5f9;vertical-align:middle;">
    <div style="font-size:13px;font-weight:600;color:#1f2937;">{item.get('name','')}</div>
    {variant_line}
    <div style="font-size:12px;color:#94a3b8;margin-top:3px;">Sasia: {qty}</div>
  </td>
  <td style="padding:10px 12px;border-bottom:1px solid #f1f5f9;vertical-align:middle;text-align:right;white-space:nowrap;">
    <div style="font-size:11px;color:#94a3b8;margin-bottom:2px;">Çmimi</div>
    <div style="font-size:13px;font-weight:700;color:#0f172a;">{total}</div>
  </td>
</tr>"""
    return f'<table cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;">{rows}</table>'


LOGO_URL = "https://res.cloudinary.com/drljgepgy/image/upload/v1788282469/ChatGPT_Image_Sep_1_2026_at_07_06_44_PM_kluztv.png"

def _email_html(title, body_html, cfg):
    """Branded email shell with logo header, consistent footer."""
    name = cfg["sender_name"]
    return f"""
<div style="font-family:Arial,sans-serif;color:#1f2937;line-height:1.6;max-width:600px;margin:0 auto;background:#fff;">
  <!-- Header -->
  <div style="background:#4F5D4E;height:4px;"></div>
  <div style="text-align:center;padding:24px 20px 18px;border-bottom:1px solid #eef0ed;background:#ffffff;">
    <img src="{LOGO_URL}" alt="{name}" width="290" style="display:inline-block;max-width:290px;height:auto;">
    <div style="font-size:11px;font-weight:600;color:#9aa095;margin-top:10px;letter-spacing:1px;text-transform:uppercase;">{title}</div>
  </div>
  <!-- Body -->
  <div style="padding:28px 32px;">
    {body_html}
  </div>
  <!-- Footer -->
  <div style="background:#f5f7f4;border-top:1px solid #eef0ed;padding:18px 28px;text-align:center;color:#8a9186;font-size:12px;line-height:2;">
    <strong style="color:#374151;">{name}</strong><br>
    {PHARMACY_ADDRESS}<br>
    Tel: {PHARMACY_PHONE} &nbsp;·&nbsp;
    <a href="mailto:{PHARMACY_EMAIL_CONTACT}" style="color:#4F5D4E;text-decoration:none;">{PHARMACY_EMAIL_CONTACT}</a>
  </div>
</div>"""


def _send_simple_email(cfg, recipient_email, subject, text_body, html_body):
    """Send an email using Resend API (preferred) or SMTP fallback."""
    resend_key = os.getenv("RESEND_API_KEY")
    if resend_key:
        # Use Resend HTTP API — works on all cloud hosts including Render
        try:
            import requests as _req
            from_addr = f"{cfg['sender_name']} <noreply@barnatoremeldpharm.com>"
            resp = _req.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json={"from": from_addr, "to": [recipient_email], "subject": subject,
                      "html": html_body, "text": text_body},
                timeout=15,
            )
            if resp.status_code in (200, 201):
                return True, "Email sent."
            return False, f"Resend error {resp.status_code}: {resp.text}"
        except Exception as exc:
            logging.exception("Resend API failed")
            return False, str(exc)

    # Fallback: SMTP (works locally, blocked on Render)
    if not cfg["smtp_host"] or not cfg["smtp_user"] or not cfg["smtp_password"] or not cfg["sender_email"]:
        return False, "SMTP configuration incomplete. Check .env variables."
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender_email']}>"
    msg["To"] = recipient_email
    msg["Reply-To"] = cfg["reply_to"]
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    host = cfg["smtp_host"]
    port = cfg["smtp_port"]
    try:
        ssl_port = 465 if port == 587 else port
        with smtplib.SMTP_SSL(host, ssl_port, timeout=8) as server:
            server.login(cfg["smtp_user"], cfg["smtp_password"])
            server.send_message(msg)
        return True, "Email sent."
    except SMTPAuthenticationError as exc:
        logging.exception("SMTP auth failed")
        return False, str(exc)
    except Exception as ssl_exc:
        logging.warning(f"SSL email failed ({ssl_exc}), trying STARTTLS...")
        try:
            with smtplib.SMTP(host, port, timeout=8) as server:
                if cfg["use_tls"]:
                    server.starttls()
                server.login(cfg["smtp_user"], cfg["smtp_password"])
                server.send_message(msg)
            return True, "Email sent."
        except SMTPAuthenticationError as exc:
            logging.exception("SMTP auth failed (STARTTLS)")
            return False, str(exc)
        except Exception as exc:
            logging.exception("Failed to send email (both SSL and STARTTLS)")
            return False, str(exc)


def _infer_smtp_defaults(sender_email):
    sender_email = (sender_email or "").strip().lower()
    if sender_email.endswith("@gmail.com"):
        return "smtp.gmail.com", "587"
    if sender_email.endswith("@hotmail.com") or sender_email.endswith("@outlook.com") or sender_email.endswith("@live.com"):
        return "smtp.office365.com", "587"
    return "smtp.office365.com", "587"


def send_order_confirmation_email(order_or_id):
    order = _get_order(order_or_id)
    if not order:
        return False, "Order not found."
    if order.get("status") not in ("Confirmed", "Pranuar", "Konfirmuar"):
        return False, "Order is not confirmed."
    recipient_email = order.get("email")
    if not recipient_email:
        return False, "Order email is missing."

    cfg = _get_smtp_config()
    short_id = str(order.get("_id"))[-6:]
    items = order.get("items") or []
    items_html = _order_items_html(items)

    created_at = order.get("created_at")
    created_at_text = created_at.strftime("%d.%m.%Y %H:%M") if isinstance(created_at, datetime) else str(created_at or "")

    body_html = f"""
<h2 style="margin:0 0 4px;color:#0f172a;font-size:1.15rem;">Porosia #{short_id} u konfirmua!</h2>
<p style="margin:0 0 16px;color:#64748b;font-size:0.9rem;">Përshëndetje {order.get('fullname', '')}, porosia juaj u pranua dhe po përgatitet.</p>
{_order_timeline_html(1)}
<div style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin:0 0 20px;font-size:0.88rem;line-height:1.9;color:#374151;">
  <strong>Nr. Porosisë:</strong> #{short_id}<br>
  <strong>Data:</strong> {created_at_text}<br>
  <strong>Pagesa:</strong> {order.get('payment_method', 'N/A')}<br>
  <strong>Dërgesa:</strong> {order.get('shipping_method', 'N/A')}<br>
  <strong>Adresa:</strong> {order.get('address', '')}, {order.get('city', '')}, {order.get('country', '')}
</div>
<div style="margin:0 0 20px;">
  <div style="font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Produktet e porositura</div>
  {items_html}
</div>
<table cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#f8fafc;border:1px solid #e5e7eb;border-radius:10px;border-collapse:collapse;">
  <tr>
    <td style="padding:10px 16px;font-size:13px;color:#374151;">Nëntotali:</td>
    <td style="padding:10px 16px;font-size:13px;color:#374151;text-align:right;font-weight:600;">&nbsp;&nbsp;{_format_currency(order.get('total_price'))}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;font-size:13px;color:#374151;border-top:1px solid #e5e7eb;">Dërgesa:</td>
    <td style="padding:10px 16px;font-size:13px;color:#374151;text-align:right;border-top:1px solid #e5e7eb;font-weight:600;">&nbsp;&nbsp;{_format_currency(order.get('shipping_cost'))}</td>
  </tr>
  <tr>
    <td style="padding:12px 16px;font-size:15px;font-weight:700;color:#0f172a;border-top:2px solid #e5e7eb;">Totali:</td>
    <td style="padding:12px 16px;font-size:15px;font-weight:700;color:#0f766e;text-align:right;border-top:2px solid #e5e7eb;">&nbsp;&nbsp;{_format_currency(order.get('grand_total'))}</td>
  </tr>
</table>
<div style="text-align:center;margin:20px 0 4px;">
  <a href="{SITE_BASE_URL}/orders" style="display:inline-block;background:#4F5D4E;color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;">Shiko Porosinë &#8594;</a>
</div>"""

    html = _email_html(f"Porosia #{short_id} · Konfirmuar", body_html, cfg)
    order_lines = [f"- {int(i.get('quantity',1))}x {i.get('name','')} = {_format_currency(i.get('item_total'))}" for i in items]
    text = (f"Porosia #{short_id} u konfirmua!\n\nPërshëndetje {order.get('fullname','')},\n\n"
            f"Data: {created_at_text}\nAdresa: {order.get('address','')}, {order.get('city','')}\n\n"
            + "\n".join(order_lines) +
            f"\n\nTotali: {_format_currency(order.get('grand_total'))}\n\nTel: {PHARMACY_PHONE} · {PHARMACY_EMAIL_CONTACT}")
    subject = f"Porosia #{short_id} u konfirmua"
    ok, msg = _send_simple_email(cfg, recipient_email, subject, text, html)
    if ok:
        mongo.db.orders.update_one(
            {"_id": order["_id"]},
            {"$set": {"confirmation_email_sent": True, "confirmation_email_sent_at": datetime.utcnow()}}
        )
    return ok, msg if ok else (False, msg)

# ---------------------------------------------------------------------------
# Order: Shipped
# ---------------------------------------------------------------------------
def send_order_shipped_email(order_or_id, tracking_number=None):
    order = _get_order(order_or_id)
    if not order:
        return False, "Order not found."
    recipient_email = order.get("email")
    if not recipient_email:
        return False, "Order email missing."

    cfg = _get_smtp_config()
    short_id = str(order.get("_id"))[-6:]
    items_html = _order_items_html(order.get("items") or [])
    tracking_block = ""
    if tracking_number:
        tracking_block = f"""
<div style="background:#f5f7f4;border:1px solid #d4dcd3;border-radius:10px;padding:14px 16px;margin:16px 0;">
  <div style="font-size:12px;color:#64748b;margin-bottom:4px;">Numri i gjurmimit (Flex Posta)</div>
  <div style="font-size:15px;font-weight:700;color:#4F5D4E;letter-spacing:1px;">{tracking_number}</div>
</div>"""

    body_html = f"""
<h2 style="margin:0 0 4px;color:#0f172a;font-size:1.15rem;">Porosia #{short_id} është nisur!</h2>
<p style="margin:0 0 16px;color:#64748b;font-size:0.9rem;">Përshëndetje {order.get('fullname','')}, porosia juaj është në rrugë.</p>
{_order_timeline_html(2)}
{tracking_block}
<div style="margin:16px 0;">
  <div style="font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Produktet e porositura</div>
  {items_html}
</div>
<p style="margin:16px 0 0;font-size:0.88rem;color:#64748b;">Adresa e dërgimit: <strong>{order.get('address','')}, {order.get('city','')}</strong></p>"""

    html = _email_html(f"Porosia #{short_id} · Në Dërgesë", body_html, cfg)
    tracking_text = f"\nNumri i gjurmimit: {tracking_number}" if tracking_number else ""
    text = (f"Porosia #{short_id} është nisur!\n\nPërshëndetje {order.get('fullname','')},\n"
            f"Porosia juaj është në rrugë drejt jush.{tracking_text}\n"
            f"Adresa: {order.get('address','')}, {order.get('city','')}\n\n"
            f"Tel: {PHARMACY_PHONE} · {PHARMACY_EMAIL_CONTACT}")
    subject = f"Porosia #{short_id} është nisur"
    ok, msg = _send_simple_email(cfg, recipient_email, subject, text, html)
    if ok:
        mongo.db.orders.update_one(
            {"_id": order["_id"]},
            {"$set": {"shipped_email_sent": True, "shipped_email_sent_at": datetime.utcnow()}}
        )
    return ok, msg


# ---------------------------------------------------------------------------
# Order: Delivered
# ---------------------------------------------------------------------------
def send_order_delivered_email(order_or_id):
    order = _get_order(order_or_id)
    if not order:
        return False, "Order not found."
    recipient_email = order.get("email")
    if not recipient_email:
        return False, "Order email missing."

    cfg = _get_smtp_config()
    short_id = str(order.get("_id"))[-6:]
    items_html = _order_items_html(order.get("items") or [])

    body_html = f"""
<h2 style="margin:0 0 4px;color:#0f172a;font-size:1.15rem;">Porosia #{short_id} u dorëzua!</h2>
<p style="margin:0 0 16px;color:#64748b;font-size:0.9rem;">Përshëndetje {order.get('fullname','')}, shpresojmë t'i gëzoni produktet.</p>
{_order_timeline_html(3)}
<div style="margin:16px 0;">
  <div style="font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Produktet e porositura</div>
  {items_html}
</div>
<p style="margin:16px 0 0;font-size:0.88rem;color:#64748b;">Nëse keni ndonjë pyetje, jemi këtu për ju. Faleminderit!</p>"""

    html = _email_html(f"Porosia #{short_id} · Dorëzuar", body_html, cfg)
    text = (f"Porosia #{short_id} u dorëzua!\n\nPërshëndetje {order.get('fullname','')},\n"
            f"Porosia juaj është dorëzuar me sukses. Shpresojmë t'i gëzoni produktet!\n\n"
            f"Tel: {PHARMACY_PHONE} · {PHARMACY_EMAIL_CONTACT}")
    subject = f"Porosia #{short_id} u dorëzua"
    ok, msg = _send_simple_email(cfg, recipient_email, subject, text, html)
    if ok:
        mongo.db.orders.update_one(
            {"_id": order["_id"]},
            {"$set": {"delivered_email_sent": True, "delivered_email_sent_at": datetime.utcnow()}}
        )
    return ok, msg


# ---------------------------------------------------------------------------
# Order: Cancelled
# ---------------------------------------------------------------------------
def send_order_cancelled_email(order_or_id, reason=None):
    order = _get_order(order_or_id)
    if not order:
        return False, "Order not found."
    recipient_email = order.get("email")
    if not recipient_email:
        return False, "Order email missing."

    cfg = _get_smtp_config()
    short_id = str(order.get("_id"))[-6:]
    reason_block = (f'<p style="margin:12px 0;color:#64748b;font-size:0.9rem;">Arsyeja: <em>{reason}</em></p>'
                    if reason else "")

    body_html = f"""
<h2 style="margin:0 0 4px;color:#0f172a;font-size:1.15rem;">Porosia #{short_id} u anulua</h2>
<p style="margin:0 0 16px;color:#64748b;font-size:0.9rem;">Përshëndetje {order.get('fullname','')},</p>
{reason_block}
<p style="font-size:0.9rem;">Nëse keni pyetje ose dëshironi të bëni një porosi të re, jemi të disponueshëm:</p>"""

    html = _email_html(f"Porosia #{short_id} · Anuluar", body_html, cfg)
    reason_text = f"\nArsyeja: {reason}" if reason else ""
    text = (f"Porosia #{short_id} u anulua.\n\nPërshëndetje {order.get('fullname','')},{reason_text}\n\n"
            f"Na kontaktoni nëse keni pyetje.\nTel: {PHARMACY_PHONE} · {PHARMACY_EMAIL_CONTACT}")
    subject = f"Porosia #{short_id} u anulua"
    return _send_simple_email(cfg, recipient_email, subject, text, html)


# ---------------------------------------------------------------------------
# Order: Rejected (distinct from cancelled — admin refused to fulfil)
# ---------------------------------------------------------------------------
def send_order_rejected_email(order_or_id, reason=None):
    order = _get_order(order_or_id)
    if not order:
        return False, "Order not found."
    recipient_email = order.get("email")
    if not recipient_email:
        return False, "Order email missing."

    cfg = _get_smtp_config()
    short_id = str(order.get("_id"))[-6:]
    reason_block = ""
    if reason:
        reason_block = f"""
<div style="background:#fef9f0;border:1px solid #fed7aa;border-radius:10px;padding:14px 16px;margin:16px 0;">
  <div style="font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Arsyeja</div>
  <div style="font-size:13px;color:#1f2937;">{reason}</div>
</div>"""

    body_html = f"""
<h2 style="margin:0 0 4px;color:#1a1f18;font-size:1.15rem;">Porosia #{short_id} nuk mund të plotësohet</h2>
<p style="margin:0 0 16px;color:#64748b;font-size:0.9rem;">Përshëndetje {order.get('fullname', '')},</p>
<p style="margin:0 0 12px;font-size:0.9rem;color:#374151;">Na vjen keq, por porosia juaj #{short_id} nuk mund të plotësohet për momentin.</p>
{reason_block}
<p style="margin:12px 0;font-size:0.9rem;color:#374151;">Nëse dëshironi të bëni një porosi të re ose keni pyetje, jemi të disponueshëm për t'ju ndihmuar:</p>
<div style="background:#f5f7f4;border:1px solid #eef0ed;border-radius:10px;padding:14px 16px;margin:16px 0;font-size:13px;color:#374151;line-height:1.8;">
  Tel: {PHARMACY_PHONE}<br>
  Email: <a href="mailto:{PHARMACY_EMAIL_CONTACT}" style="color:#4F5D4E;text-decoration:none;">{PHARMACY_EMAIL_CONTACT}</a><br>
  {PHARMACY_ADDRESS}
</div>
<p style="font-size:0.85rem;color:#8a9186;">Faleminderit për mirëkuptimin tuaj.</p>"""

    html = _email_html(f"Porosia #{short_id} · Refuzuar", body_html, cfg)
    reason_text = f"\nArsyeja: {reason}" if reason else ""
    text = (f"Porosia #{short_id} nuk mund të plotësohet.\n\nPërshëndetje {order.get('fullname','')},{reason_text}\n\n"
            f"Na kontaktoni:\nTel: {PHARMACY_PHONE} · {PHARMACY_EMAIL_CONTACT}")
    subject = f"Informacion mbi porosinë #{short_id}"
    return _send_simple_email(cfg, recipient_email, subject, text, html)


# ---------------------------------------------------------------------------
# Welcome email (on registration)
# ---------------------------------------------------------------------------
def _promo_blocks_html(base, offer_products=None, cat_images=None):
    """Build the shared offers + categories HTML block used in welcome emails."""
    from models.image_utils import cld

    # Hardcoded category images (same as home page)
    _CAT_META = [
        ('Dermokozmetikë',        'Kujdes profesional për lëkurën',   f'{base}/products?category=Dermokozmetik%C3%AB',               '#eef5ee', '#2d5a2d',
         'https://res.cloudinary.com/drljgepgy/image/upload/v1782338006/ChatGPT_Image_Jun_24_2026_at_11_23_35_PM_uqsw1l.png'),
        ('Suplemente & Vitamina', 'Shëndeti fillon nga brenda',        f'{base}/products?category=Suplemente+%26+Vitamina',           '#eef2ff', '#3730a3',
         'https://res.cloudinary.com/drljgepgy/image/upload/v1782338009/ChatGPT_Image_Jun_24_2026_at_11_25_37_PM_wpohzj.png'),
        ('Kujdes Personal & Higjienë', 'Produkte të përditshme',      f'{base}/products?category=Kujdes+Personal+%26+Higjiën%C3%AB', '#fff7ed', '#92400e',
         'https://res.cloudinary.com/drljgepgy/image/upload/v1782338009/ChatGPT_Image_Jun_24_2026_at_11_27_26_PM_om9wnq.png'),
    ]

    html = ''

    # ── Offers row ──────────────────────────────────────────────────────────
    if offer_products:
        cols = ''
        for p in offer_products[:3]:
            pid   = str(p['_id'])
            pname = p.get('name', '')[:40]
            orig  = p.get('price') or 0
            disc  = p.get('discount_price') or orig
            img   = cld(p.get('image_url', ''), 300)
            pct   = int(round((orig - disc) / orig * 100)) if orig > disc else 0
            pct_badge = f'<div style="display:inline-block;background:#dc2626;color:#fff;font-size:9px;font-weight:800;padding:2px 6px;border-radius:20px;margin-bottom:6px;">-{pct}%</div>' if pct else ''
            # contain keeps full product visible; white bg hides any transparent areas cleanly
            img_tag = f'<img src="{img}" width="120" height="120" alt="{pname}" style="width:120px;height:120px;object-fit:contain;background:#fff;border-radius:6px;display:block;margin:0 auto 8px;">' if img else ''
            cols += f"""
      <td style="width:33%;padding:4px;vertical-align:top;">
        <a href="{base}/product/{pid}" style="text-decoration:none;display:block;height:100%;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:10px;text-align:center;">
          {img_tag}
          {pct_badge}
          <div style="font-size:11px;font-weight:600;color:#1a1f18;line-height:1.3;margin-bottom:5px;">{pname}</div>
          <div style="font-size:12px;font-weight:800;color:#4F5D4E;">{disc:.0f} €</div>
          {"" if not pct else f'<div style="font-size:10px;color:#9ca3af;text-decoration:line-through;">{orig:.0f} €</div>'}
        </a>
      </td>"""
        html += f"""
<p style="margin:0 0 8px;font-weight:700;color:#1a1f18;font-size:0.85rem;">Ofertat e momentit:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;"><tr>{cols}</tr></table>"""

    # ── Categories row ───────────────────────────────────────────────────────
    cat_cells = ''
    for cat_name, cat_desc, cat_url, bg, fg, cat_img_url in _CAT_META:
        img_src = cld(cat_img_url, 300)
        img_tag = f'<img src="{img_src}" width="160" height="80" alt="{cat_name}" style="width:100%;height:80px;object-fit:cover;border-radius:6px;display:block;margin-bottom:8px;">'
        cat_cells += f"""
      <td style="width:33%;padding:4px;vertical-align:top;">
        <a href="{cat_url}" style="text-decoration:none;display:block;background:{bg};border-radius:10px;overflow:hidden;padding:10px;text-align:center;">
          {img_tag}
          <div style="font-size:11px;font-weight:800;color:{fg};margin-bottom:3px;line-height:1.3;">{cat_name}</div>
          <div style="font-size:9px;color:#6b7280;line-height:1.4;margin-bottom:6px;">{cat_desc}</div>
          <div style="font-size:10px;font-weight:700;color:{fg};">Shiko &rarr;</div>
        </a>
      </td>"""
    html += f"""
<p style="margin:0 0 8px;font-weight:700;color:#1a1f18;font-size:0.85rem;">Eksploroni kategorit tona:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;"><tr>{cat_cells}</tr></table>"""

    return html


def send_welcome_email(recipient_email, username, offer_products=None, cat_images=None):
    cfg = _get_smtp_config()
    name = cfg["sender_name"]
    base = SITE_BASE_URL.rstrip('/')

    promo = _promo_blocks_html(base, offer_products, cat_images)

    body_html = f"""
<h2 style="margin:0 0 6px;color:#1a1f18;font-size:1.1rem;">Mirë se vini, {username}!</h2>
<p style="margin:0 0 18px;color:#64748b;font-size:0.9rem;">Faleminderit që u regjistruat. Jemi këtu për çdo nevojë shëndetësore dhe kozmetike.</p>

<div style="background:#f5f7f4;border:1px solid #d4dcd3;border-radius:10px;padding:14px 16px;margin:0 0 20px;">
  <p style="margin:0 0 8px;font-weight:700;color:#4F5D4E;font-size:0.85rem;">Me llogarinë tuaj mund të:</p>
  <ul style="margin:0;padding-left:16px;color:#374151;line-height:1.9;font-size:0.85rem;">
    <li>Shikoni historikun e të gjitha porosive tuaja</li>
    <li>Ruani adresën tuaj për checkout më të shpejtë</li>
    <li>Menaxhoni listën tuaj të dëshirave nga çdo pajisje</li>
  </ul>
</div>

{promo}

<div style="text-align:center;margin-bottom:4px;">
  <a href="{base}/products?discount_only=true" style="display:inline-block;background:#4F5D4E;color:#fff;text-decoration:none;font-size:13px;font-weight:700;padding:11px 30px;border-radius:9px;">Shiko Ofertat Tona</a>
</div>"""

    html = _email_html("Mirë se vini!", body_html, cfg)
    text = (f"Mirë se vini, {username}!\n\nFaleminderit që u regjistruat në {name}.\n\n"
            f"Eksploroni: {base}/products\n"
            f"Ofertat: {base}/products?discount_only=true\n\n"
            f"Tel: {PHARMACY_PHONE} · {PHARMACY_EMAIL_CONTACT}")
    subject = f"Mirë se vini në {name}!"
    return _send_simple_email(cfg, recipient_email, subject, text, html)


# ---------------------------------------------------------------------------
# Newsletter
# ---------------------------------------------------------------------------
def send_newsletter_email(recipient_email, subject, content_html, content_text):
    cfg = _get_smtp_config()
    html = _email_html(subject, content_html, cfg)
    return _send_simple_email(cfg, recipient_email, subject, content_text, html)


def send_admin_digest(recipient_email, period_label, stats):
    """Send an order summary digest to the admin email.

    stats dict keys:
        total_orders, total_revenue, pending, konfirmuar, dergese, dorezuar,
        anuluar, recent_orders (list of dicts with fullname, grand_total, status, created_at)
    """
    cfg = _get_smtp_config()
    subject = f"Digest Porosive — {period_label}"

    def status_color(s):
        s = (s or '').lower()
        if 'pritje' in s or s == 'pending':   return '#f59e0b'
        if 'konfirm' in s or 'confirm' in s:  return '#3b82f6'
        if 'dërgese' in s or 'deliver' in s:  return '#8b5cf6'
        if 'dorëzuar' in s or s == 'delivered': return '#10b981'
        return '#ef4444'

    rows_html = ''
    for o in (stats.get('recent_orders') or []):
        date_str = o['created_at'].strftime('%d.%m.%Y %H:%M') if o.get('created_at') else '—'
        sc = status_color(o.get('status', ''))
        rows_html += f"""
        <tr>
          <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; font-size:13px; color:#1e293b;">{o.get('fullname','—')}</td>
          <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; font-size:13px; color:#0f766e; font-weight:700;">€{float(o.get('grand_total',0)):.2f}</td>
          <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; font-size:12px;">
            <span style="background:{sc}22; color:{sc}; padding:3px 8px; border-radius:6px; font-weight:700;">{o.get('status','—')}</span>
          </td>
          <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; font-size:12px; color:#94a3b8;">{date_str}</td>
        </tr>"""

    content_html = f"""
    <h2 style="font-size:1.3rem; font-weight:800; color:#1e293b; margin:0 0 1.5rem;">
      Rezymeja e Porosive — {period_label}
    </h2>

    <!-- KPI grid -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:1.5rem;">
      <tr>
        <td style="width:25%; padding:0 6px 0 0;">
          <div style="background:#f0fdf4; border-radius:12px; padding:16px; text-align:center;">
            <div style="font-size:1.6rem; font-weight:800; color:#0f766e;">€{float(stats.get('total_revenue',0)):.0f}</div>
            <div style="font-size:0.75rem; color:#64748b; font-weight:600; text-transform:uppercase; margin-top:4px;">Të Ardhura</div>
          </div>
        </td>
        <td style="width:25%; padding:0 6px;">
          <div style="background:#eff6ff; border-radius:12px; padding:16px; text-align:center;">
            <div style="font-size:1.6rem; font-weight:800; color:#1d4ed8;">{stats.get('total_orders',0)}</div>
            <div style="font-size:0.75rem; color:#64748b; font-weight:600; text-transform:uppercase; margin-top:4px;">Porosi</div>
          </div>
        </td>
        <td style="width:25%; padding:0 6px;">
          <div style="background:#fef3c7; border-radius:12px; padding:16px; text-align:center;">
            <div style="font-size:1.6rem; font-weight:800; color:#92400e;">{stats.get('pending',0)}</div>
            <div style="font-size:0.75rem; color:#64748b; font-weight:600; text-transform:uppercase; margin-top:4px;">Në Pritje</div>
          </div>
        </td>
        <td style="width:25%; padding:0 0 0 6px;">
          <div style="background:#f0fdf4; border-radius:12px; padding:16px; text-align:center;">
            <div style="font-size:1.6rem; font-weight:800; color:#16a34a;">{stats.get('dorezuar',0)}</div>
            <div style="font-size:0.75rem; color:#64748b; font-weight:600; text-transform:uppercase; margin-top:4px;">Dorëzuar</div>
          </div>
        </td>
      </tr>
    </table>

    <!-- Recent orders table -->
    <h3 style="font-size:0.95rem; font-weight:700; color:#1e293b; margin:0 0 0.75rem;">Porositë e fundit</h3>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; border:1px solid #e2e8f0; border-radius:10px; overflow:hidden;">
      <thead>
        <tr style="background:#f8fafc;">
          <th style="padding:10px 12px; text-align:left; font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase;">Klienti</th>
          <th style="padding:10px 12px; text-align:left; font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase;">Totali</th>
          <th style="padding:10px 12px; text-align:left; font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase;">Statusi</th>
          <th style="padding:10px 12px; text-align:left; font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase;">Data</th>
        </tr>
      </thead>
      <tbody>{rows_html if rows_html else '<tr><td colspan="4" style="padding:16px; text-align:center; color:#94a3b8; font-size:13px;">Nuk ka porosi në këtë periudhë.</td></tr>'}</tbody>
    </table>

    <div style="margin-top:1.5rem; text-align:center;">
      <a href="{SITE_BASE_URL}/admin/orders" style="display:inline-block; padding:12px 28px; background:#4F5D4E; color:#fff; text-decoration:none; border-radius:10px; font-weight:700; font-size:0.9rem;">
        Shiko Të Gjitha Porositë →
      </a>
    </div>
    """

    text_body = (
        f"Digest Porosive — {period_label}\n\n"
        f"Të Ardhura: €{float(stats.get('total_revenue',0)):.2f}\n"
        f"Porosi: {stats.get('total_orders',0)}\n"
        f"Në Pritje: {stats.get('pending',0)}\n"
        f"Dorëzuar: {stats.get('dorezuar',0)}\n\n"
        f"Shiko porositë: {SITE_BASE_URL}/admin/orders"
    )

    html = _email_html(subject, content_html, cfg)
    return _send_simple_email(cfg, recipient_email, subject, text_body, html)


def send_new_order_notification(order: dict):
    """Send an instant email to the admin when a new order is placed."""
    notify_email = (
        os.getenv("ORDER_NOTIFY_EMAIL")
        or os.getenv("ADMIN_DIGEST_EMAIL")
        or os.getenv("SMTP_USER")
        or os.getenv("MAIL_USERNAME")
    )
    if not notify_email:
        return

    cfg = _get_smtp_config()
    fullname = order.get("fullname", "—")
    phone    = order.get("phone", "—")
    city     = order.get("city", "—")
    address  = order.get("address", "—")
    payment  = order.get("payment_method", "—")
    shipping = order.get("shipping_method", "delivery")
    grand    = float(order.get("grand_total", 0))
    items    = order.get("items", [])

    subject = f"Porosi e Re — {fullname} — €{grand:.2f}"

    items_html = _order_items_html(items)

    content_html = f"""
    <h2 style="font-size:1.2rem;font-weight:800;color:#1a1f18;margin:0 0 1.25rem;">
      Porosi e Re ka Ardhur
    </h2>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:1.25rem;">
      <tr>
        <td style="width:50%;padding:0 8px 0 0;">
          <div style="background:#f5f7f4;border:1px solid #eef0ed;border-radius:12px;padding:14px 16px;">
            <div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.5px;color:#8a9186;margin-bottom:8px;">Klienti</div>
            <div style="font-size:14px;font-weight:700;color:#1a1f18;">{fullname}</div>
            <div style="font-size:12px;color:#475569;margin-top:3px;">{phone}</div>
            <div style="font-size:12px;color:#475569;margin-top:2px;">{address}, {city}</div>
          </div>
        </td>
        <td style="width:50%;padding:0 0 0 8px;">
          <div style="background:#f5f7f4;border:1px solid #eef0ed;border-radius:12px;padding:14px 16px;">
            <div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.5px;color:#8a9186;margin-bottom:8px;">Detajet</div>
            <div style="font-size:12px;color:#475569;"><strong>Pagesa:</strong> {payment}</div>
            <div style="font-size:12px;color:#475569;margin-top:3px;"><strong>Dërgesa:</strong> {"Marrje në dyqan" if shipping == "pickup" else "Dërgesë"}</div>
            <div style="font-size:16px;font-weight:800;color:#4F5D4E;margin-top:8px;">€{grand:.2f}</div>
          </div>
        </td>
      </tr>
    </table>

    <div style="font-size:11px;font-weight:700;color:#8a9186;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Produktet e porositura</div>
    {items_html}

    <div style="text-align:center;margin-top:1.5rem;">
      <a href="{SITE_BASE_URL}/admin/orders" style="display:inline-block;background:#4F5D4E;color:#fff;text-decoration:none;font-size:14px;font-weight:700;padding:12px 32px;border-radius:10px;">
        Shiko Porosinë në Panel →
      </a>
    </div>
    """

    text_body = (
        f"Porosi e Re: {fullname} — €{grand:.2f}\n"
        f"Telefoni: {phone}\n"
        f"Adresa: {address}, {city}\n"
        f"Pagesa: {payment}\n\n"
        + "\n".join(f"  {it.get('quantity',1)}x {it.get('name','')} — €{float(it.get('item_total',0)):.2f}" for it in items)
        + f"\n\nShiko: {SITE_BASE_URL}/admin/orders"
    )

    html = _email_html(subject, content_html, cfg)
    try:
        _send_simple_email(cfg, notify_email, subject, text_body, html)
    except Exception:
        pass  # never block the order from being placed


def send_email_in_background(func, *args, **kwargs):
    """Run an email-sending function in a non-daemon background thread.

    The calling request returns immediately; the thread completes on its own.
    Non-daemon so gunicorn workers don't kill it before it finishes.
    """
    t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=False)
    t.start()
