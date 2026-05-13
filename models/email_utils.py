import logging
import os
import smtplib
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

    if order.get("status") not in ("Confirmed", "Pranuar"):
        return False, "Order is not confirmed."

    recipient_email = order.get("email")
    if not recipient_email:
        return False, "Order email is missing."

    sender_email = (
        os.getenv("PHARMACY_FROM_EMAIL")
        or os.getenv("SMTP_FROM_EMAIL")
        or os.getenv("MAIL_DEFAULT_SENDER")
        or os.getenv("SMTP_USER")
        or os.getenv("MAIL_USERNAME")
    )
    smtp_host_default, smtp_port_default = _infer_smtp_defaults(sender_email)
    smtp_host = os.getenv("SMTP_HOST") or os.getenv("MAIL_SERVER") or smtp_host_default
    smtp_port_value = os.getenv("SMTP_PORT") or os.getenv("MAIL_PORT") or smtp_port_default
    smtp_port = int(smtp_port_value)
    smtp_user = (
        os.getenv("SMTP_USER")
        or os.getenv("MAIL_USERNAME")
        or sender_email
    )
    smtp_password = os.getenv("SMTP_PASSWORD") or os.getenv("MAIL_PASSWORD")
    sender_name = os.getenv("PHARMACY_NAME", "Barnatore Meld Pharm")
    reply_to_email = os.getenv("PHARMACY_REPLY_TO") or sender_email
    use_tls = (os.getenv("SMTP_USE_TLS") or os.getenv("MAIL_USE_TLS") or "true").lower() != "false"

    if not smtp_host or not smtp_user or not smtp_password or not sender_email:
        return False, "SMTP configuration is incomplete. Set PHARMACY_FROM_EMAIL and SMTP_PASSWORD in .env."

    items = order.get("items") or []
    order_lines = []
    for item in items:
        name = item.get("name", "Product")
        quantity = int(item.get("quantity", 1) or 1)
        line_total = _format_currency(item.get("item_total"))
        unit_price = _format_currency(item.get("price"))
        order_lines.append(f"- {quantity} x {name} @ {unit_price} = {line_total}")

    created_at = order.get("created_at")
    if isinstance(created_at, datetime):
        created_at_text = created_at.strftime("%d.%m.%Y %H:%M")
    else:
        created_at_text = str(created_at or "")

    subject = f"Porosia juaj #{str(order.get('_id'))[-6:]} është konfirmuar"
    text_body = "\n".join([
                f"Përshëndetje {order.get('fullname', '')},",
        "",
                f"Porosia juaj është konfirmuar nga {sender_name}.",
        "",
        f"Order ID: {order.get('_id')}",
                f"Data e porosisë: {created_at_text}",
                f"Statusi: {order.get('status')}",
                f"Mënyra e pagesës: {order.get('payment_method', 'N/A')}",
                f"Mënyra e dërgesës: {order.get('shipping_method', 'N/A')}",
                f"Adresa e dërgesës: {order.get('address', '')}, {order.get('city', '')}, {order.get('country', '')}",
        "",
                "Produktet e porositura:",
        *order_lines,
        "",
        f"Nëntotali: {_format_currency(order.get('total_price'))}",
        f"Dërgesa: {_format_currency(order.get('shipping_cost'))}",
        f"Totali: {_format_currency(order.get('grand_total'))}",
        "",
        "Faleminderit që zgjodhët Barnatore Meld Pharm.",
        "Porosia juaj është duke u përgatitur dhe do të jetë gati së shpejti.",
        "Për çdo pyetje na kontaktoni në +383 045 590455.",
        sender_name,
    ])

    logo_cid = make_msgid(domain="meldpharm.local")
    logo_path = os.path.join(os.path.dirname(__file__), "..", "static", "favicon.png")
    logo_src = f"cid:{logo_cid[1:-1]}"
    logo_attachment = None
    try:
        with open(os.path.abspath(logo_path), "rb") as logo_file:
            logo_attachment = logo_file.read()
    except OSError:
        logo_attachment = None

    html_items = "".join(
        f"<tr><td style='padding:8px 0;border-bottom:1px solid #eee;'>{int(item.get('quantity', 1) or 1)} x {item.get('name', 'Product')}</td><td style='padding:8px 0;border-bottom:1px solid #eee;text-align:right;'>{_format_currency(item.get('item_total'))}</td></tr>"
        for item in items
    )
    html_body = f"""
        <div style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6; max-width: 680px; margin: 0 auto;">
            <div style="display:flex; align-items:center; gap:12px; margin: 0 0 20px; padding: 16px 18px; background: linear-gradient(135deg, #0f766e, #14b8a6); border-radius: 16px; color: white;">
                <img src="{logo_src}" alt="Barnatore Meld Pharm" width="44" height="44" style="display:block; width:44px; height:44px; border-radius: 12px; background: rgba(255,255,255,0.92); padding: 6px; object-fit: contain;">
                <div>
                    <div style="font-size: 1.05rem; font-weight: 700;">Barnatore Meld Pharm</div>
                    <div style="font-size: 0.9rem; opacity: 0.92;">Porosia u konfirmua</div>
                </div>
            </div>

            <h2 style="margin: 0 0 12px; color: #0f172a;">Porosia juaj është konfirmuar</h2>
            <p style="margin: 0 0 12px;">Përshëndetje {order.get('fullname', '')},</p>
            <p style="margin: 0 0 18px;">Faleminderit për porosinë tuaj. E kemi pranuar dhe konfirmuar me sukses. Ekipi ynë po e përgatit dhe porosia do të jetë gati së shpejti.</p>
      <p><strong>Order ID:</strong> {order.get('_id')}<br>
            <strong>Data e porosisë:</strong> {created_at_text}<br>
            <strong>Statusi:</strong> Pranuar<br>
            <strong>Mënyra e pagesës:</strong> {order.get('payment_method', 'N/A')}<br>
            <strong>Mënyra e dërgesës:</strong> {order.get('shipping_method', 'N/A')}<br>
            <strong>Adresa e dërgesës:</strong> {order.get('address', '')}, {order.get('city', '')}, {order.get('country', '')}</p>
            <table style="width:100%;border-collapse:collapse;margin:22px 0; background:#fff; border:1px solid #e5e7eb; border-radius:14px; overflow:hidden;">
        <thead>
          <tr>
                        <th align="left" style="padding:12px 14px;border-bottom:1px solid #e5e7eb;background:#f8fafc;">Produkti</th>
                        <th align="right" style="padding:12px 14px;border-bottom:1px solid #e5e7eb;background:#f8fafc;">Totali</th>
          </tr>
        </thead>
        <tbody>
          {html_items}
        </tbody>
      </table>
            <div style="background:#f8fafc; border:1px solid #e5e7eb; border-radius:14px; padding:16px 18px;">
                <p style="margin:0 0 6px;"><strong>Nëntotali:</strong> {_format_currency(order.get('total_price'))}</p>
                <p style="margin:0 0 6px;"><strong>Dërgesa:</strong> {_format_currency(order.get('shipping_cost'))}</p>
                <p style="margin:0;"><strong>Totali:</strong> {_format_currency(order.get('grand_total'))}</p>
            </div>
            <p style="margin:18px 0 0;">Për çdo pyetje ose ndihmë, na kontaktoni në <strong>+383 045 590455</strong>.</p>
            <p style="margin:8px 0 0;">Barnatore Meld Pharm</p>
    </div>
    """

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{sender_name} <{sender_email}>"
    message["To"] = recipient_email
    message["Reply-To"] = reply_to_email
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    if logo_attachment:
        # Safely find the HTML alternative part and attach related image
        html_part = None
        try:
            for part in message.iter_parts():
                ctype = part.get_content_type()
                if ctype == 'text/html' or part.get_content_subtype() == 'html':
                    html_part = part
                    break
        except Exception:
            html_part = None

        if html_part is not None:
            try:
                html_part.add_related(logo_attachment, maintype="image", subtype="png", cid=logo_cid)
            except Exception:
                # If adding related fails for any reason, continue without breaking email send
                pass

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(message)

        mongo.db.orders.update_one(
            {"_id": order["_id"]},
            {"$set": {
                "confirmation_email_sent": True,
                "confirmation_email_sent_at": datetime.utcnow()
            }}
        )
        return True, "Confirmation email sent."
    except SMTPAuthenticationError as exc:
        error_text = str(exc)
        if "5.7.139" in error_text or "basic authentication is disabled" in error_text.lower():
            return False, "Hotmail/Microsoft blocked password-based SMTP login. Use a Hotmail app password (with 2-step verification enabled) or a Microsoft Graph/SMTP relay setup."
        logging.exception("SMTP authentication failed")
        return False, error_text
    except Exception as exc:
        logging.exception("Failed to send order confirmation email")
        return False, str(exc)