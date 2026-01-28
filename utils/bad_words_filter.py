"""
Bad Words Filter
Filters inappropriate language from user-generated content using regex
"""

import re
from typing import Tuple, List

# Comprehensive list of bad words and patterns (expandable)
# Using regex patterns for better matching including common substitutions
BAD_WORDS_PATTERNS = [
    # English profanity (with common letter substitutions)
    r'\b[fF][uU@][cCkK]+(?:ing|er|ed|s)?\b',
    r'\b[sS][hH][iI1!][tT]+(?:ty|ing|s)?\b',
    r'\b[aA@][sS$][sS$]+(?:hole|wipe)?\b',
    r'\b[bB][iI1!][tT][cC][hH]+(?:es|y|ing)?\b',
    r'\b[dD][aA@][mM][nN]+(?:ed|it)?\b',
    r'\b[hH][eE3][lL]+(?:\s)?[nN][oO0]\b',
    r'\b[cC][rR][aA@][pP]+(?:py|s)?\b',
    r'\b[bB][aA@][sS$][tT][aA@][rR][dD]+\b',
    r'\b[iI][dD][iI1!][oO0][tT]+(?:ic|s)?\b',
    r'\b[sS][tT][uU][pP][iI1!][dD]+\b',
    r'\b[dD][uU][mM][bB]+(?:ass)?\b',
    r'\b[mM][oO0][rR][oO0][nN]+(?:ic|s)?\b',
    r'\b[jJ][eE3][rR][kK]+(?:s)?\b',
    r'\b[lL][oO0][sS$][eE3][rR]+(?:s)?\b',
    r'\b[pP][rR][iI1!][cC][kK]+(?:s)?\b',
    r'\b[dD][iI1!][cC][kK]+(?:head|s)?\b',
    r'\b[cC][oO0][cC][kK]+(?:sucker|s)?\b',
    r'\b[pP][uU][sS$][sS$][yY]+\b',
    r'\b[wW][hH][oO0][rR][eE3]+(?:s)?\b',
    r'\b[sS][lL][uU][tT]+(?:ty|s)?\b',
    r'\b[nN][iI1!][gG]+(?:er|a)+(?:s)?\b',
    r'\b[fF][aA@][gG]+(?:got|s)?\b',
    r'\b[rR][eE3][tT][aA@][rR][dD]+(?:ed|s)?\b',
    r'\b[cC][uU][nN][tT]+(?:s)?\b',
    r'\b[tT][wW][aA@][tT]+(?:s)?\b',
    
    # Filipino/Tagalog profanity
    r'\b[pP][uU][tT][aA@]+(?:ng\s?ina)?\b',
    r'\b[gG][aA@][gG][oO0]+\b',
    r'\b[tT][aA@][nN][gG][aA@]+\b',
    r'\b[bB][oO0][bB][oO0]+\b',
    r'\b[tT][aA@][rR][aA@][nN][tT][aA@][dD][oO0]+\b',
    r'\b[lL][iI1!][nN][tT][iI1!][kK]+\b',
    r'\b[uU][lL][oO0][lL]+\b',
    r'\b[hH][iI1!][nN][dD][oO0][tT]+\b',
    r'\b[bB][uU][lL][oO0][kK]+\b',
    r'\b[pP][aA@][kK][yY][uU]+\b',
    r'\b[gG][iI1!][aA@][gG][oO0]+\b',
    r'\b[bB][wW][iI1!][sS$][iI1!][tT]+\b',
    r'\b[pP][uU][nN][yY][eE3][tT][aA@]+\b',
    r'\b[lL][eE3][cC][hH][eE3]+\b',
    r'\b[tT][iI1!][tT][iI1!]+\b',
    r'\b[kK][aA@][nN][tT][oO0][tT]+\b',
    
    # Insults and offensive terms
    r'\b[sS][cC][aA@][mM]+(?:mer|s)?\b',
    r'\b[fF][rR][aA@][uU][dD]+\b',
    r'\b[tT][hH][iI1!][eE3][fF]+\b',
    r'\b[cC][hH][eE3][aA@][tT]+(?:er|s|ing)?\b',
    r'\b[lL][iI1!][aA@][rR]+(?:s)?\b',
    
    # Spam patterns
    r'\b[sS][pP][aA@][mM]+\b',
]

# Compiled patterns for efficiency
COMPILED_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in BAD_WORDS_PATTERNS]


def contains_bad_words(text: str) -> Tuple[bool, List[str]]:
    """
    Check if text contains bad words
    Returns (contains_bad_words, list_of_found_bad_words)
    """
    if not text:
        return False, []
    
    found_words = []
    
    for pattern in COMPILED_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            found_words.extend(matches)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_words = []
    for word in found_words:
        word_lower = word.lower()
        if word_lower not in seen:
            seen.add(word_lower)
            unique_words.append(word)
    
    return len(unique_words) > 0, unique_words


def filter_bad_words(text: str, replacement: str = "***") -> str:
    """
    Replace bad words with replacement string
    Returns filtered text
    """
    if not text:
        return text
    
    filtered_text = text
    
    for pattern in COMPILED_PATTERNS:
        filtered_text = pattern.sub(replacement, filtered_text)
    
    return filtered_text


def get_filtered_content(text: str) -> dict:
    """
    Get both the filtered text and information about filtered content
    Returns dict with original, filtered, was_filtered, and filtered_words
    """
    if not text:
        return {
            'original': text,
            'filtered': text,
            'was_filtered': False,
            'filtered_words': []
        }
    
    has_bad_words, found_words = contains_bad_words(text)
    filtered_text = filter_bad_words(text) if has_bad_words else text
    
    return {
        'original': text,
        'filtered': filtered_text,
        'was_filtered': has_bad_words,
        'filtered_words': found_words
    }


def validate_content(text: str, max_length: int = 1000) -> Tuple[bool, str, str]:
    """
    Validate and filter user content
    Returns (is_valid, filtered_text, error_message)
    """
    if not text:
        return False, "", "Content cannot be empty"
    
    text = text.strip()
    
    if len(text) > max_length:
        return False, "", f"Content must be less than {max_length} characters"
    
    if len(text) < 3:
        return False, "", "Content must be at least 3 characters long"
    
    # Filter bad words
    filtered_text = filter_bad_words(text)
    
    return True, filtered_text, ""
