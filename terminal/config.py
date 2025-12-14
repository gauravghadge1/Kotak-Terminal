# Kotak Trading Terminal - Configuration

import os
from pathlib import Path

# ===== Environment Variables =====
# Set these in your .env file or system environment
# KOTAK_CONSUMER_KEY=your_consumer_key
# KOTAK_MOBILE_NUMBER=your_mobile_with_country_code
# KOTAK_UCC=your_ucc
# KOTAK_MPIN=your_mpin

class Config:
    """Configuration for Kotak Trading Terminal"""
    
    # API Settings
    ENVIRONMENT = os.getenv("KOTAK_ENVIRONMENT", "prod")
    CONSUMER_KEY = os.getenv("KOTAK_CONSUMER_KEY", "")
    MOBILE_NUMBER = os.getenv("KOTAK_MOBILE_NUMBER", "")
    UCC = os.getenv("KOTAK_UCC", "")
    MPIN = os.getenv("KOTAK_MPIN", "")
    
    # Trading Mode
    PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
    
    # Server Settings
    HOST = os.getenv("TERMINAL_HOST", "127.0.0.1")
    PORT = int(os.getenv("TERMINAL_PORT", "5000"))
    DEBUG = os.getenv("TERMINAL_DEBUG", "true").lower() == "true"
    SECRET_KEY = os.getenv("TERMINAL_SECRET_KEY", "kotak-terminal-dev-key-change-in-prod")
    
    # Risk Management (Paper Trading defaults)
    MAX_ORDER_VALUE = float(os.getenv("MAX_ORDER_VALUE", "100000"))  # Max single order value
    MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "10000"))     # Max daily loss limit
    MAX_POSITION_SIZE = int(os.getenv("MAX_POSITION_SIZE", "1000"))  # Max quantity per position
    
    # WebSocket Settings
    WS_RECONNECT_DELAY = 5  # seconds
    WS_PING_INTERVAL = 30   # seconds
    
    # Paths
    BASE_DIR = Path(__file__).parent
    STATIC_DIR = BASE_DIR / "static"
    TEMPLATES_DIR = BASE_DIR / "templates"
    
    @classmethod
    def validate(cls) -> dict:
        """Validate required configuration"""
        errors = []
        if not cls.CONSUMER_KEY:
            errors.append("KOTAK_CONSUMER_KEY is required")
        if not cls.MOBILE_NUMBER:
            errors.append("KOTAK_MOBILE_NUMBER is required")
        if not cls.UCC:
            errors.append("KOTAK_UCC is required")
        if not cls.MPIN:
            errors.append("KOTAK_MPIN is required")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "paper_mode": cls.PAPER_TRADING
        }
    
    @classmethod
    def get_status(cls) -> dict:
        """Get current configuration status"""
        return {
            "environment": cls.ENVIRONMENT,
            "paper_trading": cls.PAPER_TRADING,
            "host": cls.HOST,
            "port": cls.PORT,
            "credentials_set": bool(cls.CONSUMER_KEY and cls.MOBILE_NUMBER and cls.UCC),
            "max_order_value": cls.MAX_ORDER_VALUE,
            "max_daily_loss": cls.MAX_DAILY_LOSS
        }
