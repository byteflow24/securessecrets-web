# 🔐 SecuresSecrets – Web Platform

SecuresSecrets is a full-stack web application that enables users to securely store, schedule, and conditionally share private content (messages and files) with others.

It is designed around the concept of **digital legacy and controlled information release**, allowing secrets to be delivered based on time or user inactivity.

---

## 🚀 Features

- 🔒 Secure storage of secrets (text + files)
- ⏳ Scheduled delivery (date & time based)
- 💤 Inactivity-based delivery (Last Login Check)
- 🌍 Public sharing (published secrets feed)
- 🔑 Token-based private access links
- 📩 Multi-channel delivery (Email & WhatsApp via Twilio)
- 📂 Encrypted file storage with secure access
- ⏱ Auto-delete after viewing (self-destruct logic)
- 🔐 JWT-based authentication system

---

## 🧱 Tech Stack

### Backend
- Python (Flask)
- Flask Blueprints (modular architecture)
- JWT Authentication (`flask-jwt-extended`)
- Celery (background jobs & scheduling)
- PostgreSQL (database)
- SQLAlchemy ORM

### Storage & Infrastructure
- Google Cloud Storage (encrypted file handling)
- Render (deployment: web + workers)
- NameSilo (domain + DNS)
- Titan Email (SMTP email service)

### Integrations
- Twilio API (WhatsApp messaging)
- PayPal API (subscriptions & payments)

### Frontend
- HTML, CSS, JavaScript
- Bootstrap 5
- Jinja2 templating

---

## 🧠 System Architecture

The application follows a modular Flask architecture:
app/
├── auth/ # Authentication (login, register, JWT)
├── main/ # Core routes (dashboard, secrets, sharing)
├── models/ # Database models (User, Secret, SharedSecret)
├── services/ # Business logic (sharing, scheduling)
├── tasks/ # Celery background jobs
├── templates/ # Jinja2 HTML templates
├── static/ # CSS, JS, assets

---

## 🔐 Core Logic

### 1. Secret Sharing
Secrets can be shared via:
- Email
- WhatsApp
- Public feed

Each share generates a **unique tokenized link**:
/only-for-you/<token>

---

### 2. Conditional Delivery

Two delivery modes:
- 📅 Scheduled → delivered at a specific date/time
- 💤 Inactivity → delivered if user is inactive for X days

Handled using **Celery workers**.

---

### 3. Secure File Handling

- Files are stored encrypted in Google Cloud Storage
- Access is handled through:
/downloads/<filename>

Supports:
- Token-based access
- Streaming previews (image, PDF, video)
- Secure decryption before delivery

---

### 4. Self-Destruct Mechanism

When a recipient opens a secret:
- Marked as `received`
- Expiration timer starts (e.g., 1 hour)
- Automatically deleted after expiration

---

## 📡 API Highlights

- `/api/verify-apple-subscription`
- `/api/verify-google-subscription`
- `/only-for-you/<token>`
- `/downloads/<filename>`

---

## 💳 Payments

- PayPal subscription integration
- Webhooks handled:
  - `BILLING.SUBSCRIPTION.CREATED`
  - `BILLING.SUBSCRIPTION.ACTIVATED`
  - `PAYMENT.SALE.COMPLETED`

---

## ⚙️ Deployment

- Hosted on Render (Web Service + Workers)
- PostgreSQL hosted on Render
- Environment variables for secrets and APIs
- Production-ready configuration

---

## 📌 Key Challenges Solved

- Secure file encryption & streaming
- Handling temporary storage limits (`/tmp` issues)
- WhatsApp media delivery constraints (Twilio templates)
- Deep link integration across platforms
- Strict CSP & security headers

---

## 📷 Screens & UI

- Dashboard (private + public secrets)
- Secret creation interface
- Secure preview & download UI
- Token-based access page

---

## Final Note

This project represents a complete real-world system, covering:
- Backend architecture
- Secure data handling
- Payment systems
- Mobile integration
- Production deployment

---

## 👨‍💻 Developer

**M. Taha Srarfi**  
Full-Stack Developer (Web + Mobile)  

- Built the entire platform independently
- Designed backend architecture, APIs, and integrations
- Developed frontend UI and user flows
- Managed deployment, infrastructure, and scaling

---

> Built with purpose — securing what matters, when it matters.
