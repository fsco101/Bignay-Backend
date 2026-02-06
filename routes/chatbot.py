"""
Chatbot Routes
AI-powered assistant for Bignay-related queries with content filtering
"""

from __future__ import annotations
import re
import os
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from typing import Optional
import json

try:
    import google.generativeai as genai
except ImportError:  # Gemini is optional in some environments
    genai = None

chatbot_bp = Blueprint('chatbot', __name__, url_prefix='/api/chatbot')

# Content filter for sensitive topics
SENSITIVE_TOPICS = [
    # Violence and harmful content
    r'\b(kill|murder|attack|weapon|gun|bomb|terrorism|suicide|self-harm)\b',
    # Explicit content
    r'\b(porn|xxx|nude|naked|explicit|sexual)\b',
    # Illegal activities
    r'\b(drug|cocaine|heroin|meth|illegal|hack|crack|pirate)\b',
    # Personal information extraction
    r'\b(password|credit card|social security|bank account|ssn)\b',
    # Hate speech indicators
    r'\b(hate|racist|sexist|discriminat)\b',
    # Political/religious extremism
    r'\b(extremist|radical|fanatical)\b',
]

# System context for the chatbot
SYSTEM_CONTEXT = """You are a helpful Bignay assistant for a mobile application. Your role is to:
1. Answer questions about Bignay (Antidesma bunius) fruit - identification, growing, harvesting, processing
2. Help users understand the app's features: Scanner, Marketplace, Price Prediction, Forum
3. Provide guidance on fruit classification results
4. Share recipes and health benefits of Bignay
5. Assist with marketplace purchases and orders

You should ONLY answer questions related to:
- Bignay fruit and plants
- The Bignay app features and functionality
- Agriculture, farming, and fruit cultivation
- Recipes and food preparation with Bignay
- Health and nutrition related to Bignay

For any other topics, politely redirect the conversation back to Bignay-related subjects.
Always be helpful, friendly, and encouraging to farmers and Bignay enthusiasts."""

GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
_gemini_model = None

# Enhanced knowledge base with comprehensive Bignay information
KNOWLEDGE_BASE = {
    'identification': {
        'keywords': ['identify', 'recognize', 'look', 'appearance', 'color', 'shape', 'what does', 'how does'],
        'response': '''🍇 **Bignay Identification Guide:**

**The Fruit:**
• **Size:** Small berries, 6-8mm diameter
• **Shape:** Round to slightly oval
• **Color progression:** Green → White → Pink → Red → Dark Purple/Black
• **Clusters:** Grows in hanging clusters like grapes
• **Taste:** Sweet-tart when ripe, similar to cranberries

**The Tree:**
• **Height:** 5-15 meters tall
• **Leaves:** Alternately arranged, 10-20cm long, glossy green
• **Bark:** Gray-brown, slightly rough

**Tip:** Use our Scanner feature to instantly identify ripeness stages!'''
    },
    'ripeness': {
        'keywords': ['ripe', 'ripeness', 'ready', 'harvest time', 'when to pick', 'mature'],
        'response': '''🎯 **Bignay Ripeness Stages:**

1. **Unripe (Green):** Hard, very sour - NOT ready
2. **Turning (White/Pink):** Beginning to soften - Wait
3. **Ripe (Red):** Sweet-tart, good for fresh eating
4. **Fully Ripe (Dark Purple/Black):** Maximum sweetness, ideal for wine/jam

**Best Harvesting Practice:**
• Harvest when 70-80% of cluster is dark purple
• Morning harvest reduces bruising
• Handle gently - berries are delicate
• Process within 24-48 hours of harvest

**Use our Scanner** to check ripeness with AI-powered detection!'''
    },
    'growing': {
        'keywords': ['grow', 'plant', 'cultivation', 'care', 'soil', 'water', 'fertilizer', 'farm', 'garden'],
        'response': '''🌱 **Bignay Growing Guide:**

**Climate:** Tropical to subtropical (thrives in Philippines)

**Soil Requirements:**
• Well-draining loamy soil
• pH 5.5-6.5 (slightly acidic)
• Rich in organic matter

**Planting:**
• Spacing: 6-8 meters apart
• Can grow from seeds or cuttings
• Best planted at start of rainy season

**Care Tips:**
• Regular watering (avoid waterlogging)
• Mulch around base to retain moisture
• Prune to maintain shape and airflow
• Apply organic compost 2-3 times yearly

**Harvest:** Trees bear fruit 3-5 years after planting'''
    },
    'wine': {
        'keywords': ['wine', 'ferment', 'alcohol', 'brew', 'making wine', 'winemaking'],
        'response': '''🍷 **Bignay Wine Making Guide:**

**Ingredients:**
• 2kg ripe Bignay (dark purple)
• 1kg sugar
• Wine yeast or natural fermentation
• 4 liters water

**Process:**
1. **Preparation:** Wash berries, remove stems
2. **Crushing:** Mash thoroughly to release juice
3. **Primary Ferment:** Add sugar & yeast, ferment 7-14 days
4. **Strain:** Remove solids through cheesecloth
5. **Secondary Ferment:** Continue 2-4 weeks
6. **Aging:** Store in dark place 2-6 months
7. **Bottle:** Transfer to clean bottles

**Result:** Beautiful ruby-red wine with unique berry flavor!

⚠️ **Note:** Follow local regulations for home winemaking'''
    },
    'jam': {
        'keywords': ['jam', 'jelly', 'preserve', 'spread', 'cooking'],
        'response': '''🫙 **Bignay Jam Recipe:**

**Ingredients:**
• 1kg ripe Bignay berries
• 750g sugar
• 2 tbsp lemon juice
• 1 cup water

**Instructions:**
1. Wash and remove stems from berries
2. Boil berries in water until soft (10-15 min)
3. Mash or blend, then strain to remove seeds
4. Return pulp to pot, add sugar
5. Cook on medium heat, stirring constantly
6. Add lemon juice
7. Test: Drop on cold plate - should wrinkle when pushed
8. Pour into sterilized jars while hot
9. Seal and let cool

**Storage:** Up to 1 year unopened, 1 month after opening (refrigerated)'''
    },
    'health': {
        'keywords': ['health', 'benefit', 'nutrition', 'vitamin', 'medicinal', 'medicine', 'disease'],
        'response': '''💚 **Bignay Health Benefits:**

**Nutritional Content:**
• Rich in Vitamin C
• Antioxidants (anthocyanins)
• Dietary fiber
• Iron and phosphorus

**Traditional Uses:**
• **Digestive aid:** Helps with indigestion
• **Anti-inflammatory:** Traditional remedy
• **Blood sugar:** May help regulate glucose
• **Liver support:** Used in folk medicine
• **Skin health:** Antioxidant properties

**Leaves:** Dried leaves make herbal tea believed to:
• Aid in weight management
• Support kidney health
• Reduce cholesterol

⚠️ **Disclaimer:** Consult healthcare provider before using for medicinal purposes'''
    },
    'price': {
        'keywords': ['price', 'cost', 'market', 'sell', 'buy', 'worth', 'value', 'money'],
        'response': '''💰 **Bignay Market Information:**

**Fresh Fruit Prices (Philippines):**
• Peak season: ₱100-150/kg
• Off-season: ₱180-250/kg

**Processed Products:**
• Bignay Wine: ₱200-500/bottle
• Bignay Jam: ₱120-200/jar
• Dried Leaves: ₱80-150/pack
• Bignay Vinegar: ₱100-180/bottle

**Selling Tips:**
• List on our Marketplace for wider reach
• Quality photos increase sales
• Describe ripeness and freshness
• Offer bundle deals for better value

**Check our Price Prediction** feature for market trends!'''
    },
    'mold': {
        'keywords': ['mold', 'fungus', 'rot', 'spoil', 'disease', 'pest', 'problem'],
        'response': '''⚠️ **Bignay Mold & Disease Management:**

**Identifying Mold:**
• Fuzzy white/gray/black spots
• Soft, mushy texture
• Off-putting smell
• Discoloration beyond normal ripeness

**Prevention:**
• Proper spacing for airflow
• Avoid overhead watering
• Remove fallen fruit promptly
• Prune infected branches

**Treatment:**
• Remove affected fruit immediately
• Apply organic fungicide if needed
• Improve drainage around tree

**For Harvested Fruit:**
• Discard any moldy berries
• Don't process moldy fruit
• Store in cool, dry conditions
• Use within 2-3 days of harvesting

**Use our Scanner** to detect mold on your Bignay!'''
    },
    'scanner': {
        'keywords': ['scan', 'scanner', 'camera', 'detect', 'analyze', 'ai', 'classification', 'classify'],
        'response': '''📸 **Using the Bignay Scanner:**

**Features:**
• **Camera Mode:** Real-time scanning using your camera
• **Gallery Mode:** Upload existing photos
• **Fruit Detection:** Identifies ripeness stages
• **Leaf Analysis:** Checks for disease/mold
• **Confidence Score:** Shows detection accuracy

**How to Use:**
1. Open Scanner from the menu
2. Choose Camera or Gallery mode
3. Select "Fruit" or "Leaf" classification type
4. Capture or upload image
5. Tap "Analyze" for results

**Best Results Tips:**
• Good lighting (natural light preferred)
• Clear, focused image
• Center the subject in frame
• Avoid shadows and reflections

**Help Improve AI:** Confirm or correct results to train the model!'''
    },
    'marketplace': {
        'keywords': ['marketplace', 'shop', 'store', 'order', 'cart', 'checkout', 'payment', 'delivery'],
        'response': '''🛒 **Bignay Marketplace Guide:**

**For Buyers:**
• Browse products by category
• Add items to cart
• Secure checkout via PayMongo
• Track your orders in real-time
• Leave reviews for products

**For Sellers:**
• List your Bignay products
• Set competitive prices
• Manage inventory
• Track sales and earnings
• Respond to customer reviews

**Payment Methods:**
• GCash
• Credit/Debit Cards
• Online Banking

**Order Status:**
Pending → Confirmed → Shipped → Delivered

**Need help?** Contact sellers directly through the app!'''
    },
    'app': {
        'keywords': ['app', 'feature', 'how to', 'help', 'use', 'navigate', 'tutorial'],
        'response': '''📱 **Bignay App Features:**

**🏠 Forum/Home**
Latest news, tips, and community posts about Bignay

**📸 Scanner**
AI-powered fruit and leaf analysis

**🤖 AI Assistant**
Get instant answers (that's me!)

**🛒 Marketplace**
Buy and sell Bignay products

**🗺️ Harvest Map**
Find Bignay locations near you

**📈 Price Prediction**
Market trends and price forecasts

**📜 History**
Your past scans and activities

**⚙️ Settings**
Customize your experience

**Tips:**
• Use the sidebar menu to navigate
• Pull down to refresh content
• Tap items for more details

**Need specific help?** Just ask me!'''
    },
    'greeting': {
        'keywords': ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening', 'howdy'],
        'response': '''👋 Hello! I'm your Bignay AI assistant!

I'm here to help you with:
• 🍇 Bignay identification and ripeness
• 🌱 Growing and cultivation tips
• 🍷 Wine, jam, and recipe ideas
• 💰 Market prices and selling
• 📸 Using the Scanner feature
• 🛒 Marketplace navigation
• ⚕️ Health benefits

What would you like to know about Bignay today?'''
    },
    'thanks': {
        'keywords': ['thank', 'thanks', 'appreciate', 'helpful', 'great'],
        'response': '''😊 You're welcome! I'm glad I could help!

Feel free to ask me anything else about:
• Bignay fruit and cultivation
• Using the app features
• Recipes and processing
• Market information

Happy Bignay farming! 🍇'''
    }
}

def is_content_safe(message: str) -> tuple[bool, Optional[str]]:
    """Check if message contains sensitive content"""
    message_lower = message.lower()
    
    for pattern in SENSITIVE_TOPICS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return False, "I can only help with Bignay-related topics and app features. Let's keep our conversation focused on that! 🍇"
    
    return True, None

def find_best_response(message: str) -> str:
    """Find the best matching response from knowledge base"""
    message_lower = message.lower()
    
    best_match = None
    best_score = 0
    
    for topic, data in KNOWLEDGE_BASE.items():
        score = sum(1 for keyword in data['keywords'] if keyword in message_lower)
        if score > best_score:
            best_score = score
            best_match = topic
    
    if best_match and best_score > 0:
        return KNOWLEDGE_BASE[best_match]['response']
    
    # Default response for unrecognized queries
    return '''🤔 I'm not quite sure about that specific topic.

I can help you with:
• **Identification:** "How do I identify ripe Bignay?"
• **Growing:** "How to grow Bignay trees?"
• **Processing:** "How to make Bignay wine/jam?"
• **Market:** "What's the price of Bignay?"
• **Health:** "What are Bignay health benefits?"
• **App Help:** "How do I use the Scanner?"

Feel free to ask about any of these topics! 🍇'''


def _get_gemini_model():
    """Initialize Gemini model lazily when API key is present."""
    global _gemini_model

    if _gemini_model is not None:
        return _gemini_model

    if not GEMINI_API_KEY or genai is None:
        return None

    genai.configure(api_key=GEMINI_API_KEY)
    _gemini_model = genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=SYSTEM_CONTEXT,
    )
    return _gemini_model


def _build_prompt(message: str, context: Optional[list]) -> str:
    """Create a prompt from context history and the user message."""
    lines = [SYSTEM_CONTEXT, "", "Conversation:"]

    if context:
        for entry in context:
            if isinstance(entry, dict):
                role = entry.get('role', 'user').capitalize()
                content = entry.get('content', '').strip()
                if content:
                    lines.append(f"{role}: {content}")

    lines.append(f"User: {message}")
    lines.append("Assistant:")
    return "\n".join(lines)


def _generate_gemini_response(message: str, context: Optional[list]) -> Optional[str]:
    """Generate a response using Gemini when configured."""
    model = _get_gemini_model()
    if not model:
        return None

    prompt = _build_prompt(message, context)

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.6,
                'max_output_tokens': 600,
            },
        )
        text = getattr(response, 'text', None)
        if text:
            return text.strip()
    except Exception:
        return None

    return None

def generate_response(message: str, context: Optional[list] = None) -> dict:
    """Generate a response for the user message"""
    
    # Check for sensitive content
    is_safe, filtered_response = is_content_safe(message)
    if not is_safe:
        return {
            'response': filtered_response,
            'filtered': True,
            'topic': 'filtered'
        }
    
    # Use Gemini if available, otherwise fallback to knowledge base
    ai_response = _generate_gemini_response(message, context)
    response = ai_response or find_best_response(message)
    
    return {
        'response': response,
        'filtered': False,
        'topic': 'bignay'
    }


@chatbot_bp.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages and return AI-powered responses"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'ok': False, 'error': 'Message is required'}), 400
        
        # Optional: conversation context for future AI integration
        context = data.get('context', [])
        
        # Generate response
        result = generate_response(message, context)
        
        return jsonify({
            'ok': True,
            'response': result['response'],
            'filtered': result['filtered'],
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@chatbot_bp.route('/suggestions', methods=['GET'])
def get_suggestions():
    """Get suggested questions/topics"""
    suggestions = [
        {'id': 'q1', 'text': '🍇 How to identify ripe Bignay?', 'topic': 'ripeness'},
        {'id': 'q2', 'text': '🌱 Growing tips for beginners', 'topic': 'growing'},
        {'id': 'q3', 'text': '🍷 How to make Bignay wine?', 'topic': 'wine'},
        {'id': 'q4', 'text': '💰 Current market prices', 'topic': 'price'},
        {'id': 'q5', 'text': '📸 How to use the Scanner?', 'topic': 'scanner'},
        {'id': 'q6', 'text': '💚 Health benefits of Bignay', 'topic': 'health'},
    ]
    
    return jsonify({
        'ok': True,
        'suggestions': suggestions
    })
