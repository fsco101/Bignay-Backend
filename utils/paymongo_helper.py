"""
PayMongo Helper
Handles PayMongo API integration for online payments
"""

import requests
import base64
from typing import Optional, Dict, Any
from config import get_settings


class PayMongoHelper:
    """Helper class for PayMongo API integration"""
    
    BASE_URL = "https://api.paymongo.com/v1"
    
    def __init__(self):
        self.settings = get_settings()
        self.secret_key = self.settings.paymongo_secret_key
        self.public_key = self.settings.paymongo_public_key
        
    def _get_auth_header(self) -> Dict[str, str]:
        """Get basic auth header for API requests"""
        if not self.secret_key:
            raise ValueError("PayMongo secret key not configured")
        
        # PayMongo uses basic auth with secret key as username
        credentials = base64.b64encode(f"{self.secret_key}:".encode()).decode()
        return {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def create_checkout_session(
        self,
        amount: float,
        description: str,
        order_id: str,
        customer_email: str,
        customer_name: str,
        success_url: str,
        cancel_url: str,
        line_items: list = None,
    ) -> Dict[str, Any]:
        """
        Create a PayMongo checkout session for payment
        
        Args:
            amount: Amount in PHP (will be converted to centavos)
            description: Payment description
            order_id: Order ID for reference
            customer_email: Customer's email
            customer_name: Customer's name
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment is cancelled
            line_items: Optional list of line items
            
        Returns:
            Dict with checkout session data or error
        """
        try:
            # Convert PHP to centavos (PayMongo requires centavos)
            amount_centavos = int(amount * 100)
            
            # Build line items if not provided
            if not line_items:
                line_items = [{
                    "currency": "PHP",
                    "amount": amount_centavos,
                    "name": description,
                    "quantity": 1,
                }]
            
            payload = {
                "data": {
                    "attributes": {
                        "billing": {
                            "email": customer_email,
                            "name": customer_name,
                        },
                        "send_email_receipt": True,
                        "show_description": True,
                        "show_line_items": True,
                        "description": f"Order #{order_id} - {description}",
                        "line_items": line_items,
                        "payment_method_types": [
                            "gcash",
                            "grab_pay",
                            "paymaya",
                            "card",
                        ],
                        "success_url": success_url,
                        "cancel_url": cancel_url,
                        "reference_number": order_id,
                    }
                }
            }
            
            response = requests.post(
                f"{self.BASE_URL}/checkout_sessions",
                json=payload,
                headers=self._get_auth_header(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "ok": True,
                    "checkout_session": data["data"],
                    "checkout_url": data["data"]["attributes"]["checkout_url"],
                    "checkout_id": data["data"]["id"],
                }
            else:
                error_data = response.json()
                return {
                    "ok": False,
                    "error": error_data.get("errors", [{"detail": "Unknown error"}])[0].get("detail", "Unknown error"),
                    "status_code": response.status_code,
                }
                
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Request timeout"}
        except requests.exceptions.RequestException as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def get_checkout_session(self, checkout_id: str) -> Dict[str, Any]:
        """
        Get checkout session details
        
        Args:
            checkout_id: PayMongo checkout session ID
            
        Returns:
            Dict with checkout session data or error
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/checkout_sessions/{checkout_id}",
                headers=self._get_auth_header(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "ok": True,
                    "checkout_session": data["data"],
                    "status": data["data"]["attributes"]["status"],
                    "payment_intent_id": data["data"]["attributes"].get("payment_intent", {}).get("id"),
                }
            else:
                error_data = response.json()
                return {
                    "ok": False,
                    "error": error_data.get("errors", [{"detail": "Unknown error"}])[0].get("detail", "Unknown error"),
                }
                
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def create_payment_intent(
        self,
        amount: float,
        description: str,
        statement_descriptor: str = "BIGNAY",
    ) -> Dict[str, Any]:
        """
        Create a PayMongo payment intent
        
        Args:
            amount: Amount in PHP
            description: Payment description
            statement_descriptor: Descriptor shown on bank statement
            
        Returns:
            Dict with payment intent data or error
        """
        try:
            amount_centavos = int(amount * 100)
            
            payload = {
                "data": {
                    "attributes": {
                        "amount": amount_centavos,
                        "payment_method_allowed": [
                            "gcash",
                            "grab_pay",
                            "paymaya",
                            "card",
                        ],
                        "payment_method_options": {
                            "card": {
                                "request_three_d_secure": "any"
                            }
                        },
                        "currency": "PHP",
                        "description": description,
                        "statement_descriptor": statement_descriptor,
                    }
                }
            }
            
            response = requests.post(
                f"{self.BASE_URL}/payment_intents",
                json=payload,
                headers=self._get_auth_header(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "ok": True,
                    "payment_intent": data["data"],
                    "payment_intent_id": data["data"]["id"],
                    "client_key": data["data"]["attributes"]["client_key"],
                }
            else:
                error_data = response.json()
                return {
                    "ok": False,
                    "error": error_data.get("errors", [{"detail": "Unknown error"}])[0].get("detail", "Unknown error"),
                }
                
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def get_payment_intent(self, payment_intent_id: str) -> Dict[str, Any]:
        """
        Get payment intent details
        
        Args:
            payment_intent_id: PayMongo payment intent ID
            
        Returns:
            Dict with payment intent data or error
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/payment_intents/{payment_intent_id}",
                headers=self._get_auth_header(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "ok": True,
                    "payment_intent": data["data"],
                    "status": data["data"]["attributes"]["status"],
                    "amount": data["data"]["attributes"]["amount"] / 100,  # Convert centavos to PHP
                }
            else:
                error_data = response.json()
                return {
                    "ok": False,
                    "error": error_data.get("errors", [{"detail": "Unknown error"}])[0].get("detail", "Unknown error"),
                }
                
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def create_source(
        self,
        amount: float,
        source_type: str,  # gcash, grab_pay
        redirect_success: str,
        redirect_failed: str,
        billing_email: str = None,
        billing_name: str = None,
    ) -> Dict[str, Any]:
        """
        Create a payment source for e-wallets (GCash, GrabPay)
        
        Args:
            amount: Amount in PHP
            source_type: Payment source type (gcash, grab_pay)
            redirect_success: Success redirect URL
            redirect_failed: Failed redirect URL
            billing_email: Customer email
            billing_name: Customer name
            
        Returns:
            Dict with source data or error
        """
        try:
            amount_centavos = int(amount * 100)
            
            payload = {
                "data": {
                    "attributes": {
                        "amount": amount_centavos,
                        "redirect": {
                            "success": redirect_success,
                            "failed": redirect_failed,
                        },
                        "type": source_type,
                        "currency": "PHP",
                    }
                }
            }
            
            if billing_email or billing_name:
                payload["data"]["attributes"]["billing"] = {}
                if billing_email:
                    payload["data"]["attributes"]["billing"]["email"] = billing_email
                if billing_name:
                    payload["data"]["attributes"]["billing"]["name"] = billing_name
            
            response = requests.post(
                f"{self.BASE_URL}/sources",
                json=payload,
                headers=self._get_auth_header(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "ok": True,
                    "source": data["data"],
                    "source_id": data["data"]["id"],
                    "checkout_url": data["data"]["attributes"]["redirect"]["checkout_url"],
                }
            else:
                error_data = response.json()
                return {
                    "ok": False,
                    "error": error_data.get("errors", [{"detail": "Unknown error"}])[0].get("detail", "Unknown error"),
                }
                
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def get_source(self, source_id: str) -> Dict[str, Any]:
        """
        Get source details
        
        Args:
            source_id: PayMongo source ID
            
        Returns:
            Dict with source data or error
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/sources/{source_id}",
                headers=self._get_auth_header(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "ok": True,
                    "source": data["data"],
                    "status": data["data"]["attributes"]["status"],
                }
            else:
                error_data = response.json()
                return {
                    "ok": False,
                    "error": error_data.get("errors", [{"detail": "Unknown error"}])[0].get("detail", "Unknown error"),
                }
                
        except Exception as e:
            return {"ok": False, "error": str(e)}


# Singleton instance
paymongo_helper = PayMongoHelper()
