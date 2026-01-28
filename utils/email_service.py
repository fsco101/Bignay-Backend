"""
Email Service
Handles sending order receipts via SMTP with PDF attachments
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from io import BytesIO
from typing import Optional, Dict, Any, List

# Try to import reportlab for PDF generation
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("[EmailService] reportlab not installed - PDF generation disabled")


class EmailService:
    """Service for sending emails with SMTP"""
    
    def __init__(self):
        """Initialize email service with environment configuration"""
        self.smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.environ.get('SMTP_PORT', 587))
        self.smtp_user = os.environ.get('SMTP_USER', '')
        self.smtp_password = os.environ.get('SMTP_PASSWORD', '')
        self.from_email = os.environ.get('SMTP_FROM_EMAIL', self.smtp_user)
        self.from_name = os.environ.get('SMTP_FROM_NAME', 'Bignay Marketplace')
        self.enabled = bool(self.smtp_user and self.smtp_password)
        
        if not self.enabled:
            print("[EmailService] SMTP credentials not configured - email disabled")
        else:
            print(f"[EmailService] Configured with {self.smtp_host}:{self.smtp_port}")
    
    def _get_smtp_connection(self):
        """Create and return SMTP connection"""
        try:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            return server
        except Exception as e:
            print(f"[EmailService] SMTP connection failed: {e}")
            return None
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Send an email
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content
            text_body: Plain text fallback (optional)
            attachments: List of dicts with 'filename', 'content' (bytes), 'content_type'
        
        Returns:
            bool: True if sent successfully
        """
        if not self.enabled:
            print(f"[EmailService] Email disabled - would send to {to_email}: {subject}")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            
            # Add text and HTML parts
            if text_body:
                msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
            
            # Add attachments
            if attachments:
                for attachment in attachments:
                    part = MIMEApplication(attachment['content'], Name=attachment['filename'])
                    part['Content-Disposition'] = f'attachment; filename="{attachment["filename"]}"'
                    msg.attach(part)
            
            # Send email
            server = self._get_smtp_connection()
            if server:
                server.sendmail(self.from_email, to_email, msg.as_string())
                server.quit()
                print(f"[EmailService] Email sent to {to_email}: {subject}")
                return True
            return False
            
        except Exception as e:
            print(f"[EmailService] Failed to send email: {e}")
            return False
    
    def generate_order_pdf(self, order: Dict[str, Any]) -> Optional[bytes]:
        """
        Generate PDF receipt for an order
        
        Args:
            order: Order dictionary with all details
        
        Returns:
            bytes: PDF content or None if generation fails
        """
        if not REPORTLAB_AVAILABLE:
            print("[EmailService] PDF generation unavailable - reportlab not installed")
            return None
        
        try:
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=50,
                leftMargin=50,
                topMargin=50,
                bottomMargin=50
            )
            
            styles = getSampleStyleSheet()
            
            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                alignment=TA_CENTER,
                spaceAfter=20,
                textColor=colors.HexColor('#2E7D32')
            )
            
            subtitle_style = ParagraphStyle(
                'Subtitle',
                parent=styles['Normal'],
                fontSize=12,
                alignment=TA_CENTER,
                textColor=colors.grey,
                spaceAfter=30
            )
            
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=14,
                textColor=colors.HexColor('#2E7D32'),
                spaceBefore=20,
                spaceAfter=10
            )
            
            normal_style = ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontSize=11,
                spaceAfter=5
            )
            
            elements = []
            
            # Header
            elements.append(Paragraph("🌿 Bignay Marketplace", title_style))
            elements.append(Paragraph("Order Receipt", subtitle_style))
            
            # Order Info
            order_number = order.get('order_number', order.get('_id', 'N/A'))
            order_date = order.get('created_at', datetime.now())
            if isinstance(order_date, str):
                try:
                    order_date = datetime.fromisoformat(order_date.replace('Z', '+00:00'))
                except:
                    order_date = datetime.now()
            
            elements.append(Paragraph("Order Information", heading_style))
            elements.append(Paragraph(f"<b>Order Number:</b> #{order_number}", normal_style))
            elements.append(Paragraph(f"<b>Date:</b> {order_date.strftime('%B %d, %Y at %I:%M %p')}", normal_style))
            elements.append(Paragraph(f"<b>Status:</b> {order.get('status', 'N/A').upper()}", normal_style))
            
            elements.append(Spacer(1, 10))
            
            # Customer Info
            elements.append(Paragraph("Customer Details", heading_style))
            elements.append(Paragraph(f"<b>Name:</b> {order.get('user_name', 'N/A')}", normal_style))
            elements.append(Paragraph(f"<b>Email:</b> {order.get('user_email', 'N/A')}", normal_style))
            elements.append(Paragraph(f"<b>Phone:</b> {order.get('shipping_phone', 'N/A')}", normal_style))
            elements.append(Paragraph(f"<b>Address:</b> {order.get('shipping_address', 'N/A')}", normal_style))
            elements.append(Paragraph(f"<b>City:</b> {order.get('shipping_city', 'N/A')}", normal_style))
            
            elements.append(Spacer(1, 20))
            
            # Order Items Table
            elements.append(Paragraph("Order Items", heading_style))
            
            items = order.get('items', [])
            table_data = [['Product', 'Qty', 'Unit Price', 'Subtotal']]
            
            for item in items:
                table_data.append([
                    item.get('product_name', 'Unknown'),
                    str(item.get('quantity', 0)),
                    f"₱{item.get('unit_price', 0):.2f}",
                    f"₱{item.get('subtotal', 0):.2f}"
                ])
            
            # Add total row
            total = order.get('total_amount', 0)
            table_data.append(['', '', 'Total:', f"₱{total:.2f}"])
            
            table = Table(table_data, colWidths=[250, 50, 80, 80])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E7D32')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 1), (0, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E8F5E9')),
                ('FONTNAME', (2, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#E0E0E0')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F5F5F5')]),
            ]))
            elements.append(table)
            
            elements.append(Spacer(1, 30))
            
            # Notes if any
            notes = order.get('notes')
            if notes:
                elements.append(Paragraph("Notes", heading_style))
                elements.append(Paragraph(notes, normal_style))
                elements.append(Spacer(1, 20))
            
            # Footer
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontSize=10,
                alignment=TA_CENTER,
                textColor=colors.grey,
                spaceBefore=30
            )
            elements.append(Paragraph("Thank you for shopping with Bignay Marketplace!", footer_style))
            elements.append(Paragraph("For inquiries, please contact us at support@bignay.com", footer_style))
            
            doc.build(elements)
            pdf_content = buffer.getvalue()
            buffer.close()
            
            return pdf_content
            
        except Exception as e:
            print(f"[EmailService] PDF generation failed: {e}")
            return None
    
    def send_order_receipt(self, order: Dict[str, Any], status_changed: bool = False) -> bool:
        """
        Send order receipt email with PDF attachment
        
        Args:
            order: Order dictionary
            status_changed: Whether this is a status change notification
        
        Returns:
            bool: True if email sent successfully
        """
        user_email = order.get('user_email')
        if not user_email:
            print("[EmailService] No user email found in order")
            return False
        
        order_number = order.get('order_number', order.get('_id', 'N/A'))
        status = order.get('status', 'unknown').upper()
        user_name = order.get('user_name', 'Valued Customer')
        total = order.get('total_amount', 0)
        
        # Email subject
        if status_changed:
            subject = f"Order #{order_number} - Status Update: {status}"
        else:
            subject = f"Order #{order_number} - Confirmation"
        
        # Status-specific message and color
        status_messages = {
            'PENDING': ('Your order has been received and is awaiting confirmation.', '#FFA000'),
            'PROCESSING': ('Great news! Your order is now being prepared.', '#2196F3'),
            'SHIPPED': ('Your order is on its way! 🚚', '#9C27B0'),
            'DELIVERED': ('Your order has been delivered! Thank you for shopping with us. 🎉', '#4CAF50'),
            'CANCELLED': ('Your order has been cancelled. If you have questions, please contact us.', '#D32F2F'),
        }
        
        status_msg, status_color = status_messages.get(status, ('Your order status has been updated.', '#757575'))
        
        # Generate HTML email
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5;">
            <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; background-color: #ffffff;">
                <!-- Header -->
                <tr>
                    <td style="background: linear-gradient(135deg, #2E7D32 0%, #4CAF50 100%); padding: 30px; text-align: center;">
                        <h1 style="color: #ffffff; margin: 0; font-size: 28px;">🌿 Bignay Marketplace</h1>
                    </td>
                </tr>
                
                <!-- Status Banner -->
                <tr>
                    <td style="background-color: {status_color}; padding: 20px; text-align: center;">
                        <h2 style="color: #ffffff; margin: 0; font-size: 20px;">Order {status}</h2>
                    </td>
                </tr>
                
                <!-- Content -->
                <tr>
                    <td style="padding: 30px;">
                        <p style="font-size: 16px; color: #212121; margin-bottom: 20px;">
                            Hi <strong>{user_name}</strong>,
                        </p>
                        
                        <p style="font-size: 15px; color: #424242; line-height: 1.6;">
                            {status_msg}
                        </p>
                        
                        <!-- Order Summary Box -->
                        <div style="background-color: #f5f5f5; border-radius: 12px; padding: 20px; margin: 25px 0;">
                            <h3 style="margin: 0 0 15px 0; color: #2E7D32; font-size: 16px;">Order Summary</h3>
                            <table width="100%" style="font-size: 14px;">
                                <tr>
                                    <td style="padding: 8px 0; color: #757575;">Order Number:</td>
                                    <td style="padding: 8px 0; color: #212121; text-align: right; font-weight: bold;">#{order_number}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; color: #757575;">Status:</td>
                                    <td style="padding: 8px 0; text-align: right;">
                                        <span style="background-color: {status_color}; color: #fff; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: bold;">{status}</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; color: #757575;">Total Amount:</td>
                                    <td style="padding: 8px 0; color: #2E7D32; text-align: right; font-weight: bold; font-size: 18px;">₱{total:.2f}</td>
                                </tr>
                            </table>
                        </div>
                        
                        <!-- Items -->
                        <h3 style="color: #2E7D32; font-size: 16px; margin-bottom: 15px;">Items Ordered</h3>
                        <table width="100%" style="font-size: 14px; border-collapse: collapse;">
                            <tr style="background-color: #2E7D32; color: #fff;">
                                <th style="padding: 12px; text-align: left; border-radius: 8px 0 0 0;">Product</th>
                                <th style="padding: 12px; text-align: center;">Qty</th>
                                <th style="padding: 12px; text-align: right; border-radius: 0 8px 0 0;">Subtotal</th>
                            </tr>
        """
        
        # Add items
        for item in order.get('items', []):
            html_body += f"""
                            <tr style="border-bottom: 1px solid #e0e0e0;">
                                <td style="padding: 12px; color: #212121;">{item.get('product_name', 'Unknown')}</td>
                                <td style="padding: 12px; text-align: center; color: #757575;">{item.get('quantity', 0)}</td>
                                <td style="padding: 12px; text-align: right; color: #2E7D32; font-weight: bold;">₱{item.get('subtotal', 0):.2f}</td>
                            </tr>
            """
        
        html_body += f"""
                        </table>
                        
                        <!-- Shipping Info -->
                        <div style="margin-top: 25px; padding: 20px; background-color: #E8F5E9; border-radius: 12px;">
                            <h3 style="margin: 0 0 10px 0; color: #2E7D32; font-size: 14px;">📍 Delivery Address</h3>
                            <p style="margin: 0; color: #424242; line-height: 1.5;">
                                {order.get('shipping_address', 'N/A')}<br>
                                {order.get('shipping_city', '')}<br>
                                Phone: {order.get('shipping_phone', 'N/A')}
                            </p>
                        </div>
                        
                        <p style="font-size: 14px; color: #757575; margin-top: 25px; text-align: center;">
                            A PDF receipt is attached to this email for your records.
                        </p>
                    </td>
                </tr>
                
                <!-- Footer -->
                <tr>
                    <td style="background-color: #f5f5f5; padding: 25px; text-align: center; border-top: 1px solid #e0e0e0;">
                        <p style="margin: 0; font-size: 14px; color: #757575;">
                            Thank you for shopping with <strong style="color: #2E7D32;">Bignay Marketplace</strong>!
                        </p>
                        <p style="margin: 10px 0 0 0; font-size: 12px; color: #9e9e9e;">
                            © 2025 Bignay Project. All rights reserved.
                        </p>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        
        # Plain text fallback
        text_body = f"""
        Bignay Marketplace - Order {status}
        
        Hi {user_name},
        
        {status_msg}
        
        Order Number: #{order_number}
        Total: ₱{total:.2f}
        Status: {status}
        
        Thank you for shopping with Bignay Marketplace!
        """
        
        # Generate PDF attachment
        attachments = []
        pdf_content = self.generate_order_pdf(order)
        if pdf_content:
            attachments.append({
                'filename': f'order_{order_number}_receipt.pdf',
                'content': pdf_content,
                'content_type': 'application/pdf'
            })
        
        return self.send_email(
            to_email=user_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            attachments=attachments if attachments else None
        )


# Singleton instance
_email_service = None

def get_email_service() -> EmailService:
    """Get or create email service singleton"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
