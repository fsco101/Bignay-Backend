"""
PDF Generator Module
Generates PDF receipts for orders that can be downloaded or printed
"""

import os
from datetime import datetime
from io import BytesIO
from typing import Dict, Any, Optional
from pathlib import Path

# Try to import reportlab for PDF generation
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    REPORTLAB_AVAILABLE = True
    print("[PDFGenerator] ✓ reportlab available")
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("[PDFGenerator] ✗ reportlab not installed - run: pip install reportlab")


def generate_order_receipt_pdf(order: Dict[str, Any]) -> Optional[bytes]:
    """
    Generate a professional PDF receipt for an order
    
    Args:
        order: Order dictionary with all details
    
    Returns:
        bytes: PDF content or None if generation fails
    """
    if not REPORTLAB_AVAILABLE:
        print("[PDFGenerator] PDF generation unavailable - reportlab not installed")
        return None
    
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )
        
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=28,
            alignment=TA_CENTER,
            spaceAfter=10,
            textColor=colors.HexColor('#2E7D32')
        )
        
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#757575'),
            spaceAfter=30
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2E7D32'),
            spaceBefore=20,
            spaceAfter=12,
            borderPadding=5
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=6,
            leading=14
        )
        
        bold_style = ParagraphStyle(
            'BoldNormal',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=6,
            leading=14,
            fontName='Helvetica-Bold'
        )
        
        elements = []
        
        # Header with logo/title
        elements.append(Paragraph("🌿 Bignay Marketplace", title_style))
        elements.append(Paragraph("Official Order Receipt", subtitle_style))
        
        # Add a decorative line
        line_data = [['']]
        line_table = Table(line_data, colWidths=[500])
        line_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 2, colors.HexColor('#2E7D32')),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 20))
        
        # Order Information Section
        order_number = order.get('order_number', order.get('_id', 'N/A'))
        order_date = order.get('created_at', datetime.now())
        if isinstance(order_date, str):
            try:
                order_date = datetime.fromisoformat(order_date.replace('Z', '+00:00'))
            except:
                order_date = datetime.now()
        
        status = order.get('status', 'N/A').upper()
        status_colors = {
            'PENDING': '#FFA000',
            'PROCESSING': '#2196F3',
            'SHIPPED': '#9C27B0',
            'DELIVERED': '#4CAF50',
            'CANCELLED': '#D32F2F'
        }
        status_color = status_colors.get(status, '#757575')
        
        elements.append(Paragraph("📋 Order Information", heading_style))
        
        # Order info table
        order_info_data = [
            ['Order Number:', f"#{order_number}"],
            ['Date:', order_date.strftime('%B %d, %Y at %I:%M %p')],
            ['Status:', status],
            ['Payment Method:', order.get('payment_method', 'Cash on Delivery').replace('_', ' ').title()],
            ['Payment Status:', order.get('payment_status', 'Pending').title()],
        ]
        
        order_info_table = Table(order_info_data, colWidths=[150, 350])
        order_info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#424242')),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#212121')),
            ('TEXTCOLOR', (1, 2), (1, 2), colors.HexColor(status_color)),
            ('FONTNAME', (1, 2), (1, 2), 'Helvetica-Bold'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(order_info_table)
        
        elements.append(Spacer(1, 10))
        
        # Customer Information Section
        elements.append(Paragraph("👤 Customer Information", heading_style))
        
        customer_info_data = [
            ['Name:', order.get('user_name', 'N/A')],
            ['Email:', order.get('user_email', 'N/A')],
            ['Phone:', order.get('shipping_phone', 'N/A')],
        ]
        
        customer_table = Table(customer_info_data, colWidths=[150, 350])
        customer_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#424242')),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#212121')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(customer_table)
        
        elements.append(Spacer(1, 10))
        
        # Shipping Address Section
        elements.append(Paragraph("📍 Delivery Address", heading_style))
        
        address_parts = [
            order.get('shipping_address', ''),
            order.get('shipping_city', ''),
            order.get('shipping_province', ''),
            order.get('shipping_postal_code', '')
        ]
        full_address = ', '.join([p for p in address_parts if p])
        
        elements.append(Paragraph(full_address or 'N/A', normal_style))
        
        elements.append(Spacer(1, 15))
        
        # Order Items Section
        elements.append(Paragraph("🛒 Order Items", heading_style))
        
        items = order.get('items', [])
        table_data = [['#', 'Product', 'Seller', 'Qty', 'Unit Price', 'Subtotal']]
        
        for i, item in enumerate(items, 1):
            table_data.append([
                str(i),
                item.get('product_name', 'Unknown')[:30],
                item.get('seller_name', 'N/A')[:15],
                str(item.get('quantity', 0)),
                f"₱{item.get('unit_price', 0):,.2f}",
                f"₱{item.get('subtotal', 0):,.2f}"
            ])
        
        items_table = Table(table_data, colWidths=[30, 160, 90, 40, 80, 80])
        items_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E7D32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            
            # Data rows
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (3, 1), (3, -1), 'CENTER'),
            ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 10),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
        ]))
        elements.append(items_table)
        
        elements.append(Spacer(1, 15))
        
        # Total Section
        total = order.get('total_amount', 0)
        
        total_data = [
            ['Subtotal:', f"₱{total:,.2f}"],
            ['Shipping:', 'FREE'],
            ['Total Amount:', f"₱{total:,.2f}"],
        ]
        
        total_table = Table(total_data, colWidths=[400, 100])
        total_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -2), 11),
            ('FONTSIZE', (0, -1), (-1, -1), 14),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#2E7D32')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#2E7D32')),
        ]))
        elements.append(total_table)
        
        # Notes if any
        notes = order.get('notes')
        if notes:
            elements.append(Spacer(1, 15))
            elements.append(Paragraph("📝 Notes", heading_style))
            elements.append(Paragraph(notes, normal_style))
        
        elements.append(Spacer(1, 30))
        
        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#9E9E9E'),
            spaceBefore=20
        )
        
        # Add decorative line before footer
        elements.append(line_table)
        elements.append(Spacer(1, 15))
        
        elements.append(Paragraph("Thank you for shopping with Bignay Marketplace! 🌿", footer_style))
        elements.append(Paragraph(f"Receipt generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", footer_style))
        elements.append(Paragraph("For inquiries, contact: support@bignay.com", footer_style))
        
        doc.build(elements)
        pdf_content = buffer.getvalue()
        buffer.close()
        
        print(f"[PDFGenerator] ✓ Generated PDF for order #{order_number}")
        return pdf_content
        
    except Exception as e:
        print(f"[PDFGenerator] ✗ PDF generation failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def is_pdf_generation_available() -> bool:
    """Check if PDF generation is available"""
    return REPORTLAB_AVAILABLE
