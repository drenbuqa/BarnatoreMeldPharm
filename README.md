# Barnatore Meld Pharm - E-Commerce Pharmacy Platform

A fully functional e-commerce platform built for a pharmacy business, handling real customer orders in production. The platform covers the complete shopping experience for customers and provides a comprehensive management system for administrators.

Live URL: https://barnatoremeldpharm.com

---

## Features

### Customer Side
- Browse and search 800+ non-prescription pharmacy products across 7 categories
- Add products to cart, save favourites, and view active offers
- Place orders with automatic email notifications triggered at each status change
- Google OAuth login for quick and secure authentication

### Admin Dashboard
- Order management — view, filter, and update order statuses
- Revenue analytics and sales performance tracking
- Product management — create, edit, and delete listings
- Offer and banner management
- User administration
- Newsletter management — create campaigns and send emails to active subscribers

---

## Tech Stack

- **Backend:** Python, Flask
- **Database:** MongoDB
- **Frontend:** HTML, CSS, JavaScript
- **Authentication:** Google OAuth
- **Email:** Automated transactional emails
- **Deployment:** Render (free tier)

---

## Project Structure

```
BarnatoreMeldPharm/
├── models/          # MongoDB data models
├── routes/          # Flask route handlers
├── static/          # CSS, JS, images
├── templates/       # HTML templates
├── scripts/         # Utility scripts
├── app.py           # Application entry point
├── requirements.txt
└── Procfile         # Render deployment config
```

---

## Setup

```bash
# Clone the repo
git clone https://github.com/drenbuqa/BarnatoreMeldPharm.git
cd BarnatoreMeldPharm

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Fill in your MongoDB URI, Google OAuth credentials, and email config

# Run locally
python app.py
```

---

## Deployment

The application is deployed on Render using the included Procfile. Environment variables are configured through the Render dashboard.

---

## Status

Live and actively receiving customer orders.
