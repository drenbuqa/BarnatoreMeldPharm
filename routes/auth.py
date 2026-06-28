import os
import threading
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from models.user import User
from models.db import mongo
from flask_bcrypt import Bcrypt

def _get_shared_oauth():
    """Return the single OAuth instance initialized in app.py."""
    from app import oauth
    return oauth

auth = Blueprint('auth', __name__)
bcrypt = Bcrypt()

# Limiter reference — resolved lazily from the app
def _get_limiter():
    from app import limiter
    return limiter


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        _get_limiter().limit("10 per minute")(lambda: None)()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.get_by_email(email)

        # Brute-force lockout check
        if user:
            locked_until = user._data.get('locked_until')
            if locked_until and datetime.utcnow() < locked_until:
                remaining = int((locked_until - datetime.utcnow()).total_seconds() // 60) + 1
                flash(f'Llogaria është bllokuar. Provoni përsëri pas {remaining} minutash.', 'danger')
                return redirect(url_for('auth.login'))

        if user and user.password and bcrypt.check_password_hash(user.password, password):
            # Reset failed attempts on success
            mongo.db.users.update_one({'_id': user._data['_id']},
                {'$set': {'failed_logins': 0, 'locked_until': None}})

            login_user(user)
            try:
                db_cart = User.get_cart(user.id)
                session_cart = session.get('cart', {})
                if not isinstance(db_cart, dict):
                    db_cart = {}
                for pid, qty in session_cart.items():
                    db_cart[pid] = int(db_cart.get(pid, 0)) + int(qty)
                User.update_cart(user.id, db_cart)
                session['cart'] = db_cart
                session.modified = True
            except Exception as e:
                current_app.logger.error(f"Cart sync error: {e}")

            flash('Kyçja ishte e suksesshme!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page if next_page and next_page.startswith('/') else url_for('main.index'))
        else:
            # Track failed login attempt
            if user:
                fails = int(user._data.get('failed_logins', 0)) + 1
                update = {'failed_logins': fails}
                if fails >= 5:
                    update['locked_until'] = datetime.utcnow() + timedelta(minutes=15)
                mongo.db.users.update_one({'_id': user._data['_id']}, {'$set': update})
            flash('Kyçja dështoi. Kontrolloni emailin dhe fjalëkalimin.', 'danger')
            return redirect(request.referrer or url_for('auth.login'))

    return render_template('login.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        _get_limiter().limit("5 per minute")(lambda: None)()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if len(password) < 8 or not any(c.isdigit() for c in password):
            flash('Fjalëkalimi duhet të jetë të paktën 8 karaktere dhe të përmbajë një numër.', 'warning')
            return redirect(request.referrer or url_for('auth.register'))

        if User.get_by_email(email):
            flash('Email është regjistruar tashmë.', 'warning')
            return redirect(request.referrer or url_for('auth.register'))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User.create(username, email, hashed_pw)
        login_user(user)

        session_cart = session.get('cart', {})
        if session_cart:
            User.update_cart(user.id, session_cart)

        def _send_welcome():
            try:
                from models.email_utils import send_welcome_email
                send_welcome_email(email, username)
            except Exception:
                pass
        threading.Thread(target=_send_welcome, daemon=True).start()

        flash('Llogaria u krijua! Mirë se erdhet.', 'success')
        return redirect(url_for('main.index'))

    return render_template('register.html')


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('guest_mode', None)
    session.pop('cart', None)
    return redirect(url_for('main.index'))


# ------------------------------------------------------------------
# Google OAuth
# ------------------------------------------------------------------
@auth.route('/login/google')
def google_login():
    oauth = _get_shared_oauth()
    redirect_uri = _google_redirect_uri()
    return oauth.google.authorize_redirect(redirect_uri)


@auth.route('/login/google/callback')
def google_callback():
    # If there's an error param from Google (user denied, etc.), bail early
    if request.args.get('error'):
        flash('Kyçja me Google u anulua. Provoni përsëri.', 'warning')
        return redirect(url_for('auth.login'))

    oauth = _get_shared_oauth()
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo')
        if not userinfo:
            userinfo = oauth.google.userinfo()
    except Exception as e:
        err_str = str(e).lower()
        current_app.logger.error(f"Google OAuth callback error: {e}")
        # State mismatch / CSRF warning — just restart the OAuth flow
        if 'state' in err_str or 'csrf' in err_str or 'mismatch' in err_str:
            return redirect(url_for('auth.google_login'))
        flash('Kyçja me Google dështoi. Provoni përsëri.', 'danger')
        return redirect(url_for('auth.login'))
    if not userinfo:
        flash('Nuk u mor të dhënat nga Google. Provoni përsëri.', 'danger')
        return redirect(url_for('auth.login'))
    google_email = userinfo.get('email', '').lower()
    google_name = userinfo.get('name', '') or userinfo.get('given_name', 'Perdorues')
    google_id = str(userinfo.get('sub', ''))
    avatar = userinfo.get('picture', '')

    if not google_email:
        flash('Nuk u mor emaili nga Google. Provoni metodë tjetër.', 'danger')
        return redirect(url_for('auth.login'))

    # Find or create user
    user = User.get_by_email(google_email)
    if not user:
        user = User.create_google(google_name, google_email, google_id, avatar)
    else:
        # Update google_id if missing
        User.link_google(user.id, google_id, avatar)

    login_user(user)

    # Merge guest cart
    try:
        session_cart = session.get('cart', {})
        if session_cart:
            db_cart = User.get_cart(user.id) or {}
            for pid, qty in session_cart.items():
                db_cart[pid] = int(db_cart.get(pid, 0)) + int(qty)
            User.update_cart(user.id, db_cart)
            session['cart'] = db_cart
            session.modified = True
    except Exception:
        pass

    flash(f'Mirë se erdhet, {user.username}!', 'success')
    return redirect(url_for('main.index'))


# ------------------------------------------------------------------
# Password Reset
# ------------------------------------------------------------------
@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        _get_limiter().limit("5 per hour")(lambda: None)()
        email = request.form.get('email', '').strip().lower()
        user = User.get_by_email(email)
        if user and user.password:  # only for non-Google accounts
            token = secrets.token_urlsafe(32)
            expires = datetime.utcnow() + timedelta(hours=1)
            mongo.db.password_resets.insert_one({
                'user_id': user.id,
                'token': token,
                'expires': expires,
                'used': False,
            })
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            def _send():
                try:
                    from models.email_utils import _get_smtp_config, _email_html, _send_simple_email, PHARMACY_PHONE, PHARMACY_EMAIL_CONTACT
                    cfg = _get_smtp_config()
                    body = f"""
<div style="text-align:center;padding:8px 0 24px;">
  <h2 style="margin:0 0 10px;font-size:1.15rem;color:#0f172a;">Rivendosja e fjalëkalimit</h2>
  <p style="color:#64748b;margin:0 0 28px;font-size:0.9rem;">Kemi marrë një kërkesë për ndryshim të fjalëkalimit të llogarisë tuaj.</p>
  <a href="{reset_url}" style="display:inline-block;background:#0f766e;color:#fff;text-decoration:none;padding:14px 32px;border-radius:10px;font-weight:700;font-size:0.95rem;">Rivendos fjalëkalimin &#8594;</a>
  <p style="color:#94a3b8;font-size:0.82rem;margin:24px 0 0;">Ky link skadon pas 1 ore.<br>Nëse nuk e keni kërkuar ju, mund ta injoroni këtë email.</p>
</div>"""
                    html = _email_html("Rivendosja e fjalëkalimit", body, cfg)
                    _send_simple_email(cfg, email, "Rivendos fjalëkalimin — Barnatore Meld Pharm",
                                       f"Rivendos fjalëkalimin: {reset_url}", html)
                except Exception as e:
                    current_app.logger.error(f"Password reset email error: {e}")
            threading.Thread(target=_send, daemon=True).start()
            flash('Emaili u dërgua! Kontrolloni kutinë tuaj postare dhe klikoni linkun për të rivendosur fjalëkalimin.', 'success')
        else:
            flash('Nuk gjetëm asnjë llogari me këtë email adresë.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    return render_template('forgot_password.html')


@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    record = mongo.db.password_resets.find_one({'token': token, 'used': False})
    if not record or record['expires'] < datetime.utcnow():
        flash('Ky link ka skaduar ose është i pavlefshëm.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        bcrypt_inst = Bcrypt(current_app)
        password = request.form.get('password', '')
        if len(password) < 8 or not any(c.isdigit() for c in password):
            flash('Fjalëkalimi duhet të ketë të paktën 8 karaktere dhe 1 numër.', 'warning')
            return redirect(request.url)
        hashed = bcrypt_inst.generate_password_hash(password).decode('utf-8')
        User.set_password(record['user_id'], hashed)
        mongo.db.password_resets.update_one({'_id': record['_id']}, {'$set': {'used': True}})
        flash('Fjalëkalimi u ndryshua me sukses! Mund të kyçeni tani.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)


def _google_redirect_uri():
    return url_for('auth.google_callback', _external=True)
