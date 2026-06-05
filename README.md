# Thunder FC - Football Performance Analytics Platform

## Overview

Thunder FC is a full-stack football performance analytics web application built using Flask, SQLite, and Machine Learning.

The platform enables administrators, coaches, and players to track performance, visualize statistics, generate insights, and predict future performance using time-series forecasting models.

The project demonstrates full-stack web development, database management, data visualization, authentication systems, and machine learning integration within a sports analytics environment.

---

## Features

### Authentication & Role-Based Access

* Secure login system
* Admin dashboard
* Coach dashboard
* Player dashboard
* Session management and password hashing

### Performance Tracking

* Match-by-match player statistics
* Performance scoring system
* Historical performance records
* Position-specific evaluation metrics

### Machine Learning Forecasting

* Time-series forecasting models
* Position-specific Random Forest models
* Predicts next-match player ratings
* Confidence score generation
* Form trajectory analysis

### Analytics & Insights

* Performance trends
* Rolling average analysis
* Weakness detection
* Coaching recommendations
* Forecast confidence metrics

### Data Visualization

* Interactive charts using Chart.js
* Performance history graphs
* Trend indicators
* Dashboard analytics panels

---

## Tech Stack

| Category         | Technology               |
| ---------------- | ------------------------ |
| Backend          | Python, Flask            |
| Database         | SQLite                   |
| Machine Learning | Scikit-learn             |
| Frontend         | HTML, CSS, Jinja2        |
| Charts           | Chart.js                 |
| Authentication   | Flask Sessions, Werkzeug |
| Version Control  | Git, GitHub              |

---

## Project Structure

```text
thunder-fc-football-analytics/
│
├── app.py
├── auth.py
├── config.py
├── db.py
├── logger.py
├── ml.py
├── services.py
├── seed_data.py
├── requirements.txt
│
├── templates/
│   ├── login.html
│   ├── player_dashboard.html
│   ├── coach_dashboard.html
│   ├── admin_dashboard.html
│   └── ...
│
├── static/
│   ├── css/
│   └── js/
│
└── models/
```

---

## Machine Learning Approach

The system uses a time-series forecasting approach instead of traditional classification.

### Input

Rolling averages from the previous three matches:

* Goals
* Assists
* Pass Accuracy
* Tackles
* Overall Score
* Form Trend
* Momentum

### Output

Predicted next-match rating:

* Excellent
* Good
* Average
* Poor

### Model

* Random Forest Classifier
* Position-specific models
* Chronological train-test split
* Future prediction based on historical performance

---

## Installation

### Clone Repository

```bash
git clone https://github.com/Aficionado404/thunder-fc-football-analytics.git
cd thunder-fc-football-analytics
```

### Create Virtual Environment

```bash
python -m venv venv
```

### Activate Virtual Environment

Windows:

```bash
venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Setup Database

Generate sample data:

```bash
python seed_data.py
```

---

## Run Application

```bash
python app.py
```

Application will be available at:

```text
http://localhost:5000
```

---

## Demo Accounts

### Admin

```text
Username: admin
Password: admin123
```

### Coach

```text
Username: coach1
Password: coach123
```

### Players

```text
Username: player1
Password: pass001
```

```text
Username: player3
Password: pass003
```

```text
Username: player4
Password: pass004
```

---

## Future Improvements

* Player comparison system
* Team performance analytics
* Injury prediction module
* Live match integration
* Advanced machine learning models
* REST API support
* Mobile responsive dashboard
* Cloud deployment

---

## Educational Objectives

This project demonstrates:

* Full-Stack Web Development
* Database Design
* Machine Learning Integration
* Data Analytics
* Sports Analytics
* Software Engineering Principles
* Authentication & Authorization
* Data Visualization

---

## Author

Vignesh Venu

B.Tech Computer Science and Engineering (Data Science)

Mini Project - Thunder FC Football Performance Analytics Platform
