"""
logger.py — Thunder FC
Centralised logging configuration.
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(app):
    """Attach a rotating file handler + stream handler to the Flask app."""
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Rotating file — 5 MB max, keep 5 backups
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'thunderfc.log'),
        maxBytes=5 * 1024 * 1024,
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Stream (console)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)

    app.logger.addHandler(file_handler)
    app.logger.addHandler(stream_handler)
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)

    app.logger.info('Thunder FC logger initialised (env=%s)',
                    os.environ.get('FLASK_ENV', 'development'))