# Kotak Trading Terminal - Authentication Manager

import threading
from typing import Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import sys
import os

# Add parent directory to path for neo_api_client import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo_api_client import NeoAPI
from terminal.config import Config


@dataclass
class SessionState:
    """Represents the current authentication session state"""
    authenticated: bool = False
    login_time: Optional[datetime] = None
    user_id: Optional[str] = None
    error: Optional[str] = None


class AuthManager:
    """
    Manages authentication with Kotak Neo API.
    Handles TOTP login flow and session management.
    """
    
    _instance: Optional['AuthManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern for single-user app"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._client: Optional[NeoAPI] = None
        self._session_state = SessionState()
        self._on_message: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_open: Optional[Callable] = None
        self._on_close: Optional[Callable] = None
        self._initialized = True
    
    @property
    def client(self) -> Optional[NeoAPI]:
        """Get the NeoAPI client instance"""
        return self._client
    
    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        return self._session_state.authenticated
    
    @property
    def session_state(self) -> SessionState:
        """Get current session state"""
        return self._session_state
    
    def initialize_client(self) -> dict:
        """Initialize the NeoAPI client (step 1 of auth)"""
        try:
            self._client = NeoAPI(
                environment=Config.ENVIRONMENT,
                access_token=None,
                neo_fin_key=None,
                consumer_key=Config.CONSUMER_KEY
            )
            return {"success": True, "message": "Client initialized"}
        except Exception as e:
            self._session_state.error = str(e)
            return {"success": False, "error": str(e)}
    
    def login_with_totp(self, totp: str) -> dict:
        """
        Perform TOTP login (step 2 of auth).
        
        Args:
            totp: Time-based One-Time Password from authenticator app
            
        Returns:
            dict with success status and message
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized. Call initialize_client first."}
        
        try:
            result = self._client.totp_login(
                mobile_number=Config.MOBILE_NUMBER,
                ucc=Config.UCC,
                totp=totp
            )
            return {"success": True, "message": "TOTP login successful", "data": result}
        except Exception as e:
            self._session_state.error = str(e)
            return {"success": False, "error": str(e)}
    
    def validate_mpin(self, mpin: Optional[str] = None) -> dict:
        """
        Validate MPIN to complete authentication (step 3 of auth).
        
        Args:
            mpin: 6-digit MPIN (uses config if not provided)
            
        Returns:
            dict with success status and session info
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized"}
        
        try:
            mpin_to_use = mpin or Config.MPIN
            result = self._client.totp_validate(mpin=mpin_to_use)
            
            self._session_state = SessionState(
                authenticated=True,
                login_time=datetime.now(),
                user_id=Config.UCC
            )
            
            return {
                "success": True,
                "message": "Authentication complete",
                "data": result,
                "paper_mode": Config.PAPER_TRADING
            }
        except Exception as e:
            self._session_state.error = str(e)
            return {"success": False, "error": str(e)}
    
    def quick_login(self, totp: str) -> dict:
        """
        Perform complete login flow in one step.
        
        Args:
            totp: TOTP code from authenticator
            
        Returns:
            dict with success status
        """
        # Step 1: Initialize
        init_result = self.initialize_client()
        if not init_result.get("success"):
            return init_result
        
        # Step 2: TOTP Login
        totp_result = self.login_with_totp(totp)
        if not totp_result.get("success"):
            return totp_result
        
        # Step 3: Validate MPIN
        return self.validate_mpin()
    
    def logout(self) -> dict:
        """Logout and clear session"""
        try:
            if self._client and self._session_state.authenticated:
                self._client.logout()
            
            self._session_state = SessionState()
            self._client = None
            
            return {"success": True, "message": "Logged out successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def set_websocket_callbacks(
        self,
        on_message: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_open: Optional[Callable] = None,
        on_close: Optional[Callable] = None
    ):
        """Set WebSocket callback functions"""
        if self._client:
            if on_message:
                self._client.on_message = on_message
            if on_error:
                self._client.on_error = on_error
            if on_open:
                self._client.on_open = on_open
            if on_close:
                self._client.on_close = on_close
    
    def get_session_info(self) -> dict:
        """Get current session information"""
        return {
            "authenticated": self._session_state.authenticated,
            "login_time": self._session_state.login_time.isoformat() if self._session_state.login_time else None,
            "user_id": self._session_state.user_id,
            "paper_mode": Config.PAPER_TRADING,
            "error": self._session_state.error
        }
