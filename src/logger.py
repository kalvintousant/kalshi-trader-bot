"""
Logging configuration for Kalshi Trading Bot
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


class ConsoleDashboardFilter(logging.Filter):
    """
    Filter that blocks noisy INFO messages from the console handler.
    WARNING+ always passes. INFO messages from noisy modules are blocked
    unless they match an explicit allow-list of important patterns.
    """

    # Modules whose INFO messages are blocked by default
    BLOCKED_MODULES = {'src.strategies', 'src.weather_data', 'src.bot', 'src.outcome_tracker', '__main__'}

    # Substrings that let an INFO message through even from blocked modules
    ALLOW_PATTERNS = [
        # Trade executions
        'LONGSHOT YES', 'LONGSHOT NO',
        'Conservative YES', 'Conservative NO',
        'Asymmetric play',
        # Fill notifications
        'Notification sent:',
        # Order cancellations
        'Canceling order',
        'canceled successfully',
        # Settlement / outcome results
        'Logged outcome',
        'Performance Update',
        # Loss limit
        'Daily loss limit',
        'loss limit reached',
        # New market detection
        'NEW markets!',
        # Startup messages
        'Starting Kalshi Trading Bot',
        'Enabled strategies:',
        'Portfolio balance:',
        'Running in polling mode',
        'Scan interval:',
        'Weather sources enabled',
        'Adaptive city management',
        'Shutting down',
        'Bot stopped',
        'Daily stats reset',
        # Taking profit
        'Taking profit on',
        # Trade execution confirmation
        'Trade executed successfully',
        # Error recovery
        'Continuing in',
        # Scan completion
        'Scan complete in',
    ]

    def filter(self, record):
        # WARNING+ always passes
        if record.levelno >= logging.WARNING:
            return True

        # DEBUG is already blocked by console handler level; but be safe
        if record.levelno < logging.INFO:
            return False

        # INFO from non-blocked modules passes
        if record.name not in self.BLOCKED_MODULES:
            return True

        # INFO from blocked modules: check allow-list
        msg = record.getMessage()
        for pattern in self.ALLOW_PATTERNS:
            if pattern in msg:
                return True

        # Block this INFO message on console (it still goes to file)
        return False


def setup_logging(log_level: str = None, log_file: str = None):
    """
    Set up logging configuration for the bot

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (optional)
    """
    if log_level is None:
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    if log_file is None:
        log_file = os.getenv('LOG_FILE', 'bot.log')
    # Disable file logging if LOG_FILE is empty, "0", "false", or "none"
    if isinstance(log_file, str) and log_file.strip().lower() in ('', '0', 'false', 'none'):
        log_file = None

    # Create logs directory if it doesn't exist (only when file logging is enabled)
    if log_file:
        log_dir = os.path.dirname(log_file) if os.path.dirname(log_file) else '.'
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Check if dashboard is enabled (default: true)
    dashboard_enabled = os.getenv('DASHBOARD_ENABLED', 'true').lower() != 'false'

    # Console handler with colored output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)

    # Attach dashboard filter to console handler (blocks noisy INFO messages)
    if dashboard_enabled:
        console_handler.addFilter(ConsoleDashboardFilter())

    root_logger.addHandler(console_handler)

    # File handler with rotation (only if log_file is set)
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        root_logger.addHandler(file_handler)

    return root_logger

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
