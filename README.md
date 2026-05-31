# 🌍 AQ Monitor – Smart Air Quality Monitoring System

## 📖 Project Overview

AQ Monitor is a real-time Air Quality Monitoring System built using Flask, IoT sensors, and a responsive web dashboard. The system continuously monitors environmental conditions such as gas concentration, temperature, and humidity, providing live analytics, intelligent alerts, and SMS notifications for unsafe air conditions.

The project is designed to help users detect poor air quality and harmful gas levels in real time through a professional industrial-style monitoring platform.

---

## ✨ Features

### 📊 Real-Time Dashboard

* Live gas sensor readings
* Temperature monitoring
* Humidity monitoring
* Air quality status indicator
* Responsive industrial-style UI

### 📈 Analytics Dashboard

* Live trend visualization
* Air quality analytics
* Historical data insights
* AI-powered recommendations

### 🚨 Alert Management

* Real-time alert generation
* Critical pollution warnings
* Alert history tracking
* Safety recommendations

### 📱 Mobile PWA Support

* Installable on Android and iPhone
* Responsive mobile interface
* Home screen support
* Offline asset caching

### 📨 SMS Notifications

* Twilio SMS integration
* Real-time critical air quality alerts
* Cooldown protection to prevent spam

### 🔊 Voice Alerts

* Audible warning notifications
* Triggered during poor air quality events

---

## 🛠 Hardware Used

| Component          | Purpose                  |
| ------------------ | ------------------------ |
| MQ-2 Gas Sensor    | Smoke and gas detection  |
| DHT11/DHT22 Sensor | Temperature and humidity |
| ESP32 / Arduino    | Sensor controller        |
| USB Connection     | Data communication       |

---

## 💻 Software Stack

### Backend

* Python
* Flask
* Twilio API
* Python Dotenv

### Frontend

* HTML5
* CSS3
* JavaScript

### Mobile

* Progressive Web App (PWA)
* Service Workers
* Web Manifest

### Development Tools

* VS Code
* Git
* GitHub

---

## 📂 Project Structure

```text
AirQualityDashboard/
│
├── app.py
├── requirements.txt
├── sms_twilio.py
├── settings_store.py
│
├── static/
│   ├── css/
│   ├── js/
│   ├── icons/
│   └── manifest.webmanifest
│
├── templates/
│   ├── dashboard.html
│   ├── analytics.html
│   ├── alerts.html
│   ├── settings.html
│   └── welcome.html
│
└── .env.example
```

## 🚀 Installation Guide

### 1. Clone Repository

```bash
git clone https://github.com/123Siv123/AirQualityDashboard.git
cd AirQualityDashboard
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file using `.env.example`.

```env
TWILIO_ENABLED=1
TWILIO_ACCOUNT_SID=YOUR_SID
TWILIO_AUTH_TOKEN=YOUR_TOKEN
TWILIO_FROM_NUMBER=YOUR_TWILIO_NUMBER
TWILIO_TO_NUMBER=YOUR_PHONE
```

### 4. Run Application

```bash
python app.py
```

### 5. Open Dashboard

```text
http://127.0.0.1:5000/dashboard
```

---

## 📱 Mobile Access

Ensure the phone and laptop are connected to the same Wi-Fi network.

Find your computer IP address:

```bash
ipconfig
```

Example:

```text
http://10.79.127.179:5000/dashboard
```

You can install the application to your phone using:

* Chrome → Install App
* Safari → Add to Home Screen

---

## 📸 Screenshots

Add screenshots here:

### Dashboard

![Dashboard](screenshots/dashboard.png)

### Analytics

![Analytics](screenshots/analytics.png)

### Alerts

![Alerts](screenshots/alerts.png)

### Mobile View

![Mobile](screenshots/mobile.png)

---

## 📨 Twilio SMS Alerts

When poor air quality is detected:

* SMS notification is sent automatically
* Cooldown protection prevents repeated alerts
* Real-time monitoring ensures immediate response

Example Alert:

```text
⚠ Poor Air Quality Detected!
Gas Value: 320
```

---

## 🎯 Future Enhancements

* Cloud database integration
* Push notifications
* AI-based pollution prediction
* GPS-based air quality mapping
* Multi-sensor support
* Historical report export

---

## 👨‍💻 Developer

GitHub: https://github.com/123Siv123

---

## 📄 License

This project is developed for academic and educational purposes.
